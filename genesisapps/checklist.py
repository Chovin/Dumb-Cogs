import discord
from discord.ui import DynamicItem, Select
from redbot.core.bot import Red
from redbot.core.config import Group

import typing
from typing import Union
from datetime import datetime


class ChecklistItem:
    ROLE = "role"
    TEXT = "text"
    def __init__(self, role_or_text: Union[str, discord.Role], done: bool = False):
        if isinstance(role_or_text, discord.Role):
            self.type = self.ROLE
            self.value = role_or_text.id
            self.role = role_or_text
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
    
    def clean_str(self):
        if self.role:
            return f"@{self.role.name} acquired"
        return self.value

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
        self._initial_update = True
        self.bot = bot
        self.app = app

    async def refresh_items(self, force=False, dispatch=True):
        if force:
            self._update = True
        await self.checklist_items(dispatch)

    async def checklist_items(self, dispatch=True):
        if self._update:
            new_items = [
                ChecklistItem.new(self.guild, **ci) 
                for ci in (await self.config()).values()
            ] 
            self.previous_items = getattr(self, '_checklist_items', new_items)   
            self._checklist_items = new_items
            self._checklist_dict = {
                ci.value: ci for ci in self._checklist_items
            }
            self._update = False
            if self.member and not self._initial_update and dispatch:
                self.bot.dispatch("gapps_checklist_update", self)
        self._initial_update = False
        return self._checklist_items

    @property
    def changed_items(self):
        return [
            cci for pci, cci in zip(self.previous_items, self._checklist_items) 
            if str(pci) != str(cci)
        ]

    async def to_str(self):
        return "\n".join(
            f"{i}. {ci}" 
            for i, ci in enumerate(await self.checklist_items())
        )

    def __repr__(self):
        return f"Checklist({self.member}, {self.guild}, {[ci for ci in self._checklist_items]})"

    async def is_done(self):
        items = await self.checklist_items()
        return all(i.done for i in items)
    
    async def done_items(self):
        items = await self.checklist_items()
        return [i for i in items if i.done]

    async def get_item(self, index: int):
        return (await self.checklist_items())[index]
    
    async def get_item_by_value(self, value: str, dispatch=False):
        await self.checklist_items(dispatch)
        return self._checklist_dict[value]

    async def add_item(self, item: ChecklistItem, defer_post=False):
        self._update = True
        await self.config.set_raw(item.value, value=item.to_dict())
        if not defer_post and self.app:
            await self.app.log.post(str(item), datetime.now())
    
    async def remove_item(self, item: ChecklistItem):
        self._update = True
        await self.config.clear_raw(item.value)
        if self.app:
            await self.app.log.post(str(item), datetime.now())
    
    async def update_item(self, item: ChecklistItem, defer_post=False):
        await self.add_item(item, defer_post)

    async def update_roles(self, member: discord.Member):
        cis = {ci.value: ci for ci in await self.checklist_items() if ci.type == ChecklistItem.ROLE}
        cis = {r.id: cis[r.id] for r in member.roles if r.id in cis}

        cdones = []
        for ci in cis.values():
            if not ci.done:
                ci.done = True
                cdones.append(ci)
                await self.update_item(ci, defer_post=True)
        if cdones:
            if self.app:
                await self.app.log.post([str(ci) for ci in cdones], datetime.now())
            await self.refresh_items()
            if self.app:
                await self.app.display()

        return cdones

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


class ChecklistSelect(DynamicItem[Select], template=r"gapps:ChecklistSelect:(?P<user_id>[0-9]+)"):
    def __init__(self, checklist: Checklist):
        self.checklist = checklist
        self.bot = checklist.bot
        self.user_id = checklist.member.id
        super().__init__(
            Select(
                placeholder="Select an item to toggle",
                options = [
                    discord.SelectOption(
                        label=ci.clean_str(),
                        value=str(ci.value)
                    ) for ci in checklist._checklist_items
                ],
                custom_id=f"gapps:ChecklistSelect:{self.user_id}",
                min_values=0, max_values=len(checklist._checklist_items)
            )
        )

    @classmethod
    async def new(cls, checklist: Checklist):
        await checklist.refresh_items(dispatch=False)
        return cls(checklist)
    
    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: Select, match: typing.Match[str]):
        cog = interaction.client.get_cog("GenesisApps")
        user_id = int(match.group("user_id"))
        member = cog.get_member(interaction.guild, user_id)
        app = cog.application_for(member)
        self = await cls.new(
            Checklist(
                cog.config.member(member).CHECKLIST, 
                cog.bot, interaction.guild, member, app
            ),
        )
        return self

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True 
    
    async def callback(self, interaction: discord.Interaction):
        items = []
        for value in self.item.values:
            try:
                item = await self.checklist.get_item_by_value(int(value))
            except (ValueError, KeyError):
                item = await self.checklist.get_item_by_value(value)
            item.toggle()
            items.append(item)
            await self.checklist.update_item(item, True)

        if self.checklist.app and items:
            await self.checklist.app.log.post([str(ci) for ci in items], datetime.now())
        
        await self.checklist.refresh_items(True)
        nl = '' if len(items) == 1 else '\n-# '
        return await interaction.response.send_message(
            f"{interaction.user.mention} toggled {nl}" +
            "\n-# ".join([str(ci) for ci in items])
        )
        # await self.checklist.refresh_items()
        # self.checklist.bot.dispatch("gapps_checklist_select", self.checklist)
