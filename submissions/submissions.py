import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
import asyncio
from datetime import datetime, timedelta
import random


class Submission():
    
    def __init__(self, cog, member, name=None, tos={}, initial_config={}):
        self.bot = cog.bot
        self.cog = cog
        self.config = cog.config
        self.name = name
        self.to_members = tos
        """
            OPEN_SUBMISSION: {
                name: name,
                color: 0xFFFFFF,
                tos: [ mid, ... ],
                msgs: [
                    {
                        from: msg_id,
                        to: [
                            {
                                to_member: mid,
                                to_msg: msg_id
                            },
                            ...
                        ]
                    },
                    ...
                ]
            }
        """
        self.guild = member.guild
        self.member = member
        self.messages = {}
        """
            {
                msg_id: msg,
                ...
            }
        """
        self.loaded = bool(initial_config)
        self.config_obj = initial_config
        cog.submissions[member.id] = self
        self.start_timer()
        self.bot.loop.create_task(self.load_submission())

    async def wait_to_close(self):
        await asyncio.sleep(30*60)
        try:
            await self.member.send(
                "Took too long, submission is closing. "
                "What you sent has already been delivered. "
                "Don't worry, you can open another submission "
                "and continue where you left off")
        except:
            pass
        await self.finish()

    @classmethod
    async def new(cls, cog, member, name, message=None):
        guild = member.guild
        dest_obj = await cog.config.guild(guild).SUBMISSIONS.get_raw(name)
        config_obj = {
            'name': name,
            'tos': dest_obj['tos'],
            'color': random.randint(0, 0xFFFFFF),
            'msgs': [

            ]
        }
        self = cls(cog, member, name=name, tos={
            mid: guild.get_member(mid) for mid in dest_obj['tos'] if guild.get_member(mid)
        }, initial_config=config_obj)
        self._load_to_members()
        self.loaded = True

        action = member.send
        notes = [
            "All messages to me will be added to your submission",
            "send a message with only **done** to finish your submission"
        ]
        if message:
            await self.new_message(message)
            action = message.reply
            notes.append(
                "Your initial response was recorded. "
                "You don't need to resubmit it, but feel free to add more"
            )
        notes = '\n'.join('* ' + note for note in notes)
        content = dest_obj['prompt'] + (f"\n```md\n{notes}\n```"
        )

        await action(content)
        
    def is_empty(self):
        return bool(self.config_obj)

    async def set_to_members(self):
        self.config.self.member.guild
    
    def _load_to_members(self):
        self.to_members = { mid: self.guild.get_member(mid) for mid in self.config_obj['tos'] if self.guild.get_member(mid) }
    
    async def load_submission(self):
        if self.loaded:
            return
        submission_config = await self.config.member(self.member).OPEN_SUBMISSION()
        if not submission_config:
            return
        
        self.config_obj = submission_config

        self.name = submission_config['name']
        self._load_to_members()
        
        msg_ids = submission_config['msgs']
        if not msg_ids:
            return
        
        first = await self.member.fetch_message(msg_ids[0]['from'])
        from_tos = {mp['from']: mp for mp in msg_ids}

        sm = SubmissionMessage(self, from_tos[first.id])
        self.messages[first.id] = sm
        await sm.load()
    
        async for m in self.member.history(limit=1000, after=first):
            # ignore missed messages when bot was down
            if m.id not in from_tos:
                continue
            # try:
            sm = SubmissionMessage(self, from_tos[m.id])
            self.messages[m.id] = sm
            await sm.load()
            # except:
            #     pass

        self.loaded = True
    
    def is_for(self, user):
        return self.member.id == user.id
    
    async def save(self):
        await self.config.member(self.member).OPEN_SUBMISSION.set(self.config_obj)

    async def finish(self):
        await self.config.member(self.member).clear()
        del self.cog.submissions[self.member.id]
        self.timer.cancel()
    
    def start_timer(self):
        self.timer = self.bot.loop.create_task(self.wait_to_close())

    # TODO: fix multiple timers
    def bump(self):
        self.timer.cancel()
        self.start_timer()
    
    async def new_message(self, msg):
        sm = await SubmissionMessage.new(self, msg)
        self.config_obj['msgs'].append(sm.config_part)
        self.messages[msg.id] = sm
        await self.save()
        self.bump()
    
    async def edit_message(self, msg):
        sm = self.messages[msg.id]
        await sm.edit(msg)
        self.bump()

    async def delete_message(self, msg):
        sm = self.messages[msg.id]
        del self.messages[msg.id]
        await sm.delete()
        await self.save()
        self.bump()


