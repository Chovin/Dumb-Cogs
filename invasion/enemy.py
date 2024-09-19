import discord
from discord import Member

import random
import json
import asyncio
import math


ARRIVING_STATE = "arriving"
WIN_STATE = "dying"
LOSE_STATE = "attacking"

BOMB_DMG_TYPE = "bomb"


class Enemy():
    def __init__(self, path: str, min_enrage_mult: float, max_enrage_mult: float, enraged: bool=False):
        self.path = path
        with open(f"{path}/stats.json") as f:
            stats = json.load(f)
        self.name = stats['name']
        self.lingers_for = stats['lingers'] 
        self.max_health = stats['health'] 
        self.armor = stats['armor'] 
        self.reward_mult = stats['reward_mult']
        self.arrival_weight = stats['arrival_weight']
        self.states = stats['states']
        self.arrival_countdown = stats['arrival_countdown']
        self._active_states = [k for k, v in self.states.items() if v.get('active')]
        self._hittable_states = [k for k, v in self.states.items() if v.get('hittable')]
        self.animations = {
            anim: discord.File(f"{self.path}/animations/{anim}.gif", filename=f"{anim}.gif") 
            for anim in self.states
        }

        default_states = [k for k,v in self.states.items() if v.get('default')]
        if not default_states:
            default_states = self._active_states
        self.default_state = random.choice(default_states)
        
        self.health = self.max_health
        self.min_enrage_mult = min_enrage_mult
        self.max_enrage_mult = max_enrage_mult
        self.enraged = enraged

        # maybe reduce the number of these so it makes more sense which is stronger
        self._title_prefixes = [
            "Angry",
            "Enraged",
            "Formidable",
            "Rampaging",
            "Ferocious"
            "Epic",
            "Mythic",
            "Ancient",
            "Colossal",
            "Unstoppable",
            "Apocalyptic"
            "Eternal",
            "Divine"
        ]
        if stats.get('enrage_titles_override'):
            self._title_prefixes = stats['enrage_titles_override']

        self.enraged_amt = min_enrage_mult

        if enraged:
            # am I doing my math right here?
            min_enrage_mult-=1
            max_enrage_mult-=1
            enraged_amt = min_enrage_mult + random.random() * (max_enrage_mult-min_enrage_mult)

            self.health *= enraged_amt + 1
            self.max_health = self.health
            self.reward_mult *= enraged_amt * .75 + 1
            self.enraged_amt = enraged_amt + 1

            self.name = f"{self.title_prefix} {self.name}"
            
        self.state = ARRIVING_STATE
        self.hurt_mult = {}
        self.linger = self.lingers_for
        self.attacked_by = {}
        self.bombed_by = {}

    @property
    def msg(self):
        msgs = self.states[self.state]['msg']
        if not msgs:
            return None
        return random.choice(msgs).format(name=self.name)
    
    @property
    def health_percentage(self):
        return self.health / self.max_health
    
    @property
    def linger_percentage(self):
        return self.linger / self.lingers_for
    
    @property
    def hurt_by(self):
        return self.states[self.state].get('hurt_by', [])

    @property
    def added_armor(self):
        return self.states[self.state].get('added_armor', 0)
    
    @property
    def dead(self):
        return self.state == WIN_STATE

    @property
    def arriving(self):
        return self.state == ARRIVING_STATE
    
    @property
    def done(self):
        return self.linger <= 0 or self.dead or self.state == LOSE_STATE

    @property
    def attacking(self):
        return self.states[self.state].get('damage', 0)

    @property
    def animation(self):
        return discord.File(f"{self.path}/animations/{self.state}.gif", filename=f"{self.state}.gif") 
        # return self.animations[self.state]
    
    @property
    def attacked_by_distribution(self):
        sm = sum(self.attacked_by.values())
        return {k: v / sm for k, v in self.attacked_by.items()}

    @property
    def title_prefix(self):
        mn = self.min_enrage_mult
        mx = self.max_enrage_mult
        pn = 0
        px = len(self._title_prefixes) - 1

        return self._title_prefixes[
            # map value from between mn and mx (exclusive) to between pn and px (inclusive)
            math.floor((self.enraged_amt - mn) / (mx - mn) * (px - pn)) + pn
        ]

    def hurt(self, player: Member, dmg_type: str, damage: int):
        if player.bot:
            return
        if self.state not in self._hittable_states:
            return
        is_bomb = dmg_type == BOMB_DMG_TYPE
        pid = player.id
        # dmg as an arg for purchasable bombs
        if (not is_bomb) and dmg_type not in self.hurt_by:
            # miss penalty
            self.hurt_mult[pid] = self.hurt_mult.get(pid, 1) * .9
            return 0
        hurt_mult = 1 if is_bomb else self.hurt_mult.get(pid, 1)
        dmg = damage * hurt_mult * max(1 - (self.armor+self.added_armor), 0)
        self.health -= dmg
        if self.health <= 0:
            self.health = 0
        self.attacked_by[player.id] = self.attacked_by.get(player.id, 0) + min(self.health, dmg)
        if not is_bomb:
            # make future hits weaker
            self.hurt_mult[pid] = self.hurt_mult.get(pid, 1) * .75
        else:
            self.bombed_by[player.id] = self.bombed_by.get(player.id, 0) + 1
        return dmg

    def attack(self):
        self.state = LOSE_STATE
        return self.penalty_mult

    def tick(self):
        if self.health <= 0:
            self.health = 0
            self.state = WIN_STATE
            return
        

        if self.state == ARRIVING_STATE:
            self.state = self.default_state
        else:
            self.state = random.choices(
                self._active_states,
                weights=[self.states[s].get('weight', 1) for s in self._active_states]
            )[0]
        self.hurt_mult = {}
    
    async def update(self):
        self.bombed_by = {}
        if self.state == ARRIVING_STATE:
            await asyncio.sleep(self.arrival_countdown*60)
        else:
            await asyncio.sleep(30)
        self.linger -= .5
        if self.linger <= 0:
            self.linger = 0
            if self.health <= 0:
                self.state = WIN_STATE
            else:
                self.state = LOSE_STATE
            return
        self.tick()


    