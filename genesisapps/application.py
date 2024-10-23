import discord
from discord.errors import NotFound, HTTPException

from redbot.core.bot import Red
from redbot.core.config import Config

from typing import Union
from datetime import datetime
import asyncio

from .checklist import Checklist, ChecklistSelect
from .helpers import get_thread, role_mention, MissingMember

MENTION_EVERYONE = discord.AllowedMentions(roles=True, users=True, everyone=True)

class Log:
    def __init__(self, config: Config, message=None, channel=None):
        self.config = config
        self.message = message
        self.channel = channel

        self.entries: list[LogEntry]
    
    @classmethod
    async def new(cls, config: Config, message=None, channel=None):
        log = cls(config, message, channel)
        log.entries = [LogEntry(content, timestamp) for timestamp, content in await config()]
        return log

    def __str__(self):
        s = "**Log:**\n" +'\n'.join(str(entry) for entry in self.entries)
        si = 2
        while len(s) > 1800:
            s = f"**Log:**\n{self.entries[0]}\n-# `...`\n" + '\n'.join(str(entry) for entry in self.entries[si:])
            si += 1
        
        return s
    
    async def post(self, content: Union[str, list] = [], timestamp: int=None, channel=None):
        if isinstance(content, str):
            content = [content]
        timestamp = timestamp or int(datetime.now().timestamp())
        if isinstance(timestamp, datetime):
            timestamp = int(timestamp.timestamp())
        self.entries += [LogEntry(c, timestamp) for c in content]
        await self.config.set(self.serialize())
        self.channel = channel or self.channel
        try:
            self.message = await self.message.edit(content=str(self))
        except (AttributeError, NotFound):
            try:
                self.message = await self.channel.send(str(self))
            except:
                return None
        except HTTPException:  # thread archived most likely
            return None
        return self.message
    
    def serialize(self):
        return [entry.serialize() for entry in self.entries]
    
    def __len__(self):
        return len(self.entries)


class LogEntry:
    def __init__(self, content: str, timestamp: int):
        self.content = content
        self.timestamp = timestamp
    
    def __str__(self):
        nowts = self.timestamp
        return f"-# <t:{nowts}:d><t:{nowts}:t> (<t:{nowts}:R>) - **{self.content}**"
    
    def serialize(self):
        return [self.timestamp, self.content]
    

class Image:
    def __init__(self, image_url, jump_url, sent, index):
        self.image_url = image_url
        self.jump_url = jump_url
        self.sent = sent
        self.index = index
    
    @classmethod
    def from_dict(cls, dct):
        return cls(dct['image_url'], dct['jump_url'], dct['sent'], dct['index'])
    
    def serialize(self):
        return {
            'image_url': self.image_url,
            'jump_url': self.jump_url,
            'sent': self.sent,
            'index': self.index
        }
    
    def __str__(self):
        return f"[{self.index+1}]({self.image_url}): {self.jump_url}"


class Feedback:
    def __init__(self, content, author_name, author_avatar_url, jump_url, sent):
        self.content = content
        self.author_name = author_name
        self.author_avatar_url = author_avatar_url
        self.jump_url = jump_url
        self.embed = self.make_feedback_embed()
        self.sent = sent
    
    @classmethod
    def from_message(cls, message: discord.Message):
        return cls(message.content, message.author.name, message.author.display_avatar.url, message.jump_url, False)

    @classmethod
    def from_dict(cls, dct):
        return cls(dct['content'], dct['author_name'], dct['author_avatar_url'], dct['jump_url'], dct['sent'])

    def make_feedback_embed(self):
        return discord.Embed(description=self.content).set_author(
            name=self.author_name, url=self.jump_url, icon_url=self.author_avatar_url)
    
    def serialize(self):
        return {
            'content': self.content,
            'author_name': self.author_name,
            'author_avatar_url': self.author_avatar_url,
            'jump_url': self.jump_url,
            'sent': self.sent
        }


