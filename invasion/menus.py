import discord

import random
import math
import asyncio

from redbot.core import bank
from redbot.vendored.discord.ext import menus

from .enemy import ARRIVING_STATE, WIN_STATE, LOSE_STATE, BOMB_DMG_TYPE

BOMB_EMOJI = "\N{FIRECRACKER}"


class InvasionMenu(menus.Menu):
    def __init__(self, bot, invader, bomb_cost, bomb_dmg, role = None):
        self.bot = bot
        self.mention_role = role
        self.invader = invader
        self.bomb_cost = bomb_cost
        self.bomb_dmg = bomb_dmg
        self.title_formats = {
            ARRIVING_STATE: random.choice(["A ",""]) + random.choice([
                "{e} is approaching!",
                "{e} is on its way!",
                "{e} is coming!",
                "{e} is coming right now!",
                "{e} is here!",
                "{e} is emerging!"
            ]),
            WIN_STATE: random.choice([
                "{e} has been defeated!",
                "{e} has been vanquished!",
                "You are victorious!",
                "The server will live another day!"
            ]),
            LOSE_STATE: random.choice([
                "The {e} runs rampant!",
                "{e} decimates the server!",
                "You have been defeated!",
                "{e} ravages the server's citizens!"
            ]),
        }
        self.default_title_formats = [
            "{e} is {s}!",
            "Oh, the horror!",
            "Protect the people!",
            "Watch out! {e} is {s}!"
        ]
        super().__init__(timeout=invader.linger*60, check_embeds=True)
    
    @property
    def title(self):
        return self.title_formats.get(
            self.invader.state, random.choice(self.default_title_formats)
        ).format(e=self.invader.name, s=self.invader.state)

    async def send_initial_message(self, ctx, channel):
        m = ""
        if self.mention_role is not None:
            m = " " +self.mention_role.mention
        
        return await channel.send(
            random.choice([
                f"Suit up{m}!",
                f"{m} it's time to do your part!",
                f"Get ready{m}!"
            ]),
            embed=self.get_embed(),
            file=self.invader.animation
        )

    async def start(self, ctx):
        # manually send initial message so we can get around having a menu
        # with no emojis stopping before we can add emojis
        self.message = await self.send_initial_message(ctx, ctx.channel)
        def button_handler(button):
            async def handler(self: InvasionMenu, payload: discord.Reaction):
                dmg_type = payload.emoji.name
                dmg = 1
                player = self.bot.get_guild(payload.guild_id).get_member(payload.user_id)
                if dmg_type == BOMB_EMOJI:
                    dmg_type = BOMB_DMG_TYPE
                    dmg = self.bomb_dmg
                    try:
                        await bank.withdraw_credits(player, self.bomb_cost)
                    except Exception as e:
                        return
                self.invader.hurt(player ,dmg_type, dmg)
            return handler
        # adding bomb here instead of decorator so that it reliably adds it to the end
        for e in [*self.invader.actions, BOMB_EMOJI]:
            # super().start wasn't allowing for menus with no emojis to be started
            # causing add_buttons to throw MenuError("Menu has not been started yet")
            # so manually add_reaction
            b = menus.Button(e, button_handler(e), lock=False)
            await self.message.add_reaction(b.emoji)
            self.add_button(b)
        await super().start(ctx)

    def reaction_check(self, payload):
        """overwriting menus.Menu's reaction_check so that everyone can react
        (and also so it doesn't react to the bot's own reactions with the fake ctx)"""
        
        if payload.message_id != self.message.id:
            return False
        if payload.user_id == self.bot.user.id:
            return False

        return payload.emoji in self.buttons
      
    async def display(self, msg: str='', players_affected: dict={}, bombs_used: dict={}, reward: dict={}, final=False):
        kwargs = {}
        if msg:
            kwargs = {'content': msg}

        await self.message.edit(
            **kwargs,
            attachments=[self.invader.animation],
            embed=self.get_embed(players_affected, reward, bombs_used, final)
        )

    def get_embed(self, players_affected: dict={}, reward: dict={}, bombs_used: dict={}, final=False):
        hp = math.ceil(self.invader.health_percentage * 10)
        linger = math.ceil(self.invader.linger_percentage * 10)
        embed = discord.Embed(
            title=self.title,
            description=self.invader.msg
        )
        guild = self.message and self.message.guild
        if reward:
            embed.add_field(
                name="Rewards", 
                value="\n".join(
                    f"{guild.get_member(pid).mention}: {b}" 
                    for pid, b in reward.items()
                )
            )
        if bombs_used:
            embed.add_field(
                name="Bombs used this turn", 
                value="\n".join(
                    f"{guild.get_member(pid).mention}: {n} costing {self.bomb_cost * n}" 
                    for pid, n in bombs_used.items()
                )
            )
        if players_affected:
            embed.add_field(
                name="Players affected overall" if final else "Players affected" , 
                value="\n".join(
                    f"{guild.get_member(pid).mention}: {b}" 
                    for pid, b in players_affected.items()
                )
            )
        if not self.invader.arriving:
            heart = ':yellow_heart:' if self.invader.enraged else ':heart:'
            embed.add_field(
                name=f"{self.invader.name} HP", 
                value=heart*hp + ":black_heart:"*(10-hp),
                inline=False
            )
        msg = {
            WIN_STATE: "Attack Thwarted!",
            LOSE_STATE: "Server Attacked!",
        }.get(self.invader.state, "Large-Scale Attack Imminent!")
        embed.add_field(
            name=msg,
            value=":red_square:"*(10-linger) + ":white_large_square:"*(linger),
            inline=False
        )
        embed.set_image(url=f"attachment://{self.invader.state}.gif")
        embed.set_footer(text=f"[p]help Invasion")
        return embed
    
