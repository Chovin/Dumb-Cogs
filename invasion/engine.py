import discord
from redbot.core import commands, Config, bank
from redbot.core.bot import Red
from redbot.core.data_manager import bundled_data_path

import datetime
import random
import asyncio
import math
from typing import List
from pathlib import Path

from .enemy import Enemy
from .menus import InvasionMenu

LOOP_DONE = "done"

WARNING_GIF_FN = "warning.gif"
WARNING_GIF_PATH = Path("animations") / WARNING_GIF_FN


class InvasionCheckLoop:
    def __init__(self, cog: commands.Cog, guild: discord.Guild, enemy_paths: List[Path]):
        self.config = cog.config
        self.bot = cog.bot
        self.guild = guild
        self.enemy_paths = enemy_paths
        self.enemy_stubs = {p: Enemy(p, 1.5, 3) for p in enemy_paths}
        # self.enemy = enemy
        self.ongoing = False
        self.warning_anim_path = bundled_data_path(cog) / WARNING_GIF_PATH

    async def start(self, now=False):
        try:
            do_continue = True
            while do_continue:
                do_continue = await self.iterate(now)
                now = False
            return LOOP_DONE
        except Exception as e:
            self.ongoing = False
            raise e
    
    async def iterate(self, now=False):
        settings = await self.config.guild(self.guild).all()
        channels = settings['ENABLED_CHANNELS']
        if not channels:
            return False
        
        next_visit = settings['VISIT_ON']
        if next_visit is None:
            next_visit = datetime.datetime.now()
        else:
            next_visit = datetime.datetime.fromtimestamp(next_visit)

        min_freq = settings['MIN_INVASION_FREQUENCY_MINUTES']
        max_freq = settings['MAX_INVASION_FREQUENCY_MINUTES']
        invasion_in_minutes = random.random() * (max_freq - min_freq) + min_freq

        # avoid all guilds having a game running at once if bot starts up after a long time
        # so just skip it if the bot was down while the invasion came
        if next_visit <= datetime.datetime.now():
            next_visit = datetime.datetime.now() + datetime.timedelta(minutes=invasion_in_minutes)
            await self.config.guild(self.guild).VISIT_ON.set(next_visit.timestamp())

        enrage_chance = .1
        if now:
            next_visit = datetime.datetime.now()
            await self.config.guild(self.guild).VISIT_ON.set(next_visit.timestamp())
            enrage_chance = .6

        # handle changing visiting times in cog
        while next_visit > datetime.datetime.now():
            sleep_for_seconds = (next_visit - datetime.datetime.now()).total_seconds()
            await asyncio.sleep(sleep_for_seconds)

        self.ongoing = True
        
        settings = await self.config.guild(self.guild).all()
        channel = self.guild.get_channel(random.choice(settings['ENABLED_CHANNELS']))
        mention_role = self.guild.get_role(settings["MENTION_ROLE"])

        warning_mins = settings['WARNING_MINUTES']
        warned = False
        if warning_mins and not now:
            warned = True
            invasion_at = datetime.datetime.now() + datetime.timedelta(minutes=warning_mins)
            m = ""
            if mention_role:
                m = f"{mention_role.mention} "
            desc = random.choice([
                "Prepare yourselves for a fight.",
                "It's time to protect the server.",
                f"It's time to fight for the safety of {self.guild.name}.",
                ("" if mention_role else "Civilians, ") + 
                "ensure your children are safe and take up your arms. It is time to fight."
            ])
            msg = await channel.send(
                f"{m}monster invasion incoming!",
                embed=discord.Embed(
                    title="WARNING! monster invasion incoming!",
                    description=f"A monster will arrive <t:{int(invasion_at.timestamp())}:R>. {m}{desc}"
                ).set_image(url=f"attachment://{WARNING_GIF_FN}"),
                file=discord.File(self.warning_anim_path)
            )
            await asyncio.sleep(warning_mins*60)
            await msg.delete()
        
        self.game = InvasionGame(
            self.bot,
            channel, 
            Enemy(
                random.choices(
                    self.enemy_paths, 
                    weights=[self.enemy_stubs[e].arrival_weight for e in self.enemy_paths]
                )[0],
                settings["MIN_ENRAGE_MULT"], settings["MAX_ENRAGE_MULT"],
                enraged=random.random() <= enrage_chance
            ),
            settings["MIN_REWARD"], settings["MAX_REWARD"],
            settings["MIN_PENALTY"], settings["MAX_PENALTY"],
            settings["MIN_USERS_TO_PENALIZE"], settings["MAX_USERS_TO_PENALIZE"],
            settings["BOMB_COST"], settings["BOMB_DMG"],
            mention_role if not warned else None, 
            settings["ATTACK_OUTSIDE_ROLE"]
        )
        await self.game.start()
        self.ongoing = False
        return True
    

