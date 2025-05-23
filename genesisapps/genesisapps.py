import discord
from discord.errors import Forbidden, NotFound, HTTPException
from discord.ui import View
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config, Group
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.chat_formatting import pagify

import re
import asyncio
from datetime import datetime, timedelta
from typing import Union, List

from .wufoo import Wufoo, FormNotFound, DiscordNameFieldNotFound, Entry, WufooDB
from .checklist import Checklist, ChecklistItem, ChecklistSelect
from .helpers import get_thread, MissingMember
from .application import Application, Image, identifiable_name
from .expiringdict import ExpiringDict
from .statusimage import StatusImage, statuses
from .log import log


RE_API_KEY = re.compile(r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$")

CHECKLIST_CHOICES = [
    "message",
    "checklist",
    "joined",
]

class MemberOrMissingMemberConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        try:
            return await commands.MemberConverter().convert(ctx, argument)
        except:
            return MissingMember(int(argument), ctx.guild)


class MemberOrMissingMemberOrRoleConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        try:
            return await commands.MemberConverter().convert(ctx, argument)
        except:
            try:
                return await commands.RoleConverter().convert(ctx, argument)
            except:
                return MissingMember(int(argument), ctx.guild)


class RoleOrStringConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        try:
            return await commands.RoleConverter().convert(ctx, argument)
        except:
            return argument


class AlarmConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        argument = argument.lower()
        if argument not in CHECKLIST_CHOICES:
            raise commands.BadArgument(f"argument must be one of: {', '.join(CHECKLIST_CHOICES.keys())}")
        return argument


class GenesisApps(commands.Cog):
    """Application management and tracking for the Genesis server. 
    
    Creates a thread for each applicant to track their progress.
    Integrates with Wufoo forms"""
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )

        self.config.register_member(**{
            "ID": None,
            "NAME": None,
            "UPDATE": False,
            "MESSAGES": 0,
            "TOTAL_MESSAGES": 0,
            "THREAD_ID": None,
            "DISPLAY_MESSAGE_ID": None,
            "LOG_MESSAGE_ID": None,
            "IMAGE_MESSAGE_URLS": [],
            "IMAGES": [],
            "IMAGE_INDEX": 0,
            "NICKNAMES": [],
            "CHECKLIST": {},
            "LEFT_AT": None,
            "STATUS": "Joined",
            "FIRST_MESSAGE_LINK": None,
            "AUTO_KICK_IMMUNITY": True,
            "LOG": [],
            "APP_CLOSED": False,
            "APP_EXEMPT": False,
            "FEEDBACK": [],
            "LAST_MESSAGE_DATE": None,
            "LAST_CHECKLIST_DATE": None,
            "TRACK_ALARMS": {kind: 0 for kind in CHECKLIST_CHOICES}
        })

        self.config.register_guild(**{
            "TRACKING_CHANNEL": None,
            "PEER_REVIEW_CHANNEL": None,
            "WUFOO_API_KEY": None,
            "WUFOO_FORM_URL": None,
            "WUFOO_DISCORD_USERNAME_FIELD": None,
            "WUFOO_ALERT_CHANNEL": None,
            "WUFOO_ENTRIES": {},
            "WUFOO_ENTRY_QUEUE": {},
            "WUFOO_MEMBER_MAP": {}, # TODO: rewrite with this as part of member/application...
            "CHECKLIST_TEMPLATE": {},
            "MENTION_ROLE": None,  # also mention when application complete
            "CHECKLIST_ROLES": {},  # TODO: roles that are allowed to toggle the checklist items
            "ROLE_SWAPS": {},
            "STATUS_IMAGES": {},
            "APPLICATION_EXEMPT_ROLE": None,
            "ALARMS": {kind: 0 for kind in CHECKLIST_CHOICES},
            "DAYS_TO_KICK_IF_NO_ACTIVITY": 0,
            "INACTIVITY_KICK_MSG": None,
            "APP_MEMBERS": {}
        })

        bot.add_dynamic_items(ChecklistSelect)

        self.wufoo_apis = {}
        self.applications = {}
        self.thread_member_map = {}
        self.nickname_map = {}
        self.audit_log_cache = {}
        self.ready = False
        self.ready_lock = asyncio.Lock()

    def get_member(self, guild: discord.Guild, member_id: int):
        if not (member := guild.get_member(member_id)):
            member = MissingMember(member_id, guild)
        return member
    
    def memberify(self, thing: Union[discord.Member, MissingMember, discord.Thread, str, Checklist], guild=None):
        member = thing
        if isinstance(thing, str):
            member = self.nickname_map[guild.id][thing.lower()]
        elif isinstance(thing, Checklist):
            member = thing.member
        elif isinstance(thing, discord.Thread):
            member = self.thread_member_map[thing.id]
        return member

    def application_for(self, thing: Union[discord.Member, MissingMember, discord.Thread, str, Checklist], guild=None):
        member = self.memberify(thing, guild)
        return self.applications[member.guild.id][member.id]
    
    async def send_entry_queue_list(self, ctx):
        s = '\n'.join(f"-# **{k}**. {ur}" for ur, k in self.wufoo_apis[ctx.guild.id].db.entry_queue.items())

        for p in pagify("**Unlinked applications:**\n" + s):
            await ctx.send(p)

    async def setup_wufoo_api(self, gid: int,  form_url: str, api_key: str, discord_name_field: str):
        self.wufoo_apis[gid] = Wufoo(form_url, api_key, discord_name_field)
        guild = self.bot.get_guild(gid)
        await self.wufoo_apis[gid].setup(self.bot, self.config.guild(guild), self.bot.get_guild(gid))
        return self.wufoo_apis[gid]
    
    async def setup_all_wufoo(self):
        guild_settings = await self.config.all_guilds()
        for gid, settings in guild_settings.items():
            if settings["WUFOO_API_KEY"]:
                await self.setup_wufoo_api(gid, 
                    settings["WUFOO_FORM_URL"], 
                    settings["WUFOO_API_KEY"], 
                    settings["WUFOO_DISCORD_USERNAME_FIELD"]
                )

    async def setup_applications(self):
        guild_settings = await self.config.all_guilds()
        for gid, settings in guild_settings.items():
            guild = self.bot.get_guild(gid)
            for smid in settings["APP_MEMBERS"]:
                member = self.get_member(guild, int(smid))
                try:
                    app = await Application.new(member, guild, self.config, self.bot)
                    self.set_application_for(member, app)
                except Exception as e:
                    log.error(e)
                    continue
                if  not app.closed and (isinstance(member, MissingMember) or await Application.app_exempt(self.config, member)):
                    await app.close()

    
    async def setup_thread_member_map(self):
        gmconf = await self.config.all_members()
        for gid, mconf in gmconf.items():
            guild = self.bot.get_guild(gid)
            for mid, conf in mconf.items():
                m = self.get_member(guild, mid)
                self.thread_member_map[conf["THREAD_ID"]] = m
        
    async def setup_nickname_map(self):
        gmconf = await self.config.all_members()
        for gid, mconf in gmconf.items():
            guild = self.bot.get_guild(gid)
            self.nickname_map[gid] = {}
            for mid, conf in mconf.items():
                member = self.get_member(guild, mid)
                for nick in conf['NICKNAMES']:
                    self.nickname_map[gid][nick] = member

    def set_application_for(self, member, app, guild=None):
        member = self.memberify(member, guild)
        self.applications.setdefault(member.guild.id, {})[member.id] = app

    async def get_or_set_application_for(self, member, guild=None):
        try:
            app = self.application_for(member, guild)
        except KeyError:
            extra = {}
            if member.guild.id in self.wufoo_apis:
                extra["wufooDB"] = self.wufoo_apis[member.guild.id].db
            self.set_application_for(
                member, 
                app := await Application.new(
                    member, member.guild, self.config, self.bot, **extra
                ), 
                guild
            )
        return app

    def _set_nicknames_for(self, member, nicknames):
        for nick in nicknames:
            self.nickname_map.setdefault(member.guild.id, {})[nick] = member

    async def _setup(self):
        if not self.ready:
            async with self.ready_lock:
                await self.setup_applications()
                log.info('apps set up')
                await self.setup_thread_member_map()
                log.info('threads set up')
                await self.setup_nickname_map()
                log.info('nicks set up')
                try:
                    await self.setup_all_wufoo()
                    log.info('wufoo set up')
                except Exception as e:
                    log.error(e)
                else:
                    for gid, apps in self.applications.items():
                        for app in apps.values():
                            if gid in self.wufoo_apis:
                                app.set_wufooDB(self.wufoo_apis[app.guild.id].db)
                                if app.wufoo_skipped:
                                    await app.post_if_needed()
                    log.info('posted apps')
            log.info('setup complete')
        self.ready = True

    @commands.Cog.listener()
    async def on_ready(self):
        await self._setup()

    async def cog_load(self):
        await self._setup()
        self.loop_task = self.bot.loop.create_task(self.display_loop())

    async def cog_unload(self):
        self.loop_task.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.bot:
            return
        if await Application.app_exempt(self.config, after):
            return
        if before.display_name != after.display_name or before.name != after.name:
            app = await self.get_or_set_application_for(after)
            await self.config.member(after).NAME.set(identifiable_name(after))
        before_ids = set([r.id for r in before.roles])
        after_ids = set([r.id for r in after.roles])
        if before_ids == after_ids:
            return
        
        # swap roles
        removed = before_ids - after_ids
        if removed:
            swaps = await self.config.guild(after.guild).ROLE_SWAPS()
            new_roles = set()
            for rid in removed:
                srid = str(rid)
                if srid in swaps:
                    new_roles.add(after.guild.get_role(swaps[srid]))
            if new_roles:
                try:
                    await after.add_roles(*new_roles, reason='role swap')
                except discord.Forbidden as e:
                    log.error(f"Failed to add roles for role swap for {after.name}", exc_info=e)
        
        # checklist roles
        app = await self.get_or_set_application_for(after)

        await app.checklist.update_roles(after)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        now = datetime.now()
        await self.config.member(member).LEFT_AT.set(int(now.timestamp()))
        app = await self.get_or_set_application_for(member)
        app.member = MissingMember(member.id, member.guild)

        await asyncio.sleep(5)  # wait for audit log update
        entry = self.audit_log_cache.get(member.guild.id, {}).pop(member.id, None)
        msg = action = "Left"
        if entry:
            action = {
                discord.AuditLogAction.kick: 'Kicked',
                discord.AuditLogAction.ban: 'Banned',
            }[entry.action]
            msg = f"{action} by {entry.guild.get_member(entry.user_id).mention} ({entry.reason or 'no reason'})"
        
        await self.config.member(member).STATUS.set(action)

        await app.log.post(msg, now)
        if app.displayed:
            await app.display()
            if entry:
                await app.thread.send(f"-# {member.mention} {msg} <t:{int(now.timestamp())}:R>")
        await app.close()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        
        await self.config.member(member).ID.set(member.id)
        await self.config.member(member).NAME.set(member.display_name)

        tracking_channel = await self.config.guild(member.guild).TRACKING_CHANNEL()
        if tracking_channel is None:
            return

        was_here_before = len(await self.config.member(member).LOG())
        
        app = await self.get_or_set_application_for(member)
        
        await app.set_messages(0)
        
        if app.thread:
            self.thread_member_map[app.thread.id] = member
        
        if was_here_before:
            await self.config.member(member).STATUS.set("Joined")
            if app.displayed and len(await app.checklist.done_items()):
                await app.display()  # opens app automatically
            await app.log.post("Joined", member.joined_at)
        else:
            # new joins are subject to auto-kicking
            await self.config.member(member).AUTO_KICK_IMMUNITY.set(False)
    
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        if entry.action in (discord.AuditLogAction.kick, discord.AuditLogAction.ban):
            if entry.guild.id not in self.audit_log_cache:
                self.audit_log_cache[entry.guild.id] = ExpiringDict(max_age=10)
            self.audit_log_cache[entry.guild.id][entry.target.id] = entry
            return
        
        if entry.action == discord.AuditLogAction.unban:
            app = await self.get_or_set_application_for(MissingMember(entry.target.id, entry.guild))
            await app.log.post(f"Unbanned by {entry.guild.get_member(entry.user_id).mention}", datetime.now())

    @commands.Cog.listener()
    async def on_gapps_checklist_update(self, checklist: Checklist):
        await checklist.app.record_checklist_update()
        await checklist.app.display()
        if await checklist.is_done():
            await checklist.app.close()
        
    @commands.Cog.listener()
    async def on_gapps_app_closed(self, app):
        for nick, member in list(self.nickname_map[app.member.guild.id].items()):
            # compare ids cause MissingMember != Member atm maybe change that later :eyes:
            if member.id == app.member.id:
                del self.nickname_map[app.member.guild.id][nick]
    
    @commands.Cog.listener()
    async def on_gapps_app_opened(self, app):
        nm = self.nickname_map.setdefault(app.member.guild.id, {})
        for nick in await self.config.member(app.member).NICKNAMES():
            nm[nick] = app.member
    
    @commands.Cog.listener()
    async def on_gapps_app_thread_set(self, app):
        self.thread_member_map[app.thread] = app.member

    @commands.Cog.listener()
    async def on_gapps_wufoo_entry_mapped(self, entries: List[Entry]):
        entries_per_guild = {}
        async with self.ready_lock:
            for entry in entries:
                app = await self.get_or_set_application_for(entry.member)
                await app.post_applications()
                entries_per_guild.setdefault(app.guild.id, []).append(entry)
            for gid, entries in entries_per_guild.items():
                guild = self.bot.get_guild(gid)
                cid = await self.config.guild(guild).WUFOO_ALERT_CHANNEL()
                channel = guild.get_channel(cid)
                if not channel:
                    log.error(f"Wufoo alert channel not set for guild: {guild.name}")
                    continue
                s = (
                    "**Newly mapped application forms**\n" + 
                    ("\n".join(f"-# **{e.key}**. **{e.username_raw}** mapped to {e.member.mention}" for e in entries))
                )
                for p in pagify(s, delims=["\n", " "], priority=True, page_length=1900, escape_mass_mentions=True):
                    await channel.send(p)

    @commands.Cog.listener()
    async def on_gapps_wufoo_entry_queued(self, db: WufooDB):
        channel = db.guild.get_channel(await self.config.guild(db.guild).WUFOO_ALERT_CHANNEL())
        if not channel:
            raise ValueError("Wufoo alert channel not set")
        await self.send_entry_queue_list(channel)

    @commands.Cog.listener()
    async def on_gapps_trigger_app_display(self, app: Application):
        await app.display()

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        # unarchive auto-archived threads
        if after.archived:
            try:
                app = self.application_for(after)
            except:
                return
            if not app.closed:
                await after.edit(archived=False)
                
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        # wave at new users is a message
        if message.is_system():
            return
        
        # dms
        if message.guild is None:
            return

        if not await self.config.guild(message.guild).TRACKING_CHANNEL():
            return

        # if in peer_review channel, check for mentions
        if message.channel.id == await self.config.guild(message.guild).PEER_REVIEW_CHANNEL():
            members_to_check_for = [app.member for app in self.applications.get(message.guild.id, {}).values() if not app.closed]

            mentions_map = {m.id: m for m in members_to_check_for}
            if message.mentions:
                members = set([m for m in message.mentions if m.id in mentions_map])
            else:
                members = set()

            name_map = {m.name.lower(): m for m in members_to_check_for}
            disp_map = {m.display_name.lower(): m for m in members_to_check_for}
            nick_map = {nick.lower(): mem for nick, mem in self.nickname_map[message.guild.id].items() if mem in members_to_check_for}
            the_map = {**nick_map, **name_map, **disp_map}

            if not the_map:
                return

            sr = r"(^|\W)" + "(?P<find>"
            er = ")" + r"($|\W)"
            pattern = sr + "|".join([re.escape(n) for n in the_map]) + er
            
            for m in re.finditer(pattern, message.content.lower()):
                members.add(the_map[m.group('find')])
            
            for m in members:
                app = await self.get_or_set_application_for(m, message.guild)
                await app.add_feedback(message)
            return

        # check if applicant
        if await Application.app_exempt(self.config, message.author):
            return
        
        app = await self.get_or_set_application_for(message.author)
        
        # increment message counter
        await app.new_message(message)
        
        # send images
        if (atts := [m for m in message.attachments if m.content_type.startswith("image")]):
            
            imgs = [Image(i.proxy_url, message.jump_url, False, c + len(app.images)) for c, i in enumerate(atts)]

            await app.post_images(imgs)
        
        if app.messages == 1:
            await app.display()

    async def display_loop(self):
        
        day = 0
        hour = 0
        while True:
            if not self.ready:
                await asyncio.sleep(5)
                continue

            try:
                now = datetime.now()
                prev_day = day
                day = now.day
                prev_hour = hour
                hour = now.hour
                for guild_id, apps in self.applications.items():
                    guild = self.bot.get_guild(guild_id)
                    if guild is None:
                        continue

                    kicked = []
                    days_to_autokick = await self.config.guild(guild).DAYS_TO_KICK_IF_NO_ACTIVITY()
                    joined_before_autokick = None
                    if days_to_autokick:
                        joined_before_autokick = now - timedelta(days=days_to_autokick)
                    autokick_msg = await self.config.guild(guild).INACTIVITY_KICK_MSG()

                    for member_id, app in apps.items():
                        # check roles
                        member = self.get_member(guild, member_id)
                        await app.checklist.update_roles(member)
                        # check if needs displaying
                        if app.update:
                            await app.display()
                        # member is still in server
                        if not isinstance(member, MissingMember):
                            # keep posts' archived state synchronized with app
                            if app.thread and (app.closed != app.thread.archived):
                                await app.thread.edit(archived=app.closed)
                            # check for auto-kicks
                            if joined_before_autokick:
                                joined_naive = datetime.fromtimestamp(member.joined_at.timestamp())
                                if (joined_naive < joined_before_autokick and 
                                    (not await app.seen_activity()) and
                                    not await self.config.member(member).AUTO_KICK_IMMUNITY()
                                ):
                                    if not await Application.app_exempt(self.config, member):
                                        if autokick_msg:
                                            try:
                                                await member.send(autokick_msg)
                                            except:
                                                pass
                                        await member.kick(reason="inactivity auto-kick")
                                        kicked.append(member)
                            # check for alarms
                            if prev_day != day and (not await Application.app_exempt(self.config, member)) and not app.closed:
                                await app.check_and_alarm()

                            if prev_hour != hour:
                                try:
                                    await app.check_application_forms()
                                except AttributeError:
                                    pass
                    if kicked:
                        cid = await self.config.guild(guild).WUFOO_ALERT_CHANNEL()
                        channel = guild.get_channel(cid)
                        if channel:
                            await channel.send(f"-# **Kicked due to inactivity:** {', '.join([m.mention for m in kicked])}")
                if prev_hour != hour:
                    for gid, wapi in self.wufoo_apis.items():
                        await wapi.pull_entries()
                    
                        
            except Exception as e:
                log.error("Error in display loop", exc_info=e)
            await asyncio.sleep(60*10)

    @commands.group(aliases=["gapps"])
    @checks.mod_or_permissions(manage_guild=True)
    async def genesisapps(self, ctx: commands.Context) -> None:
        """GenesisApps setup commands"""

    @genesisapps.command()
    async def autokick(self, ctx: commands.Context, days: int) -> None:
        """Set the number of days of no activity before a user is auto-kicked.
        
        Set to 0 to disable auto-kicking.
        Note that no activity means they joined the server and they've sent 
        no messages and haven't completed any of the checklist items."""
        if not ctx.guild.me.guild_permissions.kick_members:
            await ctx.send("Please ensure the bot has `Kick Members` permissions in order to be able to auto-kick members")
            return

        if days < 0:
            await ctx.send("Invalid number of days")
            return

        await self.config.guild(ctx.guild).DAYS_TO_KICK_IF_NO_ACTIVITY.set(days)
        if days == 0:
            await ctx.send("Disabled auto-kicking")
        else:
            await ctx.send(f"Users will now get automatically kicked if they haven't "
                           f"shown activity since joining for {days} days")

    @genesisapps.command()
    async def autokickmsg(self, ctx: commands.Context, *, msg: str=None) -> None:
        """Set the message DM'd to the user when they are auto-kicked.
        Leave blank to not send a DM"""

        await self.config.guild(ctx.guild).INACTIVITY_KICK_MSG.set(msg)
        if msg is None:
            await ctx.send("Disabled auto-kick message")
        else:
            await ctx.send(f"Auto-kick message set to:\n\n{msg}")

    @genesisapps.command()
    async def alarms(self, ctx: commands.Context, alarm: AlarmConverter, days: int) -> None:
        """Set alarms to be sent in app thread once specified number of days have passed since something has/hasn't happened
        
        The choices for the alarm triggers are days since last message, checklist (item), or joined.
        Set days to 0 to disable the alarm.
        Note that alarms won't trigger for applicants that are exempt or whose applications are closed."""

        if days < 0:
            await ctx.send("Invalid number of days")
            return
        
        mention_role = ctx.guild.get_role(await self.config.guild(ctx.guild).MENTION_ROLE())
        if not mention_role:
            await ctx.send("You may want to set the mention role with `[p]gapps mentionrole`")
        
        await self.config.guild(ctx.guild).ALARMS.set_raw(alarm, value=days)
        if days == 0:
            await ctx.send(f"Disabled alarm for {alarm}")
        else:
            await ctx.send(f"An alarm will now go off if {days} days have passed since last {alarm}")
    
    @genesisapps.command()
    async def exemptrole(self, ctx: commands.Context, role: discord.Role) -> None:
        """Set the role to be exempt from the application process. 
        This is usually the role that would be used to mark that the application is complete"""
        await self.config.guild(ctx.guild).APPLICATION_EXEMPT_ROLE.set(role.id)
        await ctx.send(f"Exempt role is set to {role.mention}")

    @genesisapps.command()
    async def swaproles(self, ctx: commands.Context, removed: discord.Role, added: discord.Role) -> None:
        """Sets up swapping roles. If the 'removed' role is removed, the 'added' role will be added onto the user"""
        if not ctx.guild.me.guild_permissions.manage_roles:
            await ctx.send("Please ensure the bot has `Manage Roles` permissions in order to be able to use swap roles")
            return
        
        await self.config.guild(ctx.guild).ROLE_SWAPS.set_raw(removed.id, value=added.id)
        await ctx.send(f"Now whenever {removed.mention} is removed, {added.mention} will be added")

    @genesisapps.command()
    async def open(self, ctx: commands.Context, member_or_member_id: MemberOrMissingMemberConverter) -> None:
        """Manually open a application thread for a user
        Note, no thread is made if the applicant is exempt
        """
        app = await self.get_or_set_application_for(member_or_member_id)
        if app.thread and app.closed:  
            await app.open()
        await app.display()
    
    @genesisapps.command()
    async def close(self, ctx: commands.Context, member_or_member_id: MemberOrMissingMemberConverter) -> None:
        """Close an application. Note that applications will reopen if changes happen to it.
        
        To permanently close applications, either manually make a user exempt or give them the exempt role"""
        app = await self.get_or_set_application_for(member_or_member_id)  
        await app.close()
        

    @genesisapps.command()
    async def delete(self, ctx: commands.Context, member_or_member_id: MemberOrMissingMemberConverter) -> None:
        """Delete an application !!All data will be lost for this application!!
        
        Applicants without the exempt role will have their applications recreated automatically once they show some activity.
        If instead you just want to make them exempt to the application process, either
         * give them the application exempt role or
         * make them exempt with `[p]gapps exempt <user>`"""
        mconf = self.config.member(member_or_member_id)
        forum_id = await self.config.guild(ctx.guild).TRACKING_CHANNEL()
        forum = ctx.guild.get_channel(forum_id)
        thread_id = await mconf.THREAD_ID()
        if forum_id is None:
            await ctx.send("No forum channel set. Use `[p]gapps trackforum <forum>` to set it")
            return
        if forum is None:
            await ctx.send("Tracking forum not found. Use `[p]gapps trackforum <forum>` to set it")
            return
        if thread_id is None:
            await ctx.send("No application found for this appplicant/member")
            return
        
        await ctx.reply("Are you sure you want to delete this application? This deletes all data stored in the bot for this user and the action cannot be undone. Type \"yes\" to continue.")
        message = await self.bot.wait_for('message', timeout=60, check=MessagePredicate.same_context(channel=ctx.channel, user=ctx.author))
        if 'yes' not in message.content.lower():
            await ctx.send("Canceling")
            return

        thread = await get_thread(forum, thread_id)
        app = await self.get_or_set_application_for(member_or_member_id)
        await app.close()
        deleted = "thread and data"
        if thread is None:
            await ctx.send("No thread found for this applicant/member")
            deleted = "data"
        else:
            try:
                await thread.delete()
            except Forbidden:
                await ctx.send("I don't have permissions to delete the application thread. Please give me `Manage Threads` permissions")
                return
        
        await self.config.guild(ctx.guild).APP_MEMBERS.clear_raw(f"{member_or_member_id.id}")
        await mconf.clear()
        await self.wufoo_apis[ctx.guild.id].db.delete_member_from_member_map(member_or_member_id)        
        del self.applications[ctx.guild.id][member_or_member_id.id]
        try:
            await ctx.send(f"Application {deleted} deleted")
        except NotFound:
            pass

    @genesisapps.command(aliases=["trackingforum", "trackingchannel"])
    async def trackforum(self, ctx: commands.Context, channel: discord.ForumChannel = None) -> None:
        """Set the forum channel to create applicant tracking threads in"""

        if channel is None:
            await self.config.guild(ctx.guild).TRACKING_CHANNEL.set(None)
            await ctx.send("Tracking forum has been unset")
            return

        if not ctx.guild.me.guild_permissions.view_audit_log:
            await ctx.send(
                "Please ensure the bot has `View Audit Log` permissions in order "
                "to be able to track a member's reason for leaving (kick/ban vs just leaving)"
            )
        
        if (not ctx.guild.me.guild_permissions.manage_messages) or (not ctx.guild.me.guild_permissions.manage_threads):
            await ctx.send("Please ensure the bot has `Manage Messages` and `Manage Threads` permissions in order to be able to create and pin application threads")
            return
        
        if (not channel.permissions_for(ctx.guild.me).create_public_threads):
            await ctx.send("Please ensure the bot has `Create Public Threads` permission in the forum channel")
            return

        await self.config.guild(ctx.guild).TRACKING_CHANNEL.set(channel.id)
        await ctx.send(f"Tracking forum is set to {channel.mention}")

    @genesisapps.command()
    async def peerchannel(self, ctx: commands.Context, channel: discord.TextChannel = None) -> None:
        """Set the peer review channel to listen to.
        
        Messages that mention the application user 
        (by mention, name, nickname, or `[p]gapps nick` nicknames)
        get posted in the tracking channel
        """
        
        if channel is None:
            await self.config.guild(ctx.guild).PEER_REVIEW_CHANNEL.set(None)
            await ctx.send("Peer Review channel has been unset")
            return
        await self.config.guild(ctx.guild).PEER_REVIEW_CHANNEL.set(channel.id)
        await ctx.send(f"Peer Review channel is set to {channel.mention}")

    @genesisapps.command()
    async def checklist(self, ctx: commands.Context) -> None:
        """View the application checklist"""
        await ctx.send(await Checklist(self.config.guild(ctx.guild).CHECKLIST_TEMPLATE, self.bot, ctx.guild).to_str())

    @genesisapps.command()
    async def checklistadd(self, ctx: commands.Context, *, role_or_txt: RoleOrStringConverter) -> None:
        """Add an item to the application checklist
        
        You can add a role by itself as well and the checklist item 
        will be marked off once the member has acquired that role. 
        Regular text checklist items must be marked off manually

        If the first word of the task is "Used" or "Contains", 
        the task will be marked off if the application contains that word

        If the task is "Application Sent", it will be marked off 
        when the member sends a Wufoo applicaiotn
        """

        cl = Checklist(self.config.guild(ctx.guild).CHECKLIST_TEMPLATE, self.bot, ctx.guild)
        await cl.add_item(ChecklistItem(role_or_txt))
        await ctx.send(f"Added checklist item. Checklist is now:\n {await cl.to_str()}")

    @genesisapps.command(aliases=['checklistrem', 'checklistdel', 'checklistdelete'])
    async def checklistremove(self, ctx: commands.Context, number: int) -> None:
        """Remove an item from the application checklist"""
        
        cl = Checklist(self.config.guild(ctx.guild).CHECKLIST_TEMPLATE, self.bot, ctx.guild)
        await cl.remove_item(await cl.get_item(number - 1))
        await ctx.send(f"Removed checklist item. Checklist is now:\n {await cl.to_str()}")

    @genesisapps.command()
    async def image(self, ctx: commands.Context):
        """Upload images to be used in displaying app thread states"""
        if not ctx.message.attachments:
            await ctx.send("Please send an image in the same message as you use this command")
            return
        if len(ctx.message.attachments) > 1:
            await ctx.send("Please send only one image")
            return
        
        att = ctx.message.attachments[0]

        alarms = await self.config.guild(ctx.guild).ALARMS()
        stats = {}
        statsli = []
        for s in await statuses(self.config.guild(ctx.guild)):
            if not alarms.get(s['value'], 1):
                continue
            if s.get("type") == "role":
                role = ctx.guild.get_role(s['value'])
                if not role:
                    continue
                s['display'] = f"{role.mention} acquired"
            if 'display' not in s:
                s['display'] = str(s['value'])
            stats[s['display'].lower()] = s
            statsli.append(s)
        await ctx.reply(
            "Which status do you want to set this image for?\n " +
            "\n ".join(f"{i+1}. {s['display']}" for i, s in enumerate(statsli)))

        try:
            message = await self.bot.wait_for("message", timeout=60, check=MessagePredicate.same_context(channel=ctx.channel, user=ctx.author))
        except asyncio.TimeoutError:
            await ctx.send("Took too long")
            return
        
        for i in range(len(statsli)):
            stats[i] = statsli[i]

        status = message.content.lower()
        try:
            status = int(status.split('.')[0]) - 1
        except:
            pass

        try:
            status = stats[status]
        except:
            await ctx.send("Invalid status. Please try again and respond with a number or the full status")
            return
        
        await StatusImage.new(self, ctx.guild, self.config, status['value'], att)
        await ctx.send(f"Image for {status['display']} set to {ctx.message.attachments[0].url}")

    @genesisapps.command()
    async def mentionrole(self, ctx: commands.Context, role_or_everyone: discord.Role = None) -> None:
        """Set the role to mention for application alarms
        
        When used without a role, no role will be mentioned
        """

        if role_or_everyone is None:
            await self.config.guild(ctx.guild).MENTION_ROLE.set(None)
            await ctx.send("Mention role has been unset")
            return
        await self.config.guild(ctx.guild).MENTION_ROLE.set(role_or_everyone.id)
        mention = role_or_everyone.mention
        if role_or_everyone.id == ctx.guild.default_role.id:
            mention = "@everyone"
        await ctx.send(f"Mention role is set to {mention}")

    @genesisapps.command()
    async def wufoo(self, ctx: commands.Context, form_url: str=None) -> None:
        """Setup Wufoo-related settings
        
        form_url should be the url to the Wufoo form"""
        if not form_url:
            await self.config.guild(ctx.guild).WUFOO_FORM_URL.set(None)
            await self.config.guild(ctx.guild).WUFOO_API_KEY.set(None)
            await self.config.guild(ctx.guild).WUFOO_DISCORD_USERNAME_FIELD.set(None)
            await self.config.guild(ctx.guild).WUFOO_ALERT_CHANNEL.set(None)
            del self.wufoo_apis[ctx.guild.id]
            await ctx.send("Wufoo integration has been unset")
            return
        
        tracking_channel = await self.config.guild(ctx.guild).TRACKING_CHANNEL()
        checklist = await self.config.guild(ctx.guild).CHECKLIST_TEMPLATE()
        if tracking_channel is None or not checklist:
            await ctx.send("Please set a tracking forum and your checklist items first")
            return

        author = ctx.author
        await author.send("Please send your Wufoo API key")
        await ctx.send("A message has been sent to you in a DM. Please respond with your Wufoo API key")
        try:
            message = await self.bot.wait_for("message", check=MessagePredicate.same_context(channel=author.dm_channel, user=author), timeout=120)
        except asyncio.TimeoutError:
            await author.send("Took too long. Please try again.")
        key = message.content.strip()
        if not RE_API_KEY.match(key):
            await author.send("That doesn't look like a valid Wufoo API key. Please try again")
            return
        
        await author.send("Please send the text for the question that prompts for their discord username")        
        try:
            message = await self.bot.wait_for("message", check=MessagePredicate.same_context(channel=author.dm_channel, user=author), timeout=120)
        except asyncio.TimeoutError:
            await author.send("Took too long. Please try again.")

        discord_username_field = message.content.strip()

        try:
            await self.setup_wufoo_api(ctx.guild.id, form_url, key, discord_username_field)
        except FormNotFound:
            await author.send("Could not find that form. Please ensure the form url is correct")
            return
        except DiscordNameFieldNotFound:
            await author.send("Could not find the discord name field. Please ensure you copy/pasted the question correctly")
            return

        await self.config.guild(ctx.guild).WUFOO_API_KEY.set(key)
        await self.config.guild(ctx.guild).WUFOO_DISCORD_USERNAME_FIELD.set(discord_username_field)
        await self.config.guild(ctx.guild).WUFOO_FORM_URL.set(form_url)
        await self.config.guild(ctx.guild).WUFOO_ALERT_CHANNEL.set(ctx.channel.id)
        await author.send("Wufoo settings have been updated")
        await ctx.send("Wufoo settings have been updated. Messages will be sent to this channel if a matching user can't be found for an application submitted")

    @commands.group(name="wufoo")
    @checks.mod_or_permissions(manage_guild=True)
    async def _wufoo(self, ctx: commands.Context) -> None:
        """Wufoo application commands"""

    @_wufoo.command()
    async def list(self, ctx: commands.Context) -> None:
        """List applications that haven't been linked to a member yet"""
        await self.send_entry_queue_list(ctx)
    
    @_wufoo.command()
    async def show(self, ctx: commands.Context, *, application: str) -> None:
        """Show the given application"""
        db = self.wufoo_apis[ctx.guild.id].db
        try:
            entry = db.get_queue_entry(application)
        except KeyError:
            await ctx.send(f"Could not find application: {application}")
            return
        
        cl = Checklist(self.config.guild(ctx.guild).CHECKLIST_TEMPLATE, self.bot, ctx.guild)
        to_highlights = []
        for c in await cl.checklist_items():
            ci_title = str(c.value).lower()
            if ci_title.startswith(('used', 'contains')):
                to_find = ci_title.split(' ', 1)[-1]
                to_highlights.append(to_find)

        for e in entry.embeds(to_highlights):
            await ctx.send(embed=e)

    @_wufoo.command()
    async def ignore(self, ctx: commands.Context, *, applications: str) -> None:
        """Ignore applications from the given comma-separated list"""
        db = self.wufoo_apis[ctx.guild.id].db
        applications = [a.strip() for a in applications.split(",")]
        for qk in applications:
            try:
                db.get_queue_entry(qk)
            except KeyError:
                await ctx.send(f"Could not find application: {qk}")
                return
        
        await ctx.reply("Are you sure? There is no turning back (yes/no)")
        try:
            message = await self.bot.wait_for('message', check=MessagePredicate.same_context(channel=ctx.channel, user=ctx.author), timeout=120)
        except asyncio.TimeoutError:
            await ctx.send("Took too long. Please try again.")
            return

        if message.content.lower() != "yes":
            await ctx.send("Cancelled")
            return

        await db.remove_entries(applications)
        await ctx.reply(f"Ignored these applications")

    @_wufoo.command()
    async def link(self, ctx: commands.Context, member: discord.Member, *, application: str) -> None:
        """Link a given application to a member. Give the member first followed by their application.
        
        If the application is no longer in the `[p]app list`, you must use the Entry ID to reference the application"""
        db = self.wufoo_apis[ctx.guild.id].db
        try:
            db.get_queue_entry(application)
        except KeyError:
            await ctx.send(f"Could not find application: {application}")
            return
        
        await self.get_or_set_application_for(member)
        
        await db.link(application, member)
        await ctx.reply(f"Linked **{application}** to {member.mention}")
    
    @_wufoo.command()
    async def linkhere(self, ctx: commands.Context, *, application: str) -> None:
        """Link a given application to the thread that the command was used in

        If the application is no longer in the `[p]app list`, you must use the Entry ID to reference the application"""
        db = self.wufoo_apis[ctx.guild.id].db
        try:
            db.get_queue_entry(application)
        except KeyError:
            await ctx.send(f"Could not find application: {application}")
            return 
        
        member = await self.get_or_set_application_for(ctx.channel)

        await db.link_member(application, member)
        await ctx.reply(f"Linked **{application}** to {ctx.author.mention}")

    @_wufoo.command()
    async def unlink(self, ctx: commands.Context, *, application: str) -> None:
        """Unlink a given application from a member"""
        db = self.wufoo_apis[ctx.guild.id].db

        if application not in db.entries:
            await ctx.send(f"Could not find application. Make sure to use the Entry ID.")
            return

        removed_from = await db.unlink(application)
        if not removed_from:
            removed_from = ["MissingMember"]
        else:
            removed_from = [r.mention for r in removed_from]
        await ctx.reply(f"Unlinked **{application}** from " + (",".join(removed_from)))
    
    @_wufoo.command()
    async def requeue(self, ctx: commands.Context, *, application: str) -> None:
        """Requeue a given application"""
        db = self.wufoo_apis[ctx.guild.id].db

        if application not in db.entries:
            await ctx.send(f"Could not find application. Make sure to use the Entry ID.")
            return
        
        removed_from = await db.unlink(application)
        if not removed_from:
            removed_from = ["MissingMember"]
        else:
            removed_from = [r.mention for r in removed_from]
        await db.unlink(application, enqueue=True)
        await ctx.reply(f"Requeued **{application}** from " + (",".join(removed_from)))

    @_wufoo.command()
    async def check(self, ctx: commands.Context) -> None:
        """Check for new applications. Note, this shouldn't be used too often as we can only make 100 accesses to the API a day"""
        msg = await ctx.send("Checking Wufoo for more applications...")
        await self.wufoo_apis[ctx.guild.id].pull_entries()
        await msg.edit(content="Done")
    
    @commands.group(aliases=["apps", "app"])
    @checks.mod_or_permissions(manage_guild=True)
    async def application(self, ctx: commands.Context) -> None:
        """Application modding commands"""

    @application.command(aliases=["nickname"])
    async def nick(self, ctx: commands.Context, member: discord.Member, *nicknames: str) -> None:
        """Set nicknames for a user
        
        When users use one of these nicknames in 
        """
        try:
            app = await self.get_or_set_application_for(member)
        except:
            await ctx.send(f"There is no application for {member.mention}")
            return
        
        oldnicks = await self.config.member(member).NICKNAMES()
        await self.config.member(member).NICKNAMES.set(nicknames)

        if not app.closed:
            self._set_nicknames_for(member, nicknames)

        if oldnicks:
            await ctx.send(
                f"Nicknames for {member.mention} have been changed from\n"
                f"{', '.join(oldnicks)}\nto\n{', '.join(nicknames)}"
            )
        else:
            await ctx.send(f"Nicknames for {member.mention} have been set to {', '.join(nicknames)}")

    @application.command()
    async def autokickimmune(self, ctx: commands.Context, member: discord.Member) -> None:
        """Toggle whether or not a user is immune to inactivity auto-kicking"""
        setting = not await self.config.member(member).AUTO_KICK_IMMUNITY()
        await self.config.member(member).AUTO_KICK_IMMUNITY.set(setting)
        if setting:
            await ctx.send(f"{member.mention} is now immune to inactivity auto-kicking")
        else:
            await ctx.send(f"{member.mention} is no longer immune to inactivity auto-kicking")

    @application.command()
    async def exempt(self, ctx: commands.Context, member: discord.Member) -> None:
        """Toggle a user's exemption to the application process. 
        Users that are exempt are still tracked, but their application thread isn't updated
        and no actions are taken based on their application"""
        role_found = await Application.has_exempt_role(self.config, member)
        
        exempt = not await Application.has_manual_exempt(self.config, member)
        await Application.set_manual_exempt(self.config, member, exempt)
        if exempt:
            await ctx.send(f"{member.mention} is now exempt from the application process")
        else:
            await ctx.send(f"{member.mention} is no longer exempt from the application process")
        if role_found:
            await ctx.send(f"Although, this user already has the **{role_found.name}** role. Regardless of this setting, the user will already be exempt.")
        if exempt or role_found:
            await (await self.get_or_set_application_for(member)).close()