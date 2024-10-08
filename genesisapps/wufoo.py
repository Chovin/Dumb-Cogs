from pyfoo import PyfooAPI
import tldextract


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
    
    async def setup(self):
        forms = await self.api.forms()
        for form in forms:
            if form.get_link_url() == self.form_url:
                self.form = form
                break
        if not hasattr(self, "form"):
            raise FormNotFound(f"Could not find form for {self.form_url}")
        await self.set_fields()

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
    
    async def get_entries(self):
        await [Entry(self, entry) for entry in await self.form.get_entries()]


class Entry:
    def __init__(self, form, entry):
        self.form = form
        self._dict = {}
        for k, v in entry.items():
            self._dict[k] = {"question": form.fields[k], "answer": v}
    
    def member(self, guild):
        username = self[self.form.discord_name_field]['answer'].split(' ')[0].split('(')[0].split('#')[0]
        member = guild.get_member_named(username)
        if member is None:
            raise MemberNotFound(f"Could not find {username} in {guild.name}")
        return member
    
    def __getitem__(self, key):
        return self._dict[key]

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