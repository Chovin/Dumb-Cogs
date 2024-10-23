import discord
from discord.errors import Forbidden, NotFound, HTTPException
from discord.ui import View
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config, Group
from redbot.core.utils.predicates import MessagePredicate

import re
import asyncio
from datetime import datetime
from typing import Union

from .wufoo import Wufoo, FormNotFound, DiscordNameFieldNotFound, MemberNotFound
from .checklist import Checklist, ChecklistItem, ChecklistSelect
from .helpers import get_thread, MissingMember
from .application import Application, Image, identifiable_name
from .expiringdict import ExpiringDict
from .log import log


RE_API_KEY = re.compile(r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$")


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


class GenesisApps(commands.Cog):
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
            "LAST_CHECKLIST_DATE": None
        })

        self.config.register_guild(**{
            "TRACKING_CHANNEL": None,
            "PEER_REVIEW_CHANNEL": None,
            "WUFOO_API_KEY": None,
            "WUFOO_FORM_URL": None,
            "WUFOO_DISCORD_USERNAME_FIELD": None,
            "CHECKLIST_TEMPLATE": {},
            "MENTION_ROLE": None,  # also mention when application complete
            "CHECKLIST_ROLES": {},  # roles that are allowed to toggle the checklist items
            "ROLE_SWAPS": {},
            "APPLICATION_EXEMPT_ROLE": None,
            "DAYS_NO_MESSAGE_ALARM": None,
            "DAYS_NO_CHECKLIST_ALARM": None,
            "DAYS_SINCE_JOIN_ALARM": None,
            "DAYS_TO_KICK_IF_NO_ACTIVITY": None,
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

    async def setup_wufoo_api(self, gid: int,  form_url: str, api_key: str, discord_name_field: str):
        self.wufoo_apis[gid] = Wufoo(form_url, api_key, discord_name_field)
        await self.wufoo_apis[gid].setup()
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
                self.set_application_for(member, await Application.new(member, guild, self.config, self.bot))
    
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
            self.set_application_for(member, app := await Application.new(member, member.guild, self.config, self.bot), guild)
        return app

    def _set_nicknames_for(self, member, nicknames):
        for nick in nicknames:
            self.nickname_map.setdefault(member.guild.id, {})[nick] = member

    async def _setup(self):
        if not self.ready:
            await self.setup_applications()
            # try:
            #   await self.setup_all_wufoo()
            # except AssertionError:
            #   print("wufoo api failed to load")
            await self.setup_thread_member_map()
            await self.setup_nickname_map()
        self.ready = True

    @commands.Cog.listener()
    async def on_ready(self):
        await self._setup()

    async def cog_load(self):
        try:
            await self._setup()
        except:
            pass
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
        if set([r.id for r in before.roles]) == set([r.id for r in after.roles]):
            return
        
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
        
        # TODO: self.thread_member_map[app.thread.id] = member
        
        if was_here_before:
            await self.config.member(member).STATUS.set("Joined")
            if app.displayed:
                await app.display()  # opens app automatically
            await app.log.post("Joined", member.joined_at)
            if app.displayed:
                await app.thread.send(f"-# {member.mention} rejoined <t:{int(datetime.now().timestamp())}:R>")
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
        await checklist.app.display()
        if await checklist.is_done():
            await checklist.app.close()
        await checklist.app.record_checklist_update()
        
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
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        # wave at new users is a message
        if message.is_system():
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
            pattern = sr + "|".join(the_map) + er
            
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
        
        # resend images
        if (atts := [m for m in message.attachments if m.content_type.startswith("image")]):
            
            imgs = [Image(i.proxy_url, message.jump_url, False, c + len(app.images)) for c, i in enumerate(atts)]

            await app.post_images(imgs)
        
        if app.messages == 1:
            await app.display()

    async def display_loop(self):
        while True:
            try:
                for guild_id, apps in self.applications.items():
                    guild = self.bot.get_guild(guild_id)
                    if guild is None:
                        continue
                    for member_id, app in apps.items():
                        member = self.get_member(guild, member_id)
                        await app.checklist.update_roles(member)
                        if app.update:
                            await app.display()
            except Exception as e:
                log.error("Error in display loop", exc_info=e)
            await asyncio.sleep(60*10)

    @commands.group(aliases=["gapps"])
    @checks.admin_or_permissions(manage_guild=True)
    async def genesisapps(self, ctx: commands.Context) -> None:
        """GenesisApps setup commands"""

    @genesisapps.command()
    async def autokickimmune(self, ctx: commands.Context, member: discord.Member) -> None:
        """Toggle whether or not a user is immune to inactivity auto-kicking"""
        setting = not await self.config.member(member).AUTO_KICK_IMMUNE()
        await self.config.member(member).AUTO_KICK_IMMUNE.set(setting)
        if setting:
            await ctx.send(f"{member.mention} is now immune to inactivity auto-kicking")
        else:
            await ctx.send(f"{member.mention} is no longer immune to inactivity auto-kicking")

    @genesisapps.command()
    async def create(self, ctx: commands.Context, member_or_member_id: MemberOrMissingMemberConverter) -> None:
        """Manually create a application thread for a user
        Note, no thread is made if the applicant is exempt
        """
        app = await self.get_or_set_application_for(member_or_member_id)        
        await app.display()

    @genesisapps.command()
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
        await ctx.send(f"Although, this user already has the **{role_found.name}** role. Regardless of this setting, the user will already be exempt.")
        if exempt or role_found:
            await (await self.get_or_set_application_for(member)).close()
    
    @genesisapps.command()
    async def exemptrole(self, ctx: commands.Context, role: discord.Role) -> None:
        """Set the role to be exempt from the application process. 
        This is usually the role that would be used to mark that the application is complete"""
        await self.config.guild(ctx.guild).APPLICATION_EXEMPT_ROLE.set(role.id)
        await ctx.send(f"Exempt role is set to {role.mention}")

    @genesisapps.command()
    async def delete(self, ctx: commands.Context, member_or_member_id: MemberOrMissingMemberConverter) -> None:
        """Delete an application **!!All data will be lost for this application!!**
        
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
        del self.applications[ctx.guild.id][member_or_member_id.id]
        try:
            await ctx.send(f"Application {deleted} deleted")
        except NotFound:
            pass
    
    @genesisapps.command(aliases=["nickname"])
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


    @genesisapps.command()
    async def trackforum(self, ctx: commands.Context, channel: discord.ForumChannel = None) -> None:
        """Set the forum channel to create applicant tracking threads in"""

        if channel is None:
            await self.config.guild(ctx.guild).TRACKING_CHANNEL.set(None)
            await ctx.send("Tracking forum has been unset")
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
    async def wufoo(self, ctx: commands.Context, form_url: str) -> None:
        """Setup Wufoo-related settings
        
        form_url should be the url to the Wufoo form"""
        
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
        await author.send("Wufoo settings have been updated")
