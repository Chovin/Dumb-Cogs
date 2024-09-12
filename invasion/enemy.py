import discord

import random
import json
import asyncio


ARRIVING_STATE = "arriving"
DEAD_STATE = "dying"
ATTACK_STATE = "attacking"


class Enemy():
    def __init__(self, path: str):
        self.path = path
        with open(f"{path}/stats.json") as f:
            stats = json.load(f)
        self.name = stats['name'] 
        self.lingers_for = stats['lingers'] 
        self.max_health = stats['health'] 
        self.armor = stats['armor'] 
        self.reward_mult = stats['reward_mult']
        self.penalty_mult = stats['penalty_mult']
        self.arrival_weight = stats['arrival_weight']
        self.states = stats['states']
        self._active_states = [k for k, v in self.states.items() if v.get('active') == True]
        self.animations = {
            anim: discord.File(f"{self.path}/animations/{anim}.png") 
            for anim in self.states
        }
        self.default_state = [k for k,v in self.states.items() if v.get('default')][0]
        self.init()
    
    def init(self):
        self.health = self.max_health
        self.state = ARRIVING_STATE
        self.hurt_mult = 1
        self.linger = self.lingers_for

    @property
    def msg(self):
        self.states[self.state]
    
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
        return self.state == DEAD_STATE

    def hurt(self, dmg_type: str, damage: int):
        is_bomb = dmg_type == "bomb"
        # dmg as an arg for purchasable bombs
        if (not is_bomb) and dmg_type not in self.hurt_by:
            # miss penalty
            self.hurt_mult *= .95
            return 0
        hurt_mult = 1 if is_bomb else self.hurt_mult
        dmg = damage * hurt_mult * max(1 - (self.armor+self.added_armor), 0)
        self.health -= dmg
        if not is_bomb:
            self.hurt_mult *= .8
        return dmg

    def attack(self):
        self.state = ATTACK_STATE
        return self.penalty_mult

    def tick(self):
        if self.health <= 0:
            self.health = 0
            self.state = DEAD_STATE
            return

        if self.state == ARRIVING_STATE:
            self.state = self.default_state
        else:
            self.state = random.choices(
                self._active_states,
                weights=[self.states[s].get('weight', 1) for s in self._active_states]
            )[0]
        self.hurt_mult = 1
    
    async def do_linger(self):
        await asyncio.sleep(60)
        self.linger -= 1
        if self.linger <= 0:
            self.linger = 0
            if self.health <= 0:
                self.state = DEAD_STATE
            else:
                self.state = ATTACK_STATE
    
    def animation(self):
        return self.animations[self.state]

    