class MockContext:
    def __init__(self, channel, bot):
        self.guild = channel.guild
        self.channel = channel
        self.bot = bot
        self.author = self.guild.me
        
    
class InvasionGame():
    def __init__(self, bot: Red, channel, enemy: Enemy, 
                 min_reward: int, max_reward: int, 
                 min_penalty: int, max_penalty: int,
                 min_users_penalty: int, max_users_penalty: int,
                 bomb_cost: int, bomb_dmg: int,
                 role: discord.Role, attack_outside_role: bool):
        self.bot = bot
        self.channel = channel
        self.ctx = MockContext(channel, bot)
        self.enemy = enemy
        self.min_reward = min_reward
        self.max_reward = max_reward
        self.min_penalty = min_penalty
        self.max_penalty = max_penalty
        self.min_users_penalty = min_users_penalty
        self.max_users_penalty = max_users_penalty
        self.role = role
        self.bomb_cost = bomb_cost
        self.bomb_dmg = bomb_dmg
        self.menu = InvasionMenu(bot, enemy, bomb_cost, bomb_dmg, role)
        self.damages = []
        self.bomb_frames = []
        self._members_to_hurt = [*filter(
            lambda m: self.channel.permissions_for(m).add_reactions and self.channel.permissions_for(m).read_messages,
            [m for m in (self.ctx.guild.members if attack_outside_role else role.members) if not m.bot]
        )]

    async def start(self):
        await self.menu.start(self.ctx)
        await self.game_loop()

    async def hurt_players(self, dmg_multiplier):
        nplayers = self.min_users_penalty + random.randint(0, self.max_users_penalty - self.min_users_penalty)
        self.damages.append({})

        try:
            players = random.sample(self._members_to_hurt, nplayers)
        except ValueError:
            players = [*self._members_to_hurt]

        for player in players:
            base_dmg = self.min_penalty + random.randint(0, self.max_penalty - self.min_penalty)
            dmg = base_dmg * dmg_multiplier

            balance = await bank.get_balance(player)
            dmg = min(dmg, balance)

            self.damages[-1][player.id] = self.damages[-1].get(player.id, 0) - dmg

            await bank.withdraw_credits(player, dmg)
        return self.damages[-1]


    async def game_loop(self):
        while not self.enemy.done:
            await self.enemy.update()
            dmg = self.enemy.attacking
            players_affected = {}
            if dmg:
                players_affected = await self.hurt_players(dmg)
            bomb_frame = {}
            if self.enemy.bombed_by:
                bomb_frame = {pid: bombs for pid, bombs in self.enemy.bombed_by.items()}
                self.bomb_frames.append(bomb_frame)
            await self.menu.display(players_affected=players_affected, bombs_used=bomb_frame)
        if self.enemy.dead:
            player_dist = self.enemy.attacked_by_distribution
            reward_base = self.min_reward + random.randint(0, self.max_reward - self.min_reward)
            total_reward = len(player_dist) * reward_base * self.enemy.reward_mult
            actual_rewards = {}
            for pid, dist in player_dist.items():
                reward = math.ceil(total_reward * dist)
                try:
                    await bank.deposit_credits(self.ctx.guild.get_member(pid), reward)
                except:
                    # member probably left the server
                    # TODO: log this and actually catch the correct error
                    pass
                else:
                    actual_rewards[pid] = reward
            
            overall_affect = {}

            if self.bomb_frames:
                for frame in self.bomb_frames:
                    for pid, bombs in frame.items():
                        overall_affect[pid] = overall_affect.get(pid, 0) + bombs * -self.bomb_cost

            for frame in [*self.damages, actual_rewards]:
                for pid, dmg in frame.items():
                    overall_affect[pid] = overall_affect.get(pid, 0) + dmg
            
            if overall_affect == actual_rewards:
                overall_affect = {}

            # final display
            await self.menu.display(
                players_affected=overall_affect, 
                reward=actual_rewards, 
                bombs_used=self.enemy.bombed_by,
                final=True
            )
            
        self.menu.stop()