import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from redbot.core.utils.predicates import MessagePredicate

import re
import asyncio

from .wufoo import Wufoo, FormNotFound, DiscordNameFieldNotFound, MemberNotFound


RE_API_KEY = re.compile(r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$")


class GenesisApps(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )

        self.config.register_member(**{
            "UPDATE": True,
            "MESSAGES": 0,
            "THREAD_ID": None,
            "DISPLAY_MESSAGE_ID": None,
            "STATUS_UPDATES": [],
            "IMAGES": [],
            "NICKNAMES": {}
        })

        self.config.register_guild(**{
            "TRACKING_CHANNEL": None,
            "WUFOO_API_KEY": None,
            "WUFOO_FORM_URL": None,
            "WUFOO_DISCORD_USERNAME_FIELD": None
        })

        self.wufoo_apis = {}

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
    
    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_all_wufoo()

    async def cog_load(self):
        await self.setup_all_wufoo()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # 
        pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # if thread doesn't exist, 
        #   create it
        # add new joined_ats
        # post display message
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        pass

    @commands.group(aliases=["gapps"])
    @checks.admin_or_permissions(manage_guild=True)
    async def genesisapps(self, ctx: commands.Context) -> None:
        """GenesisApps setup commands"""

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
