import discord
from discord.ui import DynamicItem, Select
from redbot.core.bot import Red
from redbot.core.config import Group

import typing
from typing import Union


class ChecklistItem:
    ROLE = "role"
    TEXT = "text"
    def __init__(self, role_or_text: Union[str, discord.Role], done: bool = False):
        if isinstance(role_or_text, discord.Role):
            self.type = self.ROLE
            self.value = role_or_text.id
            self.role = role_or_text
            self.done = done
        else:
            self.type = self.TEXT
            self.value = role_or_text
            self.role = None
            self.done = done

    @classmethod
    def new(cls, guild: discord.Guild, *, type: str, value: Union[str, int], done: bool = False):
        if type == cls.ROLE:
            return cls(discord.utils.get(guild.roles, id=value), done)
        else:
            return cls(value, done)
    
    def __str__(self):
        ds = '✅' if self.done else '⬜'
        try:
            return f"{ds} {self.role.mention} acquired"
        except AttributeError:
            return f"{ds} {self.value}"

    def __repr__(self):
        return f"ChecklistItem({self.type}: {self.value}, done: {self.done})"
    
    def to_dict(self):
        return {
            "type": self.type,
            "value": self.value,
            "done": self.done
        }

    def toggle(self):
        self.done = not self.done


class Checklist:
    def __init__(self, config_group: Group, bot: Red, guild: discord.Guild, member: discord.Member=None, app = None):
        self.member = member
        self.guild = guild
        self.config = config_group
        self._update = True
        self.bot = bot
        self.app = app

    async def refresh_items(self):
        await self.checklist_items()

    async def checklist_items(self):
        if self._update:
            self._checklist_items = [
                ChecklistItem.new(self.guild, **ci) 
                for ci in (await self.config()).values()
            ]
            self._checklist_dict = {
                ci.value: ci for ci in self._checklist_items
            }
            self._update = False
            if self.member:
                self.bot.dispatch("gapps_checklist_update", self)
        return self._checklist_items

    async def to_str(self):
        return "\n".join(
            f"{i}. {ci}" 
            for i, ci in enumerate(await self.checklist_items())
        )

    def __repr__(self):
        return f"Checklist({self.member}, {self.guild}, {[ci for ci in self._checklist_items]})"

    async def get_item(self, index: int):
        return (await self.checklist_items())[index]
    
    async def get_item_by_value(self, value: str):
        await self.checklist_items()
        return (self._checklist_dict)[value]

    async def add_item(self, item: ChecklistItem):
        self._update = True
        await self.config.set_raw(item.value, value=item.to_dict())
    
    async def remove_item(self, item: ChecklistItem):
        self._update = True
        await self.config.clear_raw(item.value)
    
    async def update_item(self, item: ChecklistItem):
        await self.add_item(item)

    async def copy_from_template(self, template: dict):
        await self.config.set(template)
        await self.refresh_items()
    
    @classmethod
    async def new(cls, *args, **kwargs):
        cl = Checklist(*args, **kwargs)
        await cl.refresh_items()
        return cl

    @classmethod
    async def new_from_template(cls, template: dict, *args, **kwargs):
        cl = Checklist(*args, **kwargs)
        await cl.copy_from_template(template)
        return cl

    async def roles(self):
        return [ci.role for ci in await self.checklist_items() if ci.type == ChecklistItem.ROLE]