class SubmissionMessage():
    
    def __init__(self, submission, config_part):
        self.submission = submission
        self.config_part = config_part
        self.to_msgs = {}
        self.loaded = bool(config_part)
    
    async def load(self):
        for part in self.config_part['to']:
            m = self.submission.guild.get_member(part['to_member'])
            if not m:
                continue
            msg = await m.fetch_message(part['to_msg'])
            self.to_msgs[msg.id] = msg
        self.loaded = True

    async def _send_to(self, mid, msg):
        dest = self.submission.guild.get_member(mid)
        sent = await dest.send(
            embed=self.make_embed(msg, self.submission.member)
        )
        if msg.attachments:
            await dest.send(
                "Images: " + 
                ", ".join(
                    f"[{i}]({a.url})" for i, a in enumerate(msg.attachments)
                )
            )
        return sent
    
    def make_embed(self, msg, member):
        e = discord.Embed(
            color=self.submission.config_obj['color'],
            description=msg.content
        )
        name = member.name if member.name == member.display_name else f"{member.display_name} ({member.name})"
        avatar = (
            member.guild_avatar.url if member.guild_avatar else 
            member.avatar.url if member.avatar else member.default_avatar.url
        )
        e.set_author(name=name, icon_url=avatar)
        return e
    
    @classmethod
    async def new(cls, submission, msg):
        # config = await self.submission.config.member(self.submission.member).OPEN_SUBMISSION()
        """
            from: msg_id,
            to: [
                {
                    to_member: mid,
                    to_msg: msg_id
                },
                ...
            ]
        """
        co = {
            'from': msg.id,
            'to': []
        }
        omsg = msg
        self = cls(submission, co)
        for mid in submission.to_members:
            msg = await self._send_to(mid, omsg)
            co['to'].append({
                'to_member': mid,
                'to_msg': msg.id
            })
            self.to_msgs[msg.id] = msg

        self.loaded = True

        return self
    
    async def delete(self):
        for mid, m in list(self.to_msgs.items()):
            await m.delete()
            del self.to_msgs[mid]

    async def edit(self, new_msg):
        for mid, m in self.to_msgs.items():
            await m.edit(embed=self.make_embed(new_msg, self.submission.member))

class Submissions(commands.Cog):
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )

        self.config.register_member(**{
            "OPEN_SUBMISSION": None
        })

        self.config.register_guild(**{
            "SUBMISSIONS": {}
        })

        # TODO: make this user based instead of member based
        self.submissions = {}
        self.ready = False

    async def cog_load(self):
        self.bot.loop.create_task(self.setup_after_load())
    
    async def setup_after_load(self):
        await self.bot.wait_until_ready()
        c = await self.config.all_members()
        for gid, cg in c.items():
            g = self.bot.get_guild(gid)
            if g is None:
                continue
            for mid, cm  in cg.items():
                m = g.get_member(mid)
                if m is None:
                    continue
                if cm['OPEN_SUBMISSION']:
                    Submission(self, m, cm['OPEN_SUBMISSION']['name'])

        await super().cog_load()
        self.ready = True
    
    async def cog_unload(self):
        for s in self.submissions.values():
            s.timer.cancel()
        return await super().cog_unload()

    def in_submission(self, message):
        if message.guild is not None:
            return None
        return self.submissions.get(message.author.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        sub = await self.get_and_process_sub(message, check_for_command=True)
        if sub:
            await sub.new_message(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        sub = await self.get_and_process_sub(after)
        if sub:
            await sub.edit_message(after)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        sub = await self.get_and_process_sub(message, check_if_done=False)
        if sub:
            await sub.delete_message(message)

    async def get_and_process_sub(self, message, check_for_command=False, check_if_done=True):
        if message.author.bot:
            return
        
        # a command was used
        if check_for_command:
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return
        
        sub = self.in_submission(message)
        if not sub:
            return
        
        if check_if_done:
            if message.content.lower().strip("*").strip() == 'done':
                await sub.finish()
                await message.author.send("Submitted!")
                return
        
        return sub

    @commands.command()
    @checks.mod()
    async def submission(self, ctx, name: str, *recipients: discord.Member):
        """Add a submission destination. When users type [p]submit <name>,
        this will start a submission session with them where anything they type
        gets sent to the listed recipients
        """
        if ' ' in name:
            return await ctx.reply("name cannot include spaces")
        
        name = name.lower()

        if len(recipients) == 0:
            await self.config.guild(ctx.guild).SUBMISSIONS.clear_raw(name)
            return await ctx.reply(f"Removed submission destination '{name}'")
        

        prompt = await ctx.reply(f"Write a prompt that will be sent to people making new submissions to {name}.")

        def check(m: discord.Message):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=10*60)
        except asyncio.TimeoutError:
            await prompt.reply("Took too long. Try again.")
        

        await self.config.guild(ctx.guild).SUBMISSIONS.set_raw(name, value={
            'prompt': msg.content,
            'tos': [r.id for r in recipients]
        })

        await ctx.reply(f"Submissions to {name} will be sent to {', '.join(r.mention for r in recipients)}")
        # TODO: send test msg


    @commands.command()
    async def submit(self, ctx, to: str, *, text: str=None):
        """Submit a request for one of the available groups.
        Use the command in a guild to see the available groups
        Use the command in DMs with the bot to start submitting
        Send done when you are done.
        """
        if ctx.guild is not None:
            s = await self.config.guild(ctx.guild).SUBMISSIONS()
            if not s:
                return await ctx.reply("Ask a mod to create a submission destination")
            return await ctx.reply(f"You must use this command in DMs with me along with one of the following submission destinations: {', '.join(s.keys())}")

        first_msg_has_content = bool(text)
    
        found = False
        guild = None
        for g in ctx.author.mutual_guilds:
            found = (await self.config.guild(g).SUBMISSIONS()).get(to)
            guild = g
            if found:
                break
        
        if not found:
            return await ctx.reply(f'No submission destination named "{to}"')

        m = guild.get_member(ctx.author.id)
        prev = self.submissions.get(ctx.author.id)
        if prev:
            await prev.finish()
        await self.open_submission(ctx.message, m, to, first_msg_has_content)

    async def open_submission(self, message, member, submission_destination, msg_has_content=False):
        await Submission.new(self, member, submission_destination, message if msg_has_content else None)

    async def add_to_submission(self, member, message):
        pass
    
    async def edit_to_submission(self, member, message):
        pass
