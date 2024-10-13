import discord
from discord.errors import Forbidden, NotFound
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from redbot.core.utils.predicates import MessagePredicate

import re
import asyncio
from datetime import datetime
from typing import Union

from .wufoo import Wufoo, FormNotFound, DiscordNameFieldNotFound, MemberNotFound
from .checklist import Checklist, ChecklistItem


RE_API_KEY = re.compile(r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$")


class Log:
    def __init__(self, channel: discord.TextChannel, message: discord.Message=None):
        self.message = message
        self.channel = channel
    
    async def post(self, content: str, timestamp: int=None):
        if self.message is None:
            self.message = await self.channel.send(f"**Log:**\n{LogEntry(content, timestamp)}")
        else:
            self.message = await self.message.edit(
                content=f"{self.message.content}\n{LogEntry(content, timestamp)}"
            )
        return self.message


class LogEntry:
    def __init__(self, content: str, timestamp: datetime=None):
        self.content = content
        self.timestamp = timestamp
    
    def __str__(self):
        now = datetime.now()
        if self.timestamp is not None:
            now = self.timestamp
        nowts = int(now.timestamp())
        return f"-# <t:{nowts}:d><t:{nowts}:t> (<t:{nowts}:R>) - **{self.content}**"


# can't inherit from discord.Member cause trying to set id gives an error
# and I didn't want to look into it further
class MissingMember:
    def __init__(self, id: int, guild: discord.Guild):
        self.id = id
        self.guild = guild
        self.roles = []
        self.mention = f"<@{self.id}>"
    
    def __str__(self):
        return self.mention()

async def get_thread(forum, thread_id):
    thread = forum.get_thread(thread_id)
    if thread is None:
        async for t in forum.archived_threads():
            if t.id == thread_id:
                return t
    return thread


class Application:
    def __init__(self, member: discord.Member, guild: discord.Guild, config: Config, bot: Red):
        self.guild = guild
        self.member = member
        self.config = config
        self.thread: discord.Thread
        self.checklist: Checklist
        self.display_message: discord.Message
        self.log: Log
        self.bot = bot

    @classmethod
    async def new(cls, member: discord.Member, guild: discord.Guild, config: Config, bot: Red):
        app = cls(member, guild, config, bot)

        forum = guild.get_channel(await config.guild(guild).TRACKING_CHANNEL())

        mconf = config.member(member)
        # if user's first join
        if (
            await mconf.THREAD_ID() is None or 
            not (thread := await get_thread(forum, await app.config.member(member).THREAD_ID()))
        ):
            # record member
            await config.guild(guild).APP_MEMBERS.set_raw(f"{member.id}", value=True)

            await app.create_checklist()

            thread = await app.create_thread()
        else:
            app.checklist = await Checklist.new(app.config.member(member).CHECKLIST, app.bot, app.guild, app.member, app)

        app.thread = thread
        app.display_message = await app.thread.fetch_message(await app.config.member(member).DISPLAY_MESSAGE_ID())
        logmsg = await app.thread.fetch_message(await app.config.member(member).LOG_MESSAGE_ID())
        app.log = Log(app.thread, logmsg)
        return app

    async def create_checklist(self):
        mconf = self.config.member(self.member)
        if await mconf.THREAD_ID() is None:
            cl = await Checklist.new_from_template(
                await self.config.guild(self.guild).CHECKLIST_TEMPLATE(),
                mconf.CHECKLIST, self.bot, self.guild, self.member
            )
        else:
            cl = await Checklist.new(mconf.CHECKLIST, self.bot, self.guild, self.member, self)
        self.checklist = cl

    async def create_thread(self):
        return await self.display()

    @property
    def closed(self):
        return self.thread.archived
    
    async def open(self):
        self.thread = await self.thread.edit(archived=False)
        self.bot.dispatch("gapps_app_opened", self)

    async def close(self):
        self.thread = await self.thread.edit(archived=True)
        self.bot.dispatch("gapps_app_closed", self)

    async def display(self):
        if isinstance(self.member, MissingMember):
            joinmsg = f"{self.member.mention} left/kicked <t:{await self.config.member(self.member).LEFT_AT()}:R>"
        else:
            joinmsg = f"{self.member.mention} joined <t:{int(self.member.joined_at.timestamp())}:R>"
        
        msgs = await self.config.member(self.member).MESSAGES()
        firstmsglink = await self.config.member(self.member).FIRST_MESSAGE_LINK()

        msgsmsg = f"__**{msgs}**__ messages" + (f" ({firstmsglink})" if firstmsglink else "")

        rolesmsg = "**Roles:**\n" + " ".join(r.mention for r in self.member.roles if r != self.guild.default_role)

        checklistmsg = f"**Checklist:**\n" + await self.checklist.to_str()

        txt = f"{joinmsg}\n{msgsmsg}\n\n{rolesmsg}\n\n{checklistmsg}"

        mconf = self.config.member(self.member)
        if await mconf.THREAD_ID() is None:
            forum = self.guild.get_channel(await self.config.guild(self.guild).TRACKING_CHANNEL())
            thread_with_message = await forum.create_thread(
                name=self.member.name,
                content=txt
            )
            await mconf.THREAD_ID.set(thread_with_message.thread.id)
            await mconf.DISPLAY_MESSAGE_ID.set(thread_with_message.message.id)
            log = Log(thread_with_message.thread)
            logmsg = await log.post("Joined", self.member.joined_at)
            await mconf.LOG_MESSAGE_ID.set(logmsg.id)

            await thread_with_message.message.pin()
            await logmsg.pin()

            return thread_with_message.thread
        else:
            # unarchive thread if archived
            await self.open()
            return await self.display_message.edit(content=txt)


class MemberOrMissingMemberConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        try:
            return await commands.MemberConverter().convert(ctx, argument)
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
            "UPDATE": True,
            "MESSAGES": 0,
            "THREAD_ID": None,
            "DISPLAY_MESSAGE_ID": None,
            "LOG_MESSAGE_ID": None,
            "STATUS_UPDATES": [],
            "CHECKLIST": {},
            "LEFT_AT": None
        })

        self.config.register_guild(**{
            "TRACKING_CHANNEL": None,
            "WUFOO_API_KEY": None,
            "WUFOO_FORM_URL": None,
            "WUFOO_DISCORD_USERNAME_FIELD": None,
            "CHECKLIST_TEMPLATE": {},
            "APP_MEMBERS": {}
        })

        self.wufoo_apis = {}
        self.applications = {}
        self.thread_member_map = {}
        self.ready = False

    def get_member(self, guild: discord.Guild, member_id: int):
        if not (member := guild.get_member(member_id)):
            member = MissingMember(member_id, guild)
        return member

    def application_for(self, member_or_thread_or_nick: Union[discord.Member, MissingMember, discord.Thread, str], guild=None):
        member = (mtn := member_or_thread_or_nick)
        if isinstance(mtn, str):
            member = self.nickname_map[guild.id][mtn]
        elif isinstance(mtn, discord.Thread):
            member = self.thread_member_map[mtn.id]
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

    def set_application_for(self, member, app):
        self.applications.setdefault(member.guild.id, {})[member.id] = app
        print(f"applications: {self.applications}")

    async def _setup(self):
        if not self.ready:
            await self.setup_applications()
            await self.setup_all_wufoo()
            await self.setup_thread_member_map()
        self.ready = True

    @commands.Cog.listener()
    async def on_ready(self):
        await self._setup()

    async def cog_load(self):
        await self._setup()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        now = datetime.now()
        await self.config.member(member).LEFT_AT.set(int(now.timestamp()))
        (app := self.application_for(member)).member = MissingMember(member.id, member.guild)
        await app.log.post("Left", now)
        await app.display()

        await app.close()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.config.member(member).ID.set(member.id)

        tracking_channel = await self.config.guild(member.guild).TRACKING_CHANNEL()
        if tracking_channel is None:
            return

        was_here_before = await self.config.member(member).THREAD_ID()
        
        self.set_application_for(member, app := await Application.new(member, member.guild, self.config, self.bot))
        self.thread_member_map[app.thread.id] = member
        
        if was_here_before:
            await app.display()
            await app.log.post("Joined", member.joined_at)
            await app.thread.send(f"-# {member.mention} rejoined <t:{int(datetime.now().timestamp())}:R>")

    @commands.Cog.listener()
    async def on_gapps_checklist_update(self, checklist: Checklist):
        # check if all checklist items are done
        # if done send alert mentioning role
        # display
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        pass

    @commands.group(aliases=["gapps"])
    @checks.admin_or_permissions(manage_guild=True)
    async def genesisapps(self, ctx: commands.Context) -> None:
        """GenesisApps setup commands"""

    @genesisapps.command()
    async def delete(self, ctx: commands.Context, member_or_member_id: MemberOrMissingMemberConverter) -> None:
        """Delete an application !!All data will be lost for this application!!"""
        mconf = self.config.member(member_or_member_id)
        forum = ctx.guild.get_channel(await self.config.guild(ctx.guild).TRACKING_CHANNEL())
        if not (thread_id := await mconf.THREAD_ID()):
            await ctx.send("No forum channel set. Use `[p]gapps trackforum <forum>` to set it")
            return
        if forum is None:
            await ctx.send("Tracking forum not found. Use `[p]gapps trackforum <forum>` to set it")
            return
        
        thread = await get_thread(forum, thread_id)
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
        try:
            await ctx.send(f"Application {deleted} deleted")
        except NotFound:
            pass
    
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
