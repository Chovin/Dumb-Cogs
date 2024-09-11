import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config


class Invasion(commands.Cog):
    """
    Monsters are invading and they want your currency! Can your server fight them off?
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )
        self.config.register_guild(**{
            "VISIT_ON": None, 
            "MENTION_ROLE": None,
            "ENABLED_CHANNELS": [],
            "MIN_INVASION_FREQUENCY_MINUTES": 60*6,
            "MAX_INVASION_FREQUENCY_MINUTES": 60*10,
            "MIN_REWARD": 50,
            "MAX_REWARD": 150,
            "MIN_PENALTY": 10,
            "MAX_PENALTY": 100,
            "MIN_USERS_TO_PENALIZE": 1,
            "MAX_USERS_TO_PENALIZE": 4
        })
        
    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    async def invasion(self, ctx: commands.Context) -> None:
        """Invasion preparation commands"""
        if ctx.invoked_subcommand is None:
            channels = [
                ctx.guild.get_channel(cid) for cid in 
                (await self.config.guild(ctx.guild).VISIT_ON() or [])
            ]
            role = ctx.guild.get_role(await self.config.guild(ctx.guild).MENTION_ROLE())
            min_freq = await self.config.guild(ctx.guild).MIN_INVASION_FREQUENCY_MINUTES()
            max_freq = await self.config.guild(ctx.guild).MAX_INVASION_FREQUENCY_MINUTES()
            min_hours = min_freq / 60
            max_hours = max_freq / 60
            min_reward = await self.config.guild(ctx.guild).MIN_REWARD()
            max_reward = await self.config.guild(ctx.guild).MAX_REWARD()
            min_penalty = await self.config.guild(ctx.guild).MIN_PENALTY()
            max_penalty = await self.config.guild(ctx.guild).MAX_PENALTY()
            min_users = await self.config.guild(ctx.guild).MIN_USERS_TO_PENALIZE()
            max_users = await self.config.guild(ctx.guild).MAX_USERS_TO_PENALIZE()

            embed = discord.Embed(
                title="Invasion Settings",
                description=(
                    f"**Defenseless channels**: {', '.join([c.mention for c in channels])}\n"
                    f"**Defender role**: {role or role.mention}\n"
                    f"**Invasion frequency**: " + (
                        f"{min_hours:.2f} to {max_hours:.2f} hours" if min_hours > 1 else 
                        f"{min_freq} to {max_freq} minutes") + "\n"
                    f"**Reward**: {min_reward} to {max_reward}\n"
                    f"**Penalty**: {min_penalty} to {max_penalty}\n"
                    f"**Users to penalize**: {min_users} to {max_users}"
                ),
                colour=discord.Colour.blue()
            )
            await ctx.send(embed=embed)
            await ctx.send_help(ctx.command)
    
    @invasion.command()
    async def role(self, ctx: commands.Context, role: discord.Role = None) -> None:
        """Set the role that will be mentioned when a monster is attacking"""

        await self.config.guild(ctx.guild).MENTION_ROLE.set(role or role.id)
        if role is not None:
            await ctx.send(f"The {role.name} role will now be mentioned when a monster attacks.")
        else:
            await ctx.send(f"Nobody will be mentioned when a monster attacks.")

    @invasion.command()
    async def channel(self, ctx: commands.Context, channel: discord.TextChannel = None) -> None:
        """Weakens defenses on a channel, incentivising monsters to attack there"""

        guild = ctx.guild
        channel = channel or ctx.channel
        cid = channel.id
        enabled_channels = await self.config.guild(guild).ENABLED_CHANNELS()
        if cid in enabled_channels:
            enabled_channels.remove(cid)
            await self.config.guild(guild).ENABLED_CHANNELS.set(list(set(enabled_channels)))
            await ctx.send(f"Defenses have been built up in {channel.mention}. Monsters will no longer attack this channel.")
            return
        enabled_channels.append(cid)
        await self.config.guild(guild).ENABLED_CHANNELS.set(list(set(enabled_channels)))
        await ctx.send(f"You strategicly put a hole in the defenses in {channel.mention}. Monsters will now attack this channel.")

    @invasion.command()
    async def frequency(self, ctx: commands.Context, min_mins: int, max_mins: int = 0) -> None:
        """Set the frequency of invasions in minutes"""

        if min_mins < 10:
            await ctx.send("The minimum frequency is 10 minutes.")
            return
        if max_mins == 0:
            max_mins = min_mins
        if max_mins < min_mins:
            await ctx.send("The maximum frequency must be greater than or equal to the minimum frequency.")
            return
        await self.config.guild(ctx.guild).MIN_INVASION_FREQUENCY_MINUTES.set(min_mins)
        await self.config.guild(ctx.guild).MAX_INVASION_FREQUENCY_MINUTES.set(max_mins)
        await ctx.send(f"Monsters will now attack every {min_mins} to {max_mins} minutes.")

    @invasion.command()
    async def reward(self, ctx: commands.Context, min_amt: int, max_amt: int = 0) -> None:
        """Set the amount of currency you get for fighting off a monster"""

        if min_amt < 0:
            await ctx.send("The minimum reward must be greater than or equal to 0.")
            return
        if max_amt == 0:
            max_amt = min_amt
        if max_amt < min_amt:
            await ctx.send("The maximum reward must be greater than or equal to the minimum reward.")
            return
        await self.config.guild(ctx.guild).MIN_REWARD.set(min_amt)
        await self.config.guild(ctx.guild).MAX_REWARD.set(max_amt)
        await ctx.send(f"Your citizens will now gain from between {min_amt} and {max_amt} currency per monster taken down.")

    @invasion.command()
    async def penalty(self, ctx: commands.Context, min_amt: int, max_amt: int = 0) -> None:
        """Set the amount of currency you lose for failing to fight off an monster"""

        if min_amt < 0:
            await ctx.send("The minimum penalty must be greater than or equal to 0.")
            return
        if max_amt == 0:
            max_amt = min_amt
        if max_amt < min_amt:
            await ctx.send("The maximum penalty must be greater than or equal to the minimum penalty.")
            return
        await self.config.guild(ctx.guild).MIN_PENALTY.set(min_amt)
        await self.config.guild(ctx.guild).MAX_PENALTY.set(max_amt)
        await ctx.send(f"Your citizens will now lose from between {min_amt} and {max_amt} currency if a monster isn't taken down.")
    
    @invasion.command()
    async def affected(self, ctx: commands.Context, min_amt: int = 1, max_amt: int = 0) -> None:
        """Set the number of users that will be affected by an invasion.
        
        If a monster isn't fought off, this number of users will have a chance of being penalized.
        Set both min and maxto 0 to disable penalties."""

        if min_amt < 0:
            await ctx.send("The minimum number of users must be greater than or equal to 0.")
            return
        if max_amt == 0:
            max_amt = min_amt
        if max_amt < min_amt:
            await ctx.send("The maximum number of users must be greater than or equal to the minimum number of users.")
            return
        await self.config.guild(ctx.guild).MIN_USERS_TO_PENALIZE.set(min_amt)
        await self.config.guild(ctx.guild).MAX_USERS_TO_PENALIZE.set(max_amt)
        await ctx.send(f"{min_amt} to {max_amt} users will be affected by an invasion.")