class Application:
    def __init__(self, member: discord.Member, guild: discord.Guild, config: Config, bot: Red):
        self.guild = guild
        self.member = member
        self.config = config
        self.thread = None
        self.checklist: Checklist
        self.display_message: discord.Message
        self.log: Log
        self.bot = bot
        self.displayed = False
        self.closed: bool
        self.feedback = []
        self.images = []
        self.messages = 0
        self.first_message_link: str
        self.last_checklist_date: datetime
        self.last_message_date: datetime
        self.update: bool
        self.display_lock = asyncio.Lock()

    @classmethod
    async def new(cls, member: discord.Member, guild: discord.Guild, config: Config, bot: Red):
        if member.bot:
            raise ValueError("Cannot create application for bot.")
        app = cls(member, guild, config, bot)

        forum = guild.get_channel(await config.guild(guild).TRACKING_CHANNEL())
        if forum is None:
            raise ValueError("Tracking channel not found.")

        mconf = config.member(member)

        await mconf.ID.set(member.id)

        app.closed = await mconf.APP_CLOSED()
        app.feedback = [Feedback.from_dict(d) for d in await mconf.FEEDBACK()]
        app.images = [Image.from_dict(d) for d in await mconf.IMAGES()]
        app.messages = await mconf.MESSAGES()
        app.first_message_link = await mconf.FIRST_MESSAGE_LINK()
        lcd = await mconf.LAST_CHECKLIST_DATE()
        app.last_checklist_date = datetime.fromtimestamp(lcd) if lcd else datetime.now()
        lmd = await mconf.LAST_MESSAGE_DATE()
        app.last_message_date = datetime.fromtimestamp(lmd) if lmd else datetime.now()
        app.update = await mconf.UPDATE()

        thread_id = await mconf.THREAD_ID()
        thread = await get_thread(forum, thread_id)
        # if user's first join or thread got deleted, etc
        if not thread:
            # record member
            await config.guild(guild).APP_MEMBERS.set_raw(f"{member.id}", value=True)

            # create checklist
            await app.create_checklist()

            # create log
            app.log = await Log.new(mconf.LOG)
            if len(app.log) == 0:
                await app.log.post("Joined", member.joined_at)
            
            if not app.closed:
                await app.close()
        else:
            app.displayed = True
            app.checklist = await Checklist.new(app.config.member(member).CHECKLIST, app.bot, app.guild, app.member, app)
            app.thread = thread
            app.display_message = await app.thread.fetch_message(await app.config.member(member).DISPLAY_MESSAGE_ID())
            logmsg = await app.thread.fetch_message(await app.config.member(member).LOG_MESSAGE_ID())
            app.log = await Log.new(mconf.LOG, logmsg, app.thread)
            if app.closed and not app.thread.archived:
                await app.open()
            elif not app.closed and app.thread.archived:
                await app.close()
        
        return app
    
    @classmethod
    async def app_exempt(cls, config, member):
        if await cls.has_manual_exempt(config, member):
            return True
        
        return await cls.has_exempt_role(config, member)

    @classmethod
    async def set_manual_exempt(cls, config, member, value):
        await config.member(member).APP_EXEMPT.set(value)
        return value

    @classmethod
    async def has_manual_exempt(cls, config, member):
        return await config.member(member).APP_EXEMPT()
    
    @classmethod
    async def has_exempt_role(cls, config, member):
        exempt_role = await config.guild(member.guild).APPLICATION_EXEMPT_ROLE()
        if exempt_role:
            for role in member.roles:
                if role.id == exempt_role:
                    return role
        return False    
    
    async def seen_activity(self):
        return len(await self.checklist.done_items()) > 0 or self.messages > 0

    async def create_checklist(self):
        mconf = self.config.member(self.member)
        if not await mconf.CHECKLIST():
            cl = await Checklist.new_from_template(
                await self.config.guild(self.guild).CHECKLIST_TEMPLATE(),
                mconf.CHECKLIST, self.bot, self.guild, self.member, self
            )
        else:
            cl = await Checklist.new(mconf.CHECKLIST, self.bot, self.guild, self.member, self)
        self.checklist = cl

    async def create_thread(self):
        return await self.display()
    
    async def open(self):
        if self.displayed and (not self.thread.archived) and not self.closed:
            return
        if self.displayed:
            role = self.guild.get_role(await self.config.guild(self.guild).MENTION_ROLE())
            await self.thread.send(f"{role_mention(role)} Application reopened", allowed_mentions=MENTION_EVERYONE)
            # self.thread = await self.thread.edit(archived=False)  # .send opens it
            await self.post_images()
            await self.send_rest_feedback()
        await self.config.member(self.member).APP_CLOSED.set(False)
        self.closed = False
        self.bot.dispatch("gapps_app_opened", self)

    async def close(self):
        if self.displayed and self.thread.archived and self.closed:
            return
        if self.displayed:
            role = self.guild.get_role(await self.config.guild(self.guild).MENTION_ROLE())
            await self.thread.send(f"{role_mention(role)} Application closed", allowed_mentions=MENTION_EVERYONE)
            self.thread = await self.thread.edit(archived=True)
        await self.config.member(self.member).APP_CLOSED.set(True)
        self.closed = True
        self.bot.dispatch("gapps_app_closed", self)

    async def record_checklist_update(self):
        self.last_checklist_date = datetime.now()
        await self.config.member(self.member).LAST_CHECKLIST_DATE.set(self.last_checklist_date.timestamp())

    async def new_message(self, message: discord.Message):
        self.messages += 1
        await self.config.member(self.member).MESSAGES.set(self.messages)
        if self.messages == 1:
            await self.config.member(self.member).FIRST_MESSAGE_LINK.set(message.jump_url)
        self.last_message_date = datetime.now()
        await self.config.member(self.member).LAST_MESSAGE_DATE.set(self.last_message_date.timestamp())
        await self.config.member(self.member).UPDATE.set(True) 
        self.update = True

    async def add_feedback(self, message: discord.Message):
        fb = Feedback.from_message(message)
        self.feedback += [fb]
        if self.displayed:
            await self.thread.send(embed=fb.embed)
            fb.sent = True
        await self.config.member(self.member).FEEDBACK.set([f.serialize() for f in self.feedback])

    async def send_rest_feedback(self, force=False):
        fbs = []
        for fb in self.feedback:
            if (not fb.sent) or force:
                if len(fbs) < 10 and sum(len(f.content) for f in fbs) < 3000:
                    fbs += [fb]
                else:
                    await self.thread.send(embeds=[f.embed for f in fbs])
                    for f in fbs:
                        f.sent = True
                    fbs = [fb]
        if fbs:
            await self.thread.send(embeds=[f.embed for f in fbs])
            for f in fbs:
                f.sent = True
        
        await self.config.member(self.member).FEEDBACK.set([f.serialize() for f in self.feedback])

    async def post_images(self, images: Image=[], force=False):
        ims = []
        if force:
            await self.config.member(self.member).IMAGE_MESSAGE_URLS.set([])
        img_messages = await self.config.member(self.member).IMAGE_MESSAGE_URLS()

        async def send_images(ims, img_messages):
            if self.displayed:
                msg = await self.thread.send(f"[images {len(img_messages) + 1}]\n* {', '.join([str(i) for i in ims])}")
                img_messages.append(msg.jump_url)
            for im in ims:
                im.sent = self.displayed

        for im in self.images + images:
            if (not im.sent) or force:
                if len(ims) < 5:
                    ims += [im]
                else:
                    await send_images(ims, img_messages)
                    ims = [im]
        if ims:
            await send_images(ims, img_messages)
        await self.config.member(self.member).IMAGE_MESSAGE_URLS.set(img_messages)
        await self.config.member(self.member).IMAGES.set([i.serialize() for i in self.images + images])
        self.images = self.images + images

    async def display(self):
        async with self.display_lock:
            await self._display()

    async def _display(self):    
        if await Application.app_exempt(self.config, self.member):
            if not self.closed:
                await self.close()
            return

        if isinstance(self.member, MissingMember):
            joinmsg = f"{self.member.mention} left/kicked <t:{await self.config.member(self.member).LEFT_AT()}:R>"
        else:
            joinmsg = f"{self.member.mention} joined <t:{int(self.member.joined_at.timestamp())}:R>"
        
        msgs = self.messages
        firstmsglink = self.first_message_link

        msgsmsg = f"__**{msgs}**__ messages" + (f" ({firstmsglink})" if firstmsglink else "")

        rolesmsg = "**Roles:**\n" + " ".join(r.mention for r in self.member.roles if r != self.guild.default_role)

        await self.checklist.refresh_items(True, dispatch=False)
        checklistmsg = f"**Checklist:**\n" + await self.checklist.to_str()

        txt = f"{joinmsg}\n{msgsmsg}\n\n{rolesmsg}\n\n{checklistmsg}"

        mconf = self.config.member(self.member)

        forum = self.guild.get_channel(await self.config.guild(self.guild).TRACKING_CHANNEL())

        thread_id = await mconf.THREAD_ID()
        thread = await get_thread(forum, thread_id)
        
        if thread is None:
            thread_with_message = await forum.create_thread(
                name=self.member.name,
                content=txt,
                view=discord.ui.View().add_item(ChecklistSelect(self.checklist))
            )
            await mconf.THREAD_ID.set(thread_with_message.thread.id)
            self.thread = thread_with_message.thread
            await mconf.DISPLAY_MESSAGE_ID.set(thread_with_message.message.id)
            self.display_message = thread_with_message.message

            await self.open()

            logmsg = await self.log.post([], channel=thread_with_message.thread)
            await mconf.LOG_MESSAGE_ID.set(logmsg.id)

            await thread_with_message.message.pin()
            await logmsg.pin()

            await self.post_images(force=True)
            await self.send_rest_feedback(force=True)

            new_msg = thread_with_message.thread
        else:
            # unarchive thread if archived
            await self.open()
            old_log_id = await mconf.LOG_MESSAGE_ID()
            log_msg = await self.log.post([str(ci) for ci in self.checklist.changed_items], datetime.now())
            if old_log_id != log_msg.id:
                await mconf.LOG_MESSAGE_ID.set(log_msg.id)
            new_msg = await self.display_message.edit(content=txt)

        self.displayed = True
        await self.config.member(self.member).UPDATE.set(False)
        self.update = False

        return new_msg