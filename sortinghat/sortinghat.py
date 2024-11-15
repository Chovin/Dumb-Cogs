import discord
from discord.ext.commands.errors import MissingRequiredArgument
from discord.ui import DynamicItem, Button, View
from discord.ext import tasks

from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import pagify


from typing import List
import random
import asyncio
import os


class SchoolListView(discord.ui.View):
    def __init__(self, timeout=None):
        super().__init__(timeout=timeout)

    async def on_timeout(self) -> None:
        await self.message.edit(view=None)
        await self.unlink_data()

    async def unlink_data(self):
        await self.cog.config.custom("Message", str(self.message.id)).clear()
    
    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="✖️", custom_id="close_page")
    async def close_page(self, interaction: discord.Interaction, button: Button):
        cog = interaction.client.get_cog("SortingHat")
        uid = await cog.config.custom("Message", str(interaction.message.id)).USERID()
        if interaction.user.id == uid or interaction.permissions.manage_messages:
            await interaction.message.delete()
            await self.unlink_data()
        else:
            await interaction.response.send_message(
                embed=discord.Embed(
                    color=discord.Color.red(), 
                    description="You must be the message author to delete this message"
                ),
                ephemeral=True
            )

    @discord.ui.button(style=discord.ButtonStyle.grey, emoji="🔮", custom_id="sort")
    async def sort_user(self, interaction: discord.Interaction, button: Button):
        cog = interaction.client.get_cog("SortingHat")
        try:
            school = await cog.sort_member(interaction.user)
        except AlreadySortedError:
            await interaction.response.send_message(f"You're already part of a nation", ephemeral=True)
            return
        
        await asyncio.sleep(1)
        await school.joined_msg_edit(response=interaction.response)
    
    @discord.ui.button(style=discord.ButtonStyle.blurple, emoji="◀", custom_id="left_page")
    async def left_page(self, interaction: discord.Interaction, button: Button):
        cog = interaction.client.get_cog("SortingHat")
        disp = await SchoolDisplay.new(cog, interaction.guild, interaction.message)
        await disp.display(new_page=await disp.page() - 1, response=interaction.response)

    @discord.ui.button(style=discord.ButtonStyle.blurple, emoji="▶", custom_id="right_page")
    async def right_page(self, interaction: discord.Interaction, button: Button):
        cog = interaction.client.get_cog("SortingHat")
        disp = await SchoolDisplay.new(cog, interaction.guild, interaction.message)
        await disp.display(new_page=await disp.page() + 1, response=interaction.response)

        


# class ChecklistSelect(DynamicItem[Button], template=r"gapps:SortingHatBtn:(?P<message_id>[0-9]+):(?P<action>close|sort|left|right)"):
#     def __init__(self, checklist: Checklist):
#         self.checklist = checklist
#         self.bot = checklist.bot
#         self.user_id = checklist.member.id
#         super().__init__(
#             Select(
#                 placeholder="Select an item to toggle",
#                 options = [
#                     discord.SelectOption(
#                         label=ci.clean_str(),
#                         value=str(ci.value)
#                     ) for ci in checklist._checklist_items
#                 ],
#                 custom_id=f"gapps:ChecklistSelect:{self.user_id}",
#                 min_values=0, max_values=len(checklist._checklist_items)
#             )
#         )

#     @classmethod
#     async def new(cls, checklist: Checklist):
#         await checklist.refresh_items(dispatch=False)
#         return cls(checklist)
    
#     @classmethod
#     async def from_custom_id(cls, interaction: discord.Interaction, item: Select, match: typing.Match[str]):
#         cog = interaction.client.get_cog("GenesisApps")
#         user_id = int(match.group("user_id"))
#         member = cog.get_member(interaction.guild, user_id)
#         app = cog.application_for(member)
#         self = await cls.new(
#             Checklist(
#                 cog.config.member(member).CHECKLIST, 
#                 cog.bot, interaction.guild, member, app
#             ),
#         )
#         return self

#     async def interaction_check(self, interaction: discord.Interaction) -> bool:
#         return True 
    
#     async def callback(self, interaction: discord.Interaction):
#         items = []
#         for value in self.item.values:
#             try:
#                 item = await self.checklist.get_item_by_value(int(value))
#             except (ValueError, KeyError):
#                 item = await self.checklist.get_item_by_value(value)
#             item.toggle()
#             items.append(item)
#             await self.checklist.update_item(item, True)

