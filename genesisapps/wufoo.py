import discord

from typing import List

from pyfoo import PyfooAPI

import tldextract
from datetime import datetime


class FormNotFound(Exception):
    pass


class DiscordNameFieldNotFound(Exception):
    pass


class MemberNotFound(Exception):
    pass


class Wufoo:
    def __init__(self, form_url: str, key: str, discord_name_field: str):
        self.username = tldextract.extract(form_url).subdomain
        self.form_url = form_url
        if not form_url.endswith("/"):
            form_url += "/"
        self.discord_name_field_title = discord_name_field
        self.api = PyfooAPI(self.username, key)
        self.db: WufooDB
    
    async def setup(self, bot, config, guild: discord.Guild):
        forms = await self.api.forms()
        for form in forms:
            if form.get_link_url().replace('http://', 'https://') == self.form_url.replace('http://', 'https://'):
                self.form = form
                break
        if not hasattr(self, "form"):
            raise FormNotFound(f"Could not find form for {self.form_url}")
        await self.set_fields()
        self.db = await WufooDB.new(bot, config, guild)

    async def set_fields(self):
        if hasattr(self, "fields"):
            return self.fields
        flds = await self.form.fields()
        self.fields = {}
        for fld in flds:
            self.fields[fld.ID] = fld.Title
            if fld.Title == self.discord_name_field_title:
                self.discord_name_field = fld.ID
        if not hasattr(self, "discord_name_field"):
            raise DiscordNameFieldNotFound(f"Could not find {self.discord_name_field_title} in {self.form_url}")
    
    async def pull_entries(self):
        try:
            entries = await self.form.get_entries()
        except AssertionError:  # ratelimit
            return
        await self.db.new_entries(*[
            Entry.from_api(self, entry, self.db.guild) for entry in entries
            if entry['CompleteSubmission'] == '1'
        ])


class WufooDB:
    def __init__(self, bot, config, guild):
        self.entries: dict
        self.entry_queue: dict
        self.member_map: dict
        self.config = config
        self.guild = guild
        self.bot = bot

    @classmethod
    async def new(cls, bot, config, guild):
        self = cls(bot, config, guild)
        self.entries = {k: Entry.from_dict(v, guild) for k, v in (await config.WUFOO_ENTRIES()).items()}
        self.entry_queue = await config.WUFOO_ENTRY_QUEUE()
        self.member_map = await config.WUFOO_MEMBER_MAP()
        return self
    
    def get(self, k):
        return self.entries.get(k)
    
    def get_queue_entry(self, queue_key_or_key):
        try:
            return self.entries[queue_key_or_key]
        except KeyError:
            return self.entries[self.entry_queue[queue_key_or_key]]

    async def save_member_map(self):
        await self.config.WUFOO_MEMBER_MAP.set(self.member_map)
    
    async def add_to_member_map(self, k, save=True):
        entry = self.get(k)
        self.member_map.setdefault(str(entry.member_id), []).append({'key': k, 'sent': False})
        if save:
            await self.config.WUFOO_MEMBER_MAP.set(self.member_map)
    
    async def new_entries(self, *entries, place_into_queue=False, replace_existing=False):
        new_mapped = {}
        new_queued = False
        for entry in entries:
            k = entry.key
            if k in self.entries and not replace_existing:
                continue
            self.entries[k] = entry
            if entry.is_linked() and not place_into_queue:
                await self.add_to_member_map(k, save=False)
                new_mapped.setdefault(str(entry.member_id), []).append(self.entries[k])
            else:
                if k in self.entry_queue.values():
                    continue
                ur = entry.username_raw
                i = 2
                while ur in self.entry_queue:
                    ur = f"{entry.username_raw} ({i})"
                    i += 1
                entry.username_raw = ur
                self.entry_queue[ur] = k
                new_queued = True
        
        await self.config.WUFOO_ENTRIES.set({k: v.to_dict() for k, v in self.entries.items()})
        await self.config.WUFOO_ENTRY_QUEUE.set(self.entry_queue)
        await self.config.WUFOO_MEMBER_MAP.set(self.member_map)
        if new_queued:
            self.bot.dispatch("gapps_wufoo_entry_queued", self)
        if new_mapped:
            for entries in new_mapped.values():
                self.bot.dispatch("gapps_wufoo_entry_mapped", entries)
    
    async def remove_entries(self, qks: List[str]):
        for k in qks[:-1]:
            await self.pop_entry(k, save=False)
        await self.pop_entry(qks[-1], save=True)

    async def pop_entry(self, queue_key, save=True):
        entry = self.get_queue_entry(queue_key)
        self.entry_queue.pop(entry.username_raw)
        if save:
            await self.config.WUFOO_ENTRY_QUEUE.set(self.entry_queue)
        return entry

    async def link(self, queue_key, member):
        try:
            entry = await self.pop_entry(queue_key)
        except KeyError:
            entry = self.entries[queue_key]
        entry.set_member(member)
        await self.add_to_member_map(entry.key)
        self.bot.dispatch("gapps_wufoo_entry_mapped", [entry])
    
    async def unlink(self, key, enqueue=False):
        removed = None
        removed_from = []
        for mid, mentries in self.member_map.items():
            for i in range(len(mentries)-1,-1,-1):
                mentry = mentries[i]
                if mentry['key'] == key:
                    mentries.remove(mentry)
                    # still go through the rest to unlink all members
                    removed = mentry
                    member = self.guild.get_member(int(mid))
                    if member:
                        removed_from.append(member)
        if removed or enqueue:
            await self.new_entries(self.entries[key], place_into_queue=True, replace_existing=True)
        return removed_from
    
    async def delete_member_from_member_map(self, member: discord.Member):
        await self.config.WUFOO_MEMBER_MAP.clear_raw(f"{member.id}")
        del self.member_map[f"{member.id}"]



