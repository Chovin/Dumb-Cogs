import discord
from discord import Member
import random
import json
import asyncio
import math
import re
import os

ARRIVING_STATE = "arriving"
WIN_STATE = "dying"
def new_func():
    LOSE_STATE = "attacking"
    return LOSE_STATE

LOSE_STATE = new_func()
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
        self._active_states = [k for k, v in self.states.items() if v.get('active')]
        self._hittable_states = [k for k, v in self.states.items() if v.get('hittable')]
        self.actions = []
        for v in self.states.values():
            self.actions += v.get('hurt_by', [])
        self.actions = list({k: True for k in self.actions})
        self.sprites = {
            state: v.get('sprite') 
                if v.get('sprite') else 
                [s for s in os.listdir(f"{self.path}/animations") if re.match(state + r"\.[a-z]+", s)][0] for state, v in self.states.items()
        }

        default_states = [k for k,v in self.states.items() if v.get('default')]
        if not default_states:
            default_states = self._active_states
        self.default_state = random.choice(default_states)
        
        self.health = self.max_health
        self.min_enrage_mult = min_enrage_mult
        self.max_enrage_mult = max_enrage_mult
        self.enraged = enraged

        self._title_prefixes = [
            "Angry", "Enraged", "Formidable", "Rampaging", "Ferocious",
            "Epic", "Mythic", "Ancient", "Colossal", "Unstoppable",
            "Apocalyptic", "Eternal", "Divine"
        ]
        if stats.get('enrage_titles_override'):
            self._title_prefixes = stats['enrage_titles_override']

        self.enraged_amt = min_enrage_mult

        if enraged:
            min_enrage_mult -= 1
            max_enrage_mult -= 1
            enraged_amt = min_enrage_mult + random.random() * (max_enrage_mult - min_enrage_mult)

            self.health *= enraged_amt + 1
            self.max_health = self.health
            self.reward_mult *= enraged_amt * 0.75 + 1
            self.enraged_amt = enraged_amt + 1

            self.name = f"{self.title_prefix} {self.name}"
            
        self.state = ARRIVING_STATE
        self.hurt_mult = {}
        self.linger = self.lingers_for
        self.attacked_by = {}
        self.bombed_by = {}

    @property
    def state_dict(self):
        return self.states[self.state]

    @property
    def msg(self):
        msgs = self.state_dict['msg']
        if not msgs:
            return None
        return random.choice(msgs)
    
    @property
    def title_msg(self):
        tm = self.state_dict.get('title_msg')
        if not tm:
            return None
        return random.choice(tm)
    
    @property
    def health_percentage(self):
        return self.health / self.max_health
    
    @property
    def linger_percentage(self):
        return self.linger / self.lingers_for
    
    @property
    def hurt_by(self):
        return self.state_dict.get('hurt_by', [])

    @property
    def added_armor(self):
        return self.state_dict.get('added_armor', 0)
    
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
        return self.state_dict.get('damage', 0)

    @property
    def animation(self):
        sprite_fn = self.sprites[self.state]
        return discord.File(f"{self.path}/animations/{sprite_fn}", filename=sprite_fn) 
    
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
            math.floor((self.enraged_amt - mn) / (mx - mn) * (px - pn)) + pn
        ]
    
    @property
    def countdown(self):
        cd = self.state_dict.get('countdown', 30)
        try:
            return max(5, cd)
        except:
            return max(5, random.random() * (cd[1] - cd[0]) + cd[0])
        
    def format_msg(self, msg, **kwargs):
        if msg:
            return msg.format(name=self.name, **{k: v.name for k, v in kwargs.items()})
        return None

    def hurt(self, player: Member, dmg_type: str, damage: int):
        if player.bot:
            return
        if self.state not in self._hittable_states:
            return
        is_bomb = dmg_type == BOMB_DMG_TYPE
        pid = player.id
        if (not is_bomb) and dmg_type not in self.hurt_by:
            self.hurt_mult[pid] = self.hurt_mult.get(pid, 1) * 0.9
            return 0
        hurt_mult = 1 if is_bomb else self.hurt_mult.get(pid, 1)
        dmg = damage * hurt_mult * max(1 - (self.armor + self.added_armor), 0)
        self.health -= dmg
        if self.health <= 0:
            self.health = 0
        self.attacked_by[player.id] = self.attacked_by.get(player.id, 0) + min(self.health, dmg)
        if not is_bomb:
            self.hurt_mult[pid] = self.hurt_mult.get(pid, 1) * 0.75
        else:
            self.bombed_by[player.id] = self.bombed_by.get(player.id, 0) + 1
        return dmg

    def tick(self):
        if self.health <= 0:
            self.health = 0
            self.state = WIN_STATE
            return

        # Health-based state transitions
        health_percentage = self.health_percentage
        
        if health_percentage > 0.75:
            self.state = "standing"  # Dragon stands tall
        elif health_percentage > 0.25:
            self.state = "flying"    # Dragon flies above attacks
        else:
            self.state = "attacking"  # Dragon breathes fire on the server

        # Handle the arrival state transition
        if self.state == ARRIVING_STATE:
            self.state = self.default_state
        else:
            choices = {s: self.states[s].get('weight', 1) for s in 
                       self.state_dict.get('next_state', self._active_states)}
            self.state = random.choices(
                [*choices],
                weights=[*choices.values()]
            )[0]

        self.hurt_mult = {}

    async def update(self):
        self.bombed_by = {}
        
        await asyncio.sleep(self.countdown)
        self.linger -= self.countdown / 60
        
        if self.linger <= 0:
            self.linger = 0
            if self.health <= 0:
                self.state = WIN_STATE
            else:
                self.state = LOSE_STATE
            return
            
        # Add logic for handling Dragon's behaviors based on current state
        if self.state == "attacking":
            # Dragon deals damage when in attacking state
            damage = self.attacking
            # You might want to specify how much damage the Dragon does here
            # For example, deal damage to players that are currently engaged
            # Implement damage dealing logic here if necessary

        self.tick()