#         if self.checklist.app and items:
#             await self.checklist.app.log.post([str(ci) for ci in items], datetime.now())
        
#         await self.checklist.refresh_items(True)
#         nl = '' if len(items) == 1 else '\n-# '
#         return await interaction.response.send_message(
#             f"{interaction.user.mention} toggled {nl}" +
#             "\n-# ".join([str(ci) for ci in items])
#         )
#         # await self.checklist.refresh_items()
#         # self.checklist.bot.dispatch("gapps_checklist_select", self.checklist)


class School():
    def __init__(self, cog, guild, name: str) -> None:
        self.cog = cog
        self.name = name
        self.guild = guild
        self.members = []
        self.role: discord.Role
        self.role_config = cog.config.guild(guild).ROLES
        self.rset = None
    
    @classmethod
    async def new(cls, cog, guild, name: str, role: discord.Role=None):
        """Add a role to create a new School or change its name"""
        self = cls(cog, guild, name)
        roles_settings = await self.role_config()
        for rs in roles_settings.values():
            if rs['NAME'] == name:
                self.rset = rs
                break
            if role and rs['ROLEID'] == role.id:
                self.rset = rs
                break
        drole = role or self.role
        default_rset = {
            "NAME": name,
            "ROLEID": drole.id,
            "MEMBERS": [m.id for m in drole.members],
            "ORDER": len(roles_settings),
            "IMAGE_PATH": None,
            "EMOJI": None,
            "DESCRIPTION": None
        }
        if not self.rset:
            if not role:
                raise KeyError(f"The nation {name} is not Registered")
            else:
                self.rset = default_rset
                await self.save()
        else:
            if set(self.rset.keys()) != set(default_rset.keys()):
                self.rset = {**default_rset, **self.rset}
                await self.save()
            if role:
                for rset in roles_settings.values():
                    if rset != self.rset and rset["NAME"] == name:
                        raise ValueError(f"A nation with the name {name} already exists")
                self.rset['NAME'] = name
                await self.save()

        
        # keep members up to date
        await self.update_members()

        return self
    
    @property
    def role_key(self):
        return str(self.role.id)
    
    @property
    def role(self):
        return self.guild.get_role(self.rset["ROLEID"])
    
    @property
    def member_ids(self):
        return [m.id for m in self.role.members]
    
    @property
    def image_path(self):
        return self.rset["IMAGE_PATH"]
    
    @property
    def image_name(self):
        ext = self.image_path.rsplit('.')[-1]
        return f"{self.role.id}.{ext}"
    
    async def pagified_members(self):
        await self.update_members()
        pages = [*pagify("\n".join(f"-# {m.mention}" for m in self.role.members), ["\n"], page_length=500)]
        if not pages:
            pages = ['No Members']
        return pages

    async def needs_update(self):
        return not self.members_match()

    async def members_match(self):
        roles_settings = await self.cog.config.guild(self.guild).ROLES()
        return [m.id for m in self.role.members] == roles_settings[str(self.role.id)]["MEMBERS"]
    
    async def update_members(self):
        if self.member_ids != self.rset["MEMBERS"]:
            self.rset["MEMBERS"] = self.member_ids
            await self.save()

    async def add_member(self, member):
        await member.add_roles(self.role, reason="SortingHat-assigned")
        await self.update_members()

    async def remove_member(self, member):
        # shouldn't be used
        await member.remove_roles(self.role, reason="SortingHat-removed")
        await self.update_members()

    async def delete(self):
        role_settings = await self.role_config()
        del role_settings[self.role_key]
        i = 0
        for rs in sorted([rs for rs in role_settings.values()], key=lambda rs: rs["ORDER"]):
            rs["ORDER"] = i
            i += 1
        await self.role_config.set(role_settings)
    
    async def save(self):
        await self.role_config.set_raw(self.role_key, value=self.rset)
    
    async def swap_order(self, other):
        self.rset["ORDER"], other.rset["ORDER"] = other.rset["ORDER"], self.rset["ORDER"]
        await self.save()
        await other.save()

    async def set_image_path(self, path):
        self.rset["IMAGE_PATH"] = path
        await self.save()

    async def joined_msg_edit(self, *, member=None, message=None, response=None):
        d = f"{member.mention} is" if member else "You're"
        e = discord.Embed(
            description=f"{d} in the **{self.name}** ({self.role.mention})!!",
            color=self.role.color
        )
        extra = {}
        if self.image_path:
            file = discord.File(self.image_path, filename=self.image_name)
            e.set_thumbnail(url=f"attachment://{self.image_name}")
            extra = {"file": file}
            if message:
                extra = {"attachments": [file]}

        if message:
            action = message.edit
        else:
            action = response.send_message
            extra["ephemeral"] = True

        await action(content="", embed=e, **extra)

        


class SchoolDisplay():
    def __init__(self, cog, guild, message_or_channel_id):
        self.cog = cog
        self.guild = guild
        self.role_config = cog.config.guild(guild).ROLES
        self.message = None
        self.channel = None
        self.msg_config = None
        self.schools: List[School] = []
        if isinstance(message_or_channel_id, discord.Message):
            self.message = message_or_channel_id
            self.channel = self.message.channel
            self.msg_config = self.cog.config.custom("Message", str(self.message.id))
        else:
            self.channel = guild.get_channel(message_or_channel_id)
            if self.channel is None:
                raise ValueError("Channel not found")
        self.pagekey = None
        self.extra = {}
    
    @classmethod
    async def new(cls, cog, guild, message_or_channel_id, schools=None):
        self = cls(cog, guild, message_or_channel_id)
        if schools is None:
            role_settings = await self.role_config()
            if self.message:
                schools = [
                    await School.new(cog, guild, role_settings[str(roleid)]["NAME"]) 
                    for roleid in await self.msg_config.SCHOOL_ROLE_IDS()
                ]
                self.extra['timeout'] = await self.msg_config.TIMEOUT()
            else:
                schools = [await School.new(cog, guild, rs['NAME']) for rs in role_settings.values()]
        if self.message:
            self.pagekey = await self.msg_config.PAGESTR()
        self.schools = schools
        return self

    async def set_message(self, message, sent_by_user, timeout):
        if self.message is not None:
            raise Exception("Message is already set")
        self.msg_config = self.cog.config.custom("Message", str(message.id))
        await self.msg_config.USERID.set(sent_by_user.id)
        await self.msg_config.CHANNELID.set(message.channel.id)
        await self.msg_config.GUILDID.set(message.guild.id)
        await self.msg_config.SCHOOL_ROLE_IDS.set([s.role.id for s in self.schools])
        await self.msg_config.TIMEOUT.set(timeout)

    async def page(self):
        return await self.msg_config.PAGE()

    async def change_page(self, page, display=False):
        if self.message is None:
            raise AttributeError("No message has been sent yet")
        await self.msg_config.PAGE.set(page)
        if display:
            await self.display()

    async def schools_in_order(self) -> List[School]:
        rsets = await self.role_config()
        return sorted(self.schools, key=lambda s: rsets[str(s.role.id)]['ORDER'])

    async def display(self, new_page=None, sent_by=None, response=None, timeout=180):
        pages = []
        for school in await self.schools_in_order():
            pages += [(school, page) for page in await school.pagified_members()]

        pagen = 0
        if self.message:
            if new_page is not None:
                pagen = new_page
            else:
                pagen = await self.page()
            # pagen = await self.page() if new_page is None else new_page
            if pagen > len(pages) - 1:
                pagen = 0
                await self.change_page(pagen)
            elif pagen < 0:
                pagen = len(pages)-1
                await self.change_page(pagen)
            if new_page is not None:
                await self.change_page(pagen)

        school, page = pages[pagen]

        e = discord.Embed(
            title=school.name,
            color=school.role.color, description="__Members__\n\n" + page.strip()
        )
        extra = {}
        if school.image_path:
            file = discord.File(school.image_path, filename=school.image_name)
            e.set_thumbnail(url=f"attachment://{school.image_name}")
            extra = {"file": file}
            if self.message:
                extra = {"attachments": [file]}
        e.set_footer(text=f"Page: {pagen+1}/{len(pages)}")

        if self.message:
            if response:
                await response.edit_message(embed=e, **extra)
            elif f"{pagen}{page}" == self.pagekey:  # we're editing but no need to edit
                return
            else:
                await self.message.edit(embed=e, **extra)
        else:
            view = SchoolListView(**{"timeout": timeout, **self.extra})
            
            view.message = await self.channel.send(embed=e, view=view, **extra)
            view.cog = self.cog
        if not self.message:
            await self.set_message(view.message, sent_by, timeout)
        await self.msg_config.PAGESTR.set(f"{pagen}{page}")


class SchoolConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        role_settings = await ctx.cog.config.guild(ctx.guild).ROLES()
        rset = None
        try:
            role = await commands.RoleConverter().convert(ctx, argument)
            rset = role_settings[str(role.id)]
        except:
            for rs in role_settings.values():
                if rs['NAME'] == argument:
                    rset = rs
                    break
        if not rset:
            raise commands.BadArgument(f"Can't find school named or linked to {argument}")
        
        return await School.new(ctx.cog, ctx.guild, rset["NAME"])
            

class AlreadySortedError(Exception):
    pass


class SortingHat(commands.Cog):
    """Lets members sort themselves into different optionally balanced roles"""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )
        self.config.register_guild(
            ROLES = {},
            MAX_MEMBER_DIFF = 2
        )
        self.config.register_member(
            FORCE_CHOICE = []
        )
        self.config.init_custom("Message", 1)
        self.config.register_custom("Message", 
            PAGE=0,
            USERID=None,
            SCHOOL_ROLE_IDS=None,
            GUILDID=None,
            CHANNELID=None,
            PAGESTR=None,
            TIMEOUT=True,
        )

        self.messages = {}
        self.update = False

        self.update_displays.start()
        self.update_occasionally.start()

        self.bot.add_view(SchoolListView())

    async def cog_unload(self):
        self.update_displays.cancel()
        self.update_occasionally.cancel()

    async def all_schools(self, guild):
        role_settings = await self.config.guild(guild).ROLES()
        return [await School.new(self, guild, rs['NAME']) for rs in role_settings.values()]
    
    async def sort_member(self, member):
        all_schools = await self.all_schools(member.guild)
        for s in all_schools:
            if member.get_role(s.role.id):
                raise AlreadySortedError(f"{member.name} already has the {s.role.name} role")

        guild_conf = self.config.guild(member.guild)
        role_settings = await guild_conf.ROLES()
        choices = [
            await School.new(self, member.guild, role_settings[str(rid)]["NAME"]) 
            for rid in await self.config.member(member).FORCE_CHOICE()
        ]
        if not choices:
            choices = all_schools

        amt = await guild_conf.MAX_MEMBER_DIFF()
        max_members = max([len(s.role.members) for s in choices])
        min_members = min([len(s.role.members) for s in choices])
        choices = [s for s in choices if len(s.role.members) - min_members < amt]

        weights = [max_members-len(s.role.members) + 1 for s in choices]

        school = random.choices(choices, weights=weights, k=1)[0]
        await school.add_member(member)
        self.update = True
        return school

    async def school_by_role(self, role):
        role_settings = await self.config.guild(role.guild).ROLES()
        return await School.new(self, role.guild, role_settings[str(role.id)]["NAME"])
    
    async def update_all_displays(self):
        msgsets = await self.config.custom("Message").all()
        for midstr, mset in msgsets.items():
            mid = int(midstr)
            if mid in self.messages:
                msg = self.messages[mid]
            else:
                guild = self.bot.get_guild(mset["GUILDID"])
                channel = guild.get_channel(mset["CHANNELID"])
                msg = await channel.fetch_message(mid)
            sd = await SchoolDisplay.new(self, msg.guild, msg)
            await sd.display()

    @tasks.loop(seconds=10)
    async def update_displays(self):
        if self.update:
            await self.update_all_displays()
            self.update = False

    @tasks.loop(hours=1)
    async def update_occasionally(self):
        self.update = True

    @update_displays.before_loop
    async def wait_for_red(self):
        await self.bot.wait_until_red_ready()

    @commands.command()
    async def sortme(self, ctx: commands.Context):
        """Sorts yourself into one of the server's nations"""
        try:
            school = await self.sort_member(ctx.author)
        except AlreadySortedError:
            await ctx.send(f"You're already part of a nation")
            return
        
        msg = await ctx.reply("Drumroll...")
        await asyncio.sleep(5)
        await school.joined_msg_edit(member=ctx.author, message=msg)

    @commands.command()
    @checks.mod_or_permissions(manage_messages=True)
    async def nationannounce(self, ctx: commands.Context, *, school: SchoolConverter=None):
        """List the nations in a persistent menu"""

        if school:
            schools = [school]
        else:
            schools = await self.all_schools(ctx.guild)

        disp = await SchoolDisplay.new(self, ctx.guild, ctx.channel.id, schools)
        await disp.display(sent_by=ctx.author, timeout=None)

    @commands.command(aliases=["school", "schools", "nation"])
    async def nations(self, ctx: commands.Context, *, school: SchoolConverter=None):
        """List the nations and people in them"""
        
        if school:
            schools = [school]
        else:
            schools = await self.all_schools(ctx.guild)

        disp = await SchoolDisplay.new(self, ctx.guild, ctx.channel.id, schools)
        await disp.display(sent_by=ctx.author)

    @commands.command()
    @checks.mod_or_permissions(manage_messages=True)
    async def nationchoose(self, ctx: commands.Context, *schools: SchoolConverter):
        """Chooses a random person from all (or the selected) schools"""
        if not schools:
            schools = await self.all_schools(ctx.guild)
        
        members = []
        for school in schools:
            members += school.role.members

        if not members:
            await ctx.send("There are no members of any nations at this point")
            return
        
        msg = await ctx.send("Drumroll...")
        await asyncio.sleep(5)
        m = random.choice(members)
        await msg.edit(content=f"The chosen member is {m.mention}!!")

    @commands.group()
    @checks.admin_or_permissions(manage_roles=True)
    async def nationset(self, ctx: commands.Context):
        """Setup commands for nations"""
        pass

    @nationset.command(name="difference")
    async def nationset_difference(self, ctx: commands.Context, amount: int):
        """Set the maximum amount of difference in number of users that the nations can have"""
        if amount < 1:
            await ctx.send("Amount must be more than 0")
            return
        
        await self.config.guild(ctx.guild).MAX_MEMBER_DIFF.set(amount)
        await ctx.send("Now when sorting new members, they won't be placed in nations "
                       f"where the number of members exceed more than {amount} that of the other nations")
    
    @nationset.command(name="force")
    async def nationset_force(self, ctx: commands.Context, member: discord.Member, *schools: SchoolConverter):
        rids = [s.role.id for s in schools]
        await self.config.member(member).FORCE_CHOICE.set(rids)
        if rids:
            await ctx.send(f"When {member.mention} sorts themselves into a nation, their nation will be picked from {', '.join([s.role.mention for s in schools])}")
        else:
            await ctx.send(f"When {member.mention} sorts themselves into a nation, their nation will be picked from all nations")

    @nationset.command(name="nation", aliases=["school"])
    async def nationset_nation(self, ctx: commands.Context, role: discord.Role, *, name: str=None):
        """Setup a nation. Once linked to a role, when people use [p]sort, they will be randomly placed in on of the nations setup
        
        If the name is lef tblank, the nation is removed"""
        school = await School.new(self, ctx.guild, name, role)
        if name is None:
            await school.delete()
            await ctx.send(f"The nation tied to the role **{role.name}** was removed")
            return
        
        disp = await SchoolDisplay.new(self, ctx.guild, ctx.channel.id, [school])
        await disp.display(sent_by=ctx.author)

    @nationset.command(name="image")
    async def nationset_image(self, ctx: commands.Context, *, school: SchoolConverter):
        """Attach an image to a nation. If an image isn't sent, the current image will be removed"""
        
        path = None
        if ctx.message.attachments:
            att = ctx.message.attachments[0]

            base_path = cog_data_path(self) / f"{ctx.guild.id}"
            if not base_path.exists():
                base_path.mkdir()
            
            ext = att.filename.split('.')[-1]
            path = str(base_path / f"{school.role.id}.{ext}")
            await att.save(path)
        
        await school.set_image_path(path)
        if path:
            await ctx.send(f"{school.name}'s image has been set", )
        else:
            await ctx.send(f"{school.name}'s image has been removed")
        
        disp = await SchoolDisplay.new(self, ctx.guild, ctx.channel.id, [school])
        await disp.display(sent_by=ctx.author)

    @nationset.command(name="swaporder")
    async def nationset_swap_order(self, ctx: commands.Context, schoolA: SchoolConverter, schoolB: SchoolConverter):
        await schoolA.swap_order(schoolB)
        await ctx.send(f"The order of **{schoolA.name}** and **{schoolB.name}** have been swapped")
    