class Entry:
    def __init__(self, entry_dict, guild):
        self.guild = guild
        self._dict = entry_dict
        
    
    @classmethod
    def from_dict(cls, entry_dict, guild):
        return cls(entry_dict, guild)

    @classmethod
    def from_api(cls, api, entry, guild):
        self = cls({}, guild)
        for k, v in entry.items():
            if k.startswith(('Field', 'EntryId')):
                self[api.fields[k]] = v
        self['USERNAME_RAW'] = self[api.discord_name_field_title].strip()
        member = guild.get_member_named(self.username)
        self['DISCORD_MEMBER_ID'] = member.id if member else None
        self['Date Created'] = f"<t:{int(datetime.fromisoformat(entry['DateCreated']).timestamp())}:F>"
        return self
    
    def to_dict(self):
        return self._dict
    
    @property
    def key(self):
        return self['Entry Id']
    
    @property
    def username_raw(self):
        return self['USERNAME_RAW']
    
    @username_raw.setter
    def username_raw(self, value):
        self['USERNAME_RAW'] = value
    
    @property
    def username(self):
        return self.username_raw.split(' ')[0].split('(')[0].split('#')[0]

    @property  
    def member_id(self):
        return self['DISCORD_MEMBER_ID']
    
    @property
    def member(self):
        return self.guild.get_member(self.member_id)
    
    def set_member(self, member):
        self['DISCORD_MEMBER_ID'] = member.id
    
    def is_linked(self):
        return bool(self['DISCORD_MEMBER_ID'])

    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return f"{self.key}. {self.username_raw}"
    
    def __getitem__(self, key):
        return self._dict[key]
    
    def __setitem__(self, key, value):
        self._dict[key] = value

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        return iter(self._dict)
    
    def keys(self):
        return self._dict.keys()
    
    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()
    
    def entry_keys(self):
        return (k for k in self.keys() if k not in ('DISCORD_MEMBER_ID', 'USERNAME_RAW'))

    def entry_values(self):
        return (v for k, v in self.items() if k not in ('DISCORD_MEMBER_ID', 'USERNAME_RAW'))
    
    def entry_items(self):
        return ((k, v) for k, v in self.items() if k not in ('DISCORD_MEMBER_ID', 'USERNAME_RAW'))