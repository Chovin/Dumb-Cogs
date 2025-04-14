import discord
from discord.errors import NotFound, HTTPException

from redbot.core.bot import Red
from redbot.core.config import Config

from typing import Union, List
from datetime import datetime, timedelta
import asyncio
import re

from .checklist import Checklist, ChecklistSelect
from .helpers import get_thread, role_mention, MissingMember, IterCache, int_to_emoji, CONTAINS_PRE, CONTAINS_POST
from .statusimage import statuses
from .wufoo import WufooDB
from .log import log as debug_log

MENTION_EVERYONE = discord.AllowedMentions(roles=True, users=True, everyone=True)


def identifiable_name(member):
    return f"{member.display_name} ({member.name})" if member.name != member.display_name else member.name


class MissingDB(Exception): pass

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
    def __init__(self, member: discord.Member, guild: discord.Guild, config: Config, bot: Red, wufooDB: WufooDB=None):
        self.guild = guild
        self.member = member
        self.config = config
        self.thread = None
        self.checklist: Checklist
        self.display_message: discord.Message
        self.log: Log
        self.bot = bot
        self.wufooDB = wufooDB
        self.displayed = False
        self.closed: bool
        self.feedback = []
        self.images = []
        self.messages = 0
        self.total_messages = 0
        self.first_message_link: str
        self.last_checklist_date: datetime
        self.last_message_date: datetime
        self.update: bool
        self.display_lock = asyncio.Lock()
        self.wufoo_skipped = False

    @classmethod
    async def new(cls, member: discord.Member, guild: discord.Guild, config: Config, bot: Red, wufooDB: WufooDB=None):
        if member.bot:
            raise ValueError("Cannot create application for bot.")
        app = cls(member, guild, config, bot, wufooDB)

        forum = guild.get_channel(await config.guild(guild).TRACKING_CHANNEL())
        if forum is None:
            raise ValueError("Tracking channel not found.")

        mconf = config.member(member)
        await mconf.ID.set(member.id)

        app.closed = await mconf.APP_CLOSED()
        app.feedback = [Feedback.from_dict(d) for d in await mconf.FEEDBACK()]
        app.images = [Image.from_dict(d) for d in await mconf.IMAGES()]
        app.messages = await mconf.MESSAGES()
        app.total_messages = await mconf.TOTAL_MESSAGES()
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
                if not isinstance(member, MissingMember):
                    await app.log.post("Joined", member.joined_at)
            
            if not app.closed:
                await app.close()
            
            # wufoodb not set yet
            try:
                await app.check_application_forms()
            except AttributeError as e:
                app.wufoo_skipped = True
                pass
        else:
            app.displayed = True
            app.checklist = await Checklist.new(app.config.member(member).CHECKLIST, app.bot, app.guild, app.member, app)
            await app.set_thread(thread)
            app.display_message = await app.thread.fetch_message(await app.config.member(member).DISPLAY_MESSAGE_ID())
            logmsg = None
            try:
                logmsg = await app.thread.fetch_message(await app.config.member(member).LOG_MESSAGE_ID())
            except:
                pass
            app.log = await Log.new(mconf.LOG, logmsg, app.thread)
            if app.closed and not app.thread.archived:
                await app.close()
            elif not app.closed and app.thread.archived:
                await app.open()
        
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
    
    def set_wufooDB(self, wufooDB):
        self.wufooDB = wufooDB
    
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
            if self.thread.archived == self.closed:
                await self.notify("Application reopened")
            else:
                self.closed = False
                await self.set_thread(await self.thread.edit(archived=False))
            await self.post_images()
            await self.send_rest_feedback()
        await self.config.member(self.member).APP_CLOSED.set(False)
        self.closed = False
        self.bot.dispatch("gapps_app_opened", self)

    async def close(self):
        if self.displayed and self.thread.archived and self.closed:
            return
        if self.displayed:
            if self.thread.archived == self.closed:
                await self.notify("Application closed", notify_role=False)
            self.closed = True
            await self.set_thread(await self.thread.edit(archived=True))
        await self.config.member(self.member).APP_CLOSED.set(True)
        self.closed = True
        self.bot.dispatch("gapps_app_closed", self)

    async def set_thread(self, thread):
        await self.config.member(self.member).THREAD_ID.set(thread.id)
        self.thread = thread
        self.bot.dispatch("gapps_app_thread_set", self)

    async def record_checklist_update(self):
        self.last_checklist_date = datetime.now()
        await self.config.member(self.member).LAST_CHECKLIST_DATE.set(self.last_checklist_date.timestamp())

    async def new_message(self, message: discord.Message):
        self.messages += 1
        self.total_messages += 1
        await self.config.member(self.member).MESSAGES.set(self.messages)
        await self.config.member(self.member).TOTAL_MESSAGES.set(self.total_messages)
        if self.messages == 1:
            await self.config.member(self.member).FIRST_MESSAGE_LINK.set(message.jump_url)
        self.last_message_date = datetime.now()
        await self.config.member(self.member).LAST_MESSAGE_DATE.set(self.last_message_date.timestamp())
        await self.config.member(self.member).UPDATE.set(True) 
        self.update = True
    
    async def set_messages(self, messages: int):
        await self.config.member(self.member).MESSAGES.set(messages)
        self.messages = messages

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

    async def post_images(self, images: List[Image]=[], force=False):
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

    async def post_applications(self, force=False, not_done_displaying=False):
        try:
            emap = self.wufooDB.member_map.get(str(self.member.id), [])
        except AttributeError:
            raise MissingDB
        emap = [e for e in emap if (not e['sent']) or force]
        if not emap:
            return

        answers = "\n".join("\n".join(answer for answer in self.wufooDB.get(e['key']).entry_values()) for e in emap)
        to_finds = []
        app_sent_ci = False
        # update relavent checklist items
        for c in await self.checklist.checklist_items():
            ci_title = str(c.value).lower()
            if ci_title == 'application sent':
                c.done = True
                await self.checklist.update_item(c)
                app_sent_ci = True
            elif ci_title.startswith(('used', 'contains')):
                to_find = ci_title.split(' ', 1)[-1]
                to_finds.append(to_find)
                if re.search(
                        CONTAINS_PRE + re.escape(to_find) + CONTAINS_POST, 
                        answers, flags=re.IGNORECASE
                    ):
                    c.done = True
                    await self.checklist.update_item(c)
        
        if await Application.app_exempt(self.config, self.member):
            return
        
        if (not self.displayed) and not not_done_displaying:
            await self.display()
        elif not_done_displaying:
            self.bot.dispatch('gapps_trigger_app_display', self)

        for e in emap:
            sent = await self.send_application(self.wufooDB.get(e['key']), to_finds)
            e['sent'] = sent
        
        await self.wufooDB.save_member_map()

        # log this event if there's no checklist item with the name "Application Sent"
        if not app_sent_ci:
            await self.log.post("Application Sent", datetime.now())

    async def send_application(self, application, highlights=[]):
        if await Application.app_exempt(self.config, self.member):
            return False
        
        sent = None
        for e in application.embeds(highlights):
            sent = sent or await self.thread.send(embed=e)
        
        # pin first message
        await sent.pin()
        return True
    
    async def triggered_alarms(self):
        times = self.alarm_times()
        track_alarms = await self.config.member(self.member).TRACK_ALARMS()
        return [kind for kind in times if times[kind].timestamp() == track_alarms[kind]]

    def alarm_times(self):
        ret = {
            "message": self.last_message_date,
            "checklist": self.last_checklist_date
        }
        if not isinstance(self.member, MissingMember):
            ret["joined"] = datetime.fromtimestamp(self.member.joined_at.timestamp())

        return ret

    async def post_if_needed(self):
        await self.check_application_forms()
        if self.closed:
            await self.close()
        self.wufoo_skipped = False

    async def check_application_forms(self):
        if await Application.app_exempt(self.config, self.member):
            return
        mm = self.wufooDB.member_map.get(str(self.member.id))
        if not mm:
            return
        if len([e for e in mm if not e['sent']]):
            await self.display()

    async def check_and_alarm(self):
        now = datetime.now()
        alarms_before = {
            kind: now - timedelta(days=days) 
            for kind, days in (await self.config.guild(self.guild).ALARMS()).items()
            if days > 0
        }
        times = self.alarm_times()
        # ignore alarms that have already gone off
        mconf = self.config.member(self.member)
        track_alarms = await mconf.TRACK_ALARMS()
        for kind, timestamp in track_alarms.items():
            if datetime.fromtimestamp(timestamp) == times.get(kind):
                del times[kind]
        offenses = []
        for kind, before_date in alarms_before.items():
            if times.get(kind, before_date) < before_date:
                offenses.append(kind)
        if offenses:
            await self.notify(*[f"<t:{int(times[o].timestamp())}:R> since last {o}{' item' if o == 'checklist' else ''}" for o in offenses])
            await mconf.TRACK_ALARMS.set({**track_alarms, **{o: times[o].timestamp() for o in offenses}})
            if self.displayed:
                await self.display()

    async def notify(self, *msgs, notify_role=True):
        if not self.displayed:
            return
        if notify_role:
            role = self.guild.get_role(await self.config.guild(self.guild).MENTION_ROLE())
        else:
            role = None
        multiple_nl = "\n" if len(msgs) > 1 else ''
        await self.thread.send(f"{role_mention(role) if role else ''} {self.member.mention} {multiple_nl}" + "\n".join(msgs), allowed_mentions=MENTION_EVERYONE)

    async def display(self):
        async with self.display_lock:
            await self._display()

    async def _display(self):    
        if await Application.app_exempt(self.config, self.member):
            if not self.closed:
                await self.close()
            return

        status = (await self.config.member(self.member).STATUS()).lower()
        if isinstance(self.member, MissingMember):
            name = await self.config.member(self.member).NAME()
            timestamp = await self.config.member(self.member).LEFT_AT()
            if not name:
                name = f'<@ {self.member.id} >'
        else:
            name = identifiable_name(self.member)
            timestamp = int(self.member.joined_at.timestamp())
        joinmsg = f"{self.member.mention} {status} <t:{timestamp}:R>"
        
        msgs = self.messages
        firstmsglink = self.first_message_link

        extra = ""
        if msgs != self.total_messages:
            extra = f" ({self.total_messages} total)"
        msgsmsg = f"__**{msgs}**__ msgs{extra}" + (f" ({firstmsglink})" if firstmsglink else "")

        updatemsg = (
            f"<t:{int(self.last_message_date.timestamp())}:R> (last msg)\n"
            f"<t:{int(self.last_checklist_date.timestamp())}:R> (last checklist)"
        )


        rolesmsg = "**Roles:**\n" + " ".join(r.mention for r in self.member.roles if r != self.guild.default_role)

        await self.checklist.refresh_items(True, dispatch=False)
        checklistmsg = f"**Checklist:**\n" + await self.checklist.to_str()

        txt = f"{joinmsg}\n{msgsmsg}\n\n{updatemsg}\n\n{rolesmsg}\n\n{checklistmsg}"

        mconf = self.config.member(self.member)

        # attachments
        simgs = await self.config.guild(self.guild).STATUS_IMAGES()
        stats = await statuses(mconf)
        status = {
            "single": None,
            "compounds": []
        }
        cis = await self.checklist.checklist_items()
        triggered_alarms = await self.triggered_alarms()
        for s in stats:
            val = s['value']
            if str(val) not in simgs:
                continue
            if s['compound']:
                action = status['compounds'].append
            else:
                action = lambda v: status.__setitem__("single", str(v))
            if val == "Joined":
                action(val)
            for ci in cis:
                if ci.value == val and ci.done:
                    action(val)
                    break
            for alarm in triggered_alarms:
                if alarm == val:
                    action(val)
                    break

        paths = [simgs[s] for s in filter(None, reversed([status['single'], *status['compounds']]))]

        files = [discord.File(p) for p in paths][:10]

        forum = self.guild.get_channel(await self.config.guild(self.guild).TRACKING_CHANNEL())

        thread_id = await mconf.THREAD_ID()
        thread = await get_thread(forum, thread_id)
        
        if thread is None:
            thread_with_message = await forum.create_thread(
                name=name,
                content=txt,
                files=files,
                view=discord.ui.View().add_item(ChecklistSelect(self.checklist))
            )
            await self.set_thread(thread_with_message.thread)
            await mconf.DISPLAY_MESSAGE_ID.set(thread_with_message.message.id)
            self.display_message = thread_with_message.message

            await self.open()

            logmsg = await self.log.post([], channel=thread_with_message.thread)
            await mconf.LOG_MESSAGE_ID.set(logmsg.id)

            await thread_with_message.message.pin()
            await logmsg.pin()

            await self.post_applications(force=True, not_done_displaying=True)
            await self.post_images(force=True)
            await self.send_rest_feedback(force=True)

            new_msg = thread_with_message.thread
        else:
            # unarchive thread if archived
            await self.open()
            old_log_id = await mconf.LOG_MESSAGE_ID()
            log_msg = await self.log.post([], datetime.now())
            if old_log_id != log_msg.id:
                await mconf.LOG_MESSAGE_ID.set(log_msg.id)
            new_msg = await self.display_message.edit(content=txt, attachments=files)

        self.displayed = True
        await self.config.member(self.member).UPDATE.set(False)
        self.update = False

        return new_msg