import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config


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
            "TRACKING_CHANNEL": None
        })

    
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

    
