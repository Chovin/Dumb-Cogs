import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from redbot.core.data_manager import bundled_data_path

import datetime
import json
import os
import random
import asyncio

from .menus import InvasionMenu
from .engine import InvasionCheckLoop, LOOP_DONE
from .enemy import Enemy
from .log import log


class Invasion(commands.Cog):
    """
    Monsters are invading and they want your currency! Can your server fight them off?

    To allow monsters to enter a channel, have an admin run `[p]invasion channel`.
    Once they do this, monsters will start to appear periodically.

    To fight off monsters, watch carefully at what the monster does and spam the relavent emojis.
    Each of your subsequent attacks is less effective, so make sure each attack counts.
    The more members you have fighting a monster at the same time, the faster it will go down.
    If you find yourself in a pinch, you can use bombs for a currency cost. They always hit and are always full force.

    Rarely, larger versions of monsters will appear that are tougher and reward more currency.

    If you and your team are itching to fight a monster, you can try to `[p]provoke` the gods to instigate a monster invasion.
    Be careful though, angering the gods means they'll more likely send a tougher monster your way.

    Want there to be more monster variants? See [my repo](https://github.com/Chovin/Dumb-Cogs/blob/main/CONTRIBUTING.md) for how you can help add some!
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
            "ATTACK_OUTSIDE_ROLE": True,
            "ENABLED_CHANNELS": [],
            "MIN_INVASION_FREQUENCY_MINUTES": 60*2,
            "MAX_INVASION_FREQUENCY_MINUTES": 60*24*4,
            "MIN_REWARD": 100,
            "MAX_REWARD": 200,
            "MIN_PENALTY": 20,
            "MAX_PENALTY": 150,
            "MIN_USERS_TO_PENALIZE": 1,
            "MAX_USERS_TO_PENALIZE": 4,
            "MIN_ENRAGE_MULT": 1.5,
            "MAX_ENRAGE_MULT": 4,
            "BOMB_COST": 30,
            "BOMB_DMG": 4,
            "PROVOKE_COOLDOWN_MINUTES": 5,
            "WARNING_MINUTES": 5,
            "NEXT_PROVOKE": datetime.datetime.now().timestamp()
        })

        #TODO: put enemy stats and arrival weights into guild config (load initial from stats.json)
        self.enemy_paths = self.load_enemies()
        self.tasks = {}
        self.invasions = {}

    def load_enemies(self) -> None:
        enemies_path = bundled_data_path(self) / "enemies"
        enemy_paths = [enemies_path / p for p in os.listdir(enemies_path)]
        return enemy_paths
        
    async def cog_load(self) -> None:
        await self.bot.wait_until_ready()
        await super().cog_load()
        for guild_id in await self.config.all_guilds():
            self.initiate_invasion(self.bot.get_guild(guild_id))
        return 

    async def cog_unload(self) -> None:
        for guild_id, task in [*self.tasks.items()]:
            guild = self.bot.get_guild(guild_id)
            self._cancel_invasion_check(guild)
        return await super().cog_unload()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.initiate_invasion(guild)
    
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self._cancel_invasion_check(guild)
    
    def initiate_invasion(self, guild: discord.Guild, now=False) -> None:
        """Starts an eventual invasion in the guild if there isn't an enemy attacking already"""
        # enemy = random.choices(enemies, weights=[e.arrival_weight for e in enemies])[0]
        # if invasion battle already happening, don't start a new loop
        if guild.id in self.invasions:
            if self.invasions[guild.id].ongoing:
                return False
        self._cancel_invasion_check(guild)
        def _done_callback(task: asyncio.Task) -> None:
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                log.error("Error in Invasion check loop", exc_info=exc)
            elif task.result() == LOOP_DONE:
                return
            # if error or loop not done, restart loop
            self.initiate_invasion(guild)

        invasion = InvasionCheckLoop(self, guild, self.enemy_paths)
        self.invasions[guild.id] = invasion
        task = self.bot.loop.create_task(invasion.start(now))
        task.add_done_callback(_done_callback)
        self.tasks[guild.id] = task
        return True

    def _cancel_invasion_check(self, guild: discord.Guild) -> None:
        if guild.id in self.tasks:
            self.tasks[guild.id].cancel()
            del self.tasks[guild.id]
        if guild.id in self.invasions:
            del self.invasions[guild.id]
    
    def is_invasion_coming(self, guild: discord.Guild) -> None:
        return guild.id in self.tasks
    
    async def is_defender_or_everyone_is_attacked(ctx):
        everyone_is_attacked = await ctx.cog.config.guild(ctx.guild).ATTACK_OUTSIDE_ROLE()
        if everyone_is_attacked:
            return True
        defender_role = ctx.guild.get_role(await ctx.cog.config.guild(ctx.guild).MENTION_ROLE())
        return defender_role in ctx.author.roles

    @commands.check(is_defender_or_everyone_is_attacked)
    @commands.command()
    async def provoke(self, ctx: commands.Context) -> None:
        """Stoke the wrath of the gods and instigate an invasion
        
        Be careful, annoy the gods and they may send larger monsters your way"""
        
        invasion = self.invasions.get(ctx.guild.id)
        if invasion:
            if self.invasions[ctx.guild.id].ongoing:
                invasion = self.invasions[ctx.guild.id]
                await ctx.send(f"An invasion is already in progress in {invasion.game.channel.mention}")
                return
        else:
            await ctx.send(f"{ctx.author.mention} stokes the wrath of the gods. Luckily the defenses in this channel are air-tight. No monster is able to break through")
            return
    
        next_provoke = datetime.datetime.fromtimestamp(await self.config.guild(ctx.guild).NEXT_PROVOKE())
        if datetime.datetime.now() < next_provoke:
            await ctx.send(f"Your voice doesn't reach the gods. Try again <t:{int(next_provoke.timestamp())}:R>")
            return
        
        cooldown = await self.config.guild(ctx.guild).PROVOKE_COOLDOWN_MINUTES()
        if cooldown == -1:
            await ctx.send(f"{ctx.author.mention} tries to provoke the gods, but the server admins stop it from happening; probably for the better.")
            return
        await self.config.guild(ctx.guild).NEXT_PROVOKE.set(datetime.datetime.now().timestamp() + cooldown * 60)
        await ctx.send(f"{ctx.author.mention} stokes the wrath of the gods. A monster is in-bound!")
        self.initiate_invasion(ctx.guild, now=True)

    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    async def invasion(self, ctx: commands.Context) -> None:
        """Invasion preparation commands"""
        if ctx.invoked_subcommand is None:
            settings = await self.config.guild(ctx.guild).all()
            channels = [
                ctx.guild.get_channel(cid) for cid in 
                (settings['ENABLED_CHANNELS'] or [])
            ]
            role = ctx.guild.get_role(settings['MENTION_ROLE'])
            min_freq = settings['MIN_INVASION_FREQUENCY_MINUTES']
            max_freq = settings['MAX_INVASION_FREQUENCY_MINUTES']
            min_hours = min_freq / 60
            max_hours = max_freq / 60
            min_reward = settings['MIN_REWARD']
            max_reward = settings['MAX_REWARD']
            min_penalty = settings['MIN_PENALTY']
            max_penalty = settings['MAX_PENALTY']
            min_users = settings['MIN_USERS_TO_PENALIZE']
            max_users = settings['MAX_USERS_TO_PENALIZE']
            min_enrage = settings['MIN_ENRAGE_MULT']
            max_enrage = settings['MAX_ENRAGE_MULT']
            bomb_cost = settings['BOMB_COST']
            bomb_dmg = settings['BOMB_DMG']
            provoke_cooldown = settings['PROVOKE_COOLDOWN_MINUTES']
            warning_time = settings['WARNING_MINUTES']
            warning_setting = f"**Warning time**: {warning_time} minutes"
            if warning_time == 0:
                warning_setting = "**Warning time**: no warning"

            embed = discord.Embed(
                title="Invasion Settings",
                description=(
                    f"**Vulnerable channels**: {', '.join([c.mention for c in channels])}\n"
                    f"**Defender role**: {role and role.mention}\n"
                    f"**Invasion frequency**: " + (
                        f"{min_hours:.2f} to {max_hours:.2f} hours" if min_hours > 1 else 
                        f"{min_freq} to {max_freq} minutes") + "\n"
                    f"**Reward**: {min_reward} to {max_reward}\n"
                    f"**Penalty**: {min_penalty} to {max_penalty}\n"
                    f"**Users to penalize**: {min_users} to {max_users}\n"
                    f"**Enrage multiplier**: {min_enrage} to {max_enrage}\n"
                    f"**Bomb cost**: {bomb_cost}\n"
                    f"**Bomb damage multiplier**: {bomb_dmg}x\n"
                    f"**Provoke cooldown**: {provoke_cooldown} minutes\n" +
                    warning_setting
                ),
                colour=discord.Colour.blue()
            )
            await ctx.send(embed=embed)
    
    @invasion.command()
    async def defender(self, ctx: commands.Context, role: discord.Role = None) -> None:
        """Set which role is the Defender role. This role will be mentioned when a monster is attacking"""

        await self.config.guild(ctx.guild).MENTION_ROLE.set(role and role.id)
        if role is not None:
            await ctx.send(f"The {role.name} role will now be mentioned when a monster attacks.")
        else:
            await ctx.send(f"Nobody will be mentioned when a monster attacks.")
    
    @invasion.command()
    async def protect(self, ctx: commands.Context, protect_everyone: bool = None) -> None:
        """Toggles protection for the rest of the server members besides the defending role.
        
        For example if protect is on and a monster is failed to be slain, only the members 
        of the defending role will be penalized."""
        if protect_everyone is None:
            protect_everyone = await self.config.guild(ctx.guild).ATTACK_OUTSIDE_ROLE()
        await self.config.guild(ctx.guild).ATTACK_OUTSIDE_ROLE.set(not protect_everyone)
        if protect_everyone:
            await ctx.send("Protection is on. Only the members of the defending role will be penalized.")
        else:
            await ctx.send("Protection is off. Everyone will be penalized.")


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

        if len(enabled_channels) >= 1:
            if not self.is_invasion_coming(guild):
                self.initiate_invasion(guild)
        else:
            if self.is_invasion_coming(guild):
                self._cancel_invasion_check(guild)

        await ctx.send(f"You strategicly put a hole in the defenses of {channel.mention}. Monsters will now attack this channel.")

    @invasion.command()
    async def frequency(self, ctx: commands.Context, min_hours: float, max_hours: float = 0) -> None:
        """Set the frequency of invasions in hours"""

        min_mins = int(min_hours * 60)
        max_mins = int(max_hours * 60)
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
        next_visit = await self.config.guild(ctx.guild).VISIT_ON()
        if self.is_invasion_coming(ctx.guild):
            # if next visit is after the newly set max time, reinitiate
            if next_visit is None or datetime.datetime.fromtimestamp(next_visit) > datetime.datetime.now() + datetime.timedelta(minutes=max_mins):
                self.initiate_invasion(ctx.guild)

        await ctx.send(f"Monsters will now attack every {min_mins / 60:.2f} to {max_mins / 60:.2f} hours.")

    @invasion.command()
    async def reward(self, ctx: commands.Context, min_amt: int, max_amt: int = 0) -> None:
        """Set the amount of currency you get for fighting off a monster

        Reward is multiplied by the number of participating members 
        then dealt out depending on their participation
        
        Note: boss monsters may have a multiplier applied to the reward
        """

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
        """Set the amount of currency you lose for failing to fight off an monster
        
        Note: boss monsters may have a multiplier applied to the penalty"""

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
    async def affected(self, ctx: commands.Context, min_amt: int, max_amt: int = 0) -> None:
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

    @invasion.command()
    async def enrage(self, ctx: commands.Context, min_mult: float=1.5, max_mult: float=None) -> None:
        """Sets the multiplier put on enraged enemy health and rewards.
        
        Every so often monsters will arrive enraged having more health as well as more rewards
        Provoking the gods will also increase the odds of an enraged enemy attacking
        """

        min_mult_range = 1

        if min_mult <= 1.5:
            await ctx.send("The minimum multiplier must be greater than 1.5")
            return

        if max_mult is None:
            max_mult = min_mult + min_mult_range
        
        if max_mult < min_mult + min_mult_range:
            await ctx.send(f"The maximum multiplier must be greater than or equal to the minimum multiplier + {min_mult_range}.")
        
        await self.config.guild(ctx.guild).MIN_ENRAGE_MULT.set(min_mult)
        await self.config.guild(ctx.guild).MAX_ENRAGE_MULT.set(max_mult)
        await ctx.send(f"Enraged monsters will now be between {min_mult} and {max_mult} times tougher")

    @invasion.command()
    async def bombcost(self, ctx: commands.Context, cost: int=30) -> None:
        """Set the cost of using a bomb.
        
        Bombs can be used to attack monsters despite their specific resistances (besides armor)
        Bombs also ignore first-come first-served damage weakening
        """

        if cost < 0:
            await ctx.send("The cost must be greater than or equal to 0.")
            return
        await self.config.guild(ctx.guild).BOMB_COST.set(cost)
        await ctx.send(f"Bombs will now cost {cost} currency to use.")
    
    @invasion.command()
    async def bombdmg(self, ctx: commands.Context, dmg: int=4) -> None:
        """Set the damage multiplier bombs have.
        
        Bombs can be used to attack monsters despite their specific resistances (besides armor)
        Bombs also ignore first-come first-served damage weakening
        """

        if dmg <= 0:
            await ctx.send("The damage multiplier must be greater than or equal to 1.")
            return
        await self.config.guild(ctx.guild).BOMB_DMG.set(dmg)
        await ctx.send(f"Bombs will now deal {dmg}x damage.")

    @invasion.command(name="provoke")
    async def _provoke(self, ctx: commands.Context, cooldown: int) -> None:
        """Set the cooldown for using the provoke command in minutes.
        
        Set to -1 to disable provoking"""

        if cooldown < 0 and cooldown != -1:
            await ctx.send("The cooldown must be greater than or equal to 0 (or -1 to disable provoking)")
            return
        await self.config.guild(ctx.guild).PROVOKE_COOLDOWN_MINUTES.set(cooldown)
        next_provoke = await self.config.guild(ctx.guild).NEXT_PROVOKE()
        new_next = (datetime.datetime.now() + datetime.timedelta(minutes=cooldown)).timestamp()
        if new_next < next_provoke:
            await self.config.guild(ctx.guild).NEXT_PROVOKE.set(new_next)
        if cooldown == -1:
            await ctx.send(f"Provoking is now disabled")
        else:
            await ctx.send(f"The provoke command will now be usable every {cooldown} minutes.")

    @invasion.command()
    async def warning(self, ctx: commands.Context, minutes: int) -> None:
        """Before an invasion starts, a warning will be sent. This sets how long before the invasion starts that the warning is sent.
        Set to 0 to disable warnings.
        """
        if minutes < 0:
            await ctx.send("The warning time must be greater than or equal to 0.")
            return
        
        await self.config.guild(ctx.guild).WARNING_MINUTES.set(minutes)
        if minutes:
            await ctx.send(f"A warning will now be sent {minutes} minutes before an invasion starts.")
        else:
            await ctx.send("No warning will be sent before an invasion starts.")
        