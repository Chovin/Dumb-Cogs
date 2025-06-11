import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from datetime import timedelta
from redbot.core.utils.menus import SimpleMenu
from redbot.core.data_manager import bundled_data_path
from typing import Optional
import json
import re

# TODO: add other actions like kick/ban


class TimeoutWords(commands.Cog):
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )

        # words derived from https://github.com/zacanger/profane-words/blob/master/words.json
        self.default_words = json.load(
            open(bundled_data_path(self) / "words.json")
        )

        self.default_dm = "You have been timed out for using `{word}`"

        self.config.register_guild(**{
            "WORDS": {},
            "EXEMPT_ROLE": None,
            "TIMEOUT": 60 * 60, # 1 hour
            "NOTIFY_CHANNEL": None,
            "NOTIFY_ROLES": [],
            "DM_MSG": self.default_dm,
            "NOTIFY_ORIGINAL_CHANNEL": True
        })
        self.word_cache = {}
        self.prev_msgs = {}

    async def cog_load(self):
        guilds = await self.config.all_guilds()
        for gid, data in guilds.items():
            words = data.get("WORDS", {})
            for word in words:
                self.set_in_cache(gid, word)
        
    def word_to_cache_word(self, word):
        if word.startswith('\\b'):
            try:
                return re.compile(word)
            except re.error as e:
                raise e
        else:
            return word.lower()
        
    def set_in_cache(self, gid, pattern):
            cached_word = self.word_to_cache_word(pattern)
            self.word_cache.setdefault(gid, {})[pattern] = cached_word

    async def set_words(self, guild, *pattern_name_pairs):
        """
        Set a timeout word patterns
        """
        words = await self.config.guild(guild).WORDS()
        if len(pattern_name_pairs)%2 != 0:
            raise ValueError(f"pattern_name_pairs must be in key-value pairs. {len(pattern_name_pairs)} {pattern_name_pairs}")
        for i in range(0, len(pattern_name_pairs), 2):
            pattern = pattern_name_pairs[i]
            name = pattern_name_pairs[i+1]

            self.set_in_cache(guild.id, pattern)
            words[pattern] = name

        await self.config.guild(guild).WORDS.set(words)
    
    async def del_word(self, guild, pattern):
        words = await self.config.guild(guild).WORDS()
        if guild.id in self.word_cache and pattern in self.word_cache[guild.id]:
            del self.word_cache[guild.id][pattern]
        del words[pattern]
        await self.config.guild(guild).WORDS.set(words)
         
    def embed_msg(self, message, title=None):
        e = discord.Embed(
            timestamp=message.created_at,
            title=title,
            description=message.content,
            color=message.author.accent_color or discord.Color.random()
        )
        e.set_author(
            name=message.author.display_name or message.author.name, 
            icon_url=message.author.display_avatar.url,
            url=message.jump_url
        )
        e.set_footer(text=f"#{message.channel}")
        return e

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild:
            return
        
        guild_id = message.guild.id
        words = self.word_cache.get(guild_id, {})

        if not words:
            return
        
        prev_msg = self.prev_msgs.get(message.channel.id)
        self.prev_msgs[message.channel.id] = message

        if message.author.bot:
            return
        
        exempt_role_id = await self.config.guild(message.guild).EXEMPT_ROLE()   

        exempt_role = message.guild.get_role(exempt_role_id) if exempt_role_id else None
        if exempt_role and exempt_role in message.author.roles:
            return
        
        content = message.content.lower().strip() if message.content else ''

        if not content:
            return
        
        for pattern, cached_word in words.items():
            if isinstance(cached_word, re.Pattern):
                if cached_word.search(f" {message.content} "):
                    await self.handle_timeout(message, pattern, prev_msg)
                    break
            elif cached_word in message.content.lower():
                await self.handle_timeout(message, pattern, prev_msg)
                break
        

    async def handle_timeout(self, message, pattern, prev_msg=None):
        guild = message.guild
        words = await self.config.guild(guild).WORDS()
        if pattern not in words:
            return
        
        notify_channel_id = await self.config.guild(guild).NOTIFY_CHANNEL()
        notify_roles = await self.config.guild(guild).NOTIFY_ROLES()
        notify_channel = guild.get_channel(notify_channel_id) if notify_channel_id else None

        # delete message
        try:
            await message.delete()
        except discord.Forbidden:
            await (notify_channel or message.channel).send("I do not have permission to delete messages.")

        name = words[pattern]
        timeout_duration = await self.config.guild(guild).TIMEOUT()

        # timeout user
        timedout = True
        try:
            await message.author.timeout(timedelta(seconds=timeout_duration), reason=f"Timeout word: {name}")
        except discord.Forbidden:
            timedout = False
            await (notify_channel or message.channel).send("I do not have permission to timeout members.")
        
        # send notification w/ prev and deleted msg
        if notify_channel:
            embeds = [self.embed_msg(message)]
            if prev_msg:
                embeds.insert(0, self.embed_msg(prev_msg, title="(Previous Message for context)"))
            nr_mentions = ", ".join(role.mention for role in guild.roles if role.id in notify_roles)
            try:
                await notify_channel.send(
                    embeds=embeds, 
                    content=f"{nr_mentions} The user {message.author.mention} has {'been' if timedout else 'failed to be'} timed out for saying `{name}`.", 
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
            except discord.Forbidden:
                await message.channel.send("I do not have permission to send messages in the notify channel.")

        # dm user
        dm_msg = await self.config.guild(guild).DM_MSG()
        dm_msg = dm_msg.replace("{word}", name)
        
        try:
            await message.author.send(dm_msg)
            await message.author.send(embed=self.embed_msg(message, title="Offending Message"))
        except discord.Forbidden:
            pass

        if await self.config.guild(guild).NOTIFY_ORIGINAL_CHANNEL():
            await message.channel.send(f"User {message.author.mention} has {'been' if timedout else 'failed to be'} timed out.")
            
    @commands.group()
    @checks.mod()
    @commands.bot_has_permissions(manage_messages=True)
    async def timeoutwords(self, ctx):
        """Manage timeout words in this server.
        Note: Requires Manage Messages and Moderate Members (Timeout Members) permissions."""
        pass

    @timeoutwords.command(name="msgchannel")
    async def tw_msgchannel(self, ctx):
        """
        Whether or not to notify the original channel where the timeout word was used
        """
        current_setting = await self.config.guild(ctx.guild).NOTIFY_ORIGINAL_CHANNEL()
        new_setting = not current_setting
        await self.config.guild(ctx.guild).NOTIFY_ORIGINAL_CHANNEL.set(new_setting)
        status = "enabled" if new_setting else "disabled"
        return await ctx.reply(f"Notification in the original channel is now {status}.")

    @timeoutwords.command(name="notifyroles")
    async def tw_notifyroles(self, ctx, *roles: discord.Role):
        """
        Set the roles that will be notified when a timeout word is used
        If no roles are provided, it will reset to an empty list
        """
        if not roles:
            await self.config.guild(ctx.guild).NOTIFY_ROLES.set([])
            return await ctx.reply("Notification roles have been reset to an empty list.")
        
        role_ids = [role.id for role in roles]
        await self.config.guild(ctx.guild).NOTIFY_ROLES.set(role_ids)
        role_mentions = ", ".join(role.mention for role in roles)
        return await ctx.reply(f"Notification roles set to: {role_mentions}")

    @timeoutwords.command(name="dm")
    async def tw_dm(self, ctx, *, message: Optional[str] = None):
        """
        Set the DM message that will be sent to users when they are timed out
        If no message is provided, it will reset to the default message

        use {word} to include the word that caused the timeout
        """
        if message is None:
            await self.config.guild(ctx.guild).DM_MSG.set(self.default_dm)
            return await ctx.reply(f"DM message has been reset to default: {self.default_dm}")
        
        await self.config.guild(ctx.guild).DM_MSG.set(message)
        return await ctx.reply(f"DM message set to: {message}")

    @timeoutwords.command(name="notifychannel")
    async def tw_setchannel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """
        Set the channel where timeouts will be notified
        """
        if channel is None:
            channel = ctx.channel
        
        await self.config.guild(ctx.guild).NOTIFY_CHANNEL.set(channel.id)
        return await ctx.reply(f"Timeouts will now notify the {channel.mention} channel")

    @timeoutwords.command(name="timeout")
    async def tw_settimeout(self, ctx, timeout: Optional[int] = None):
        """
        Set the timeout duration for timeout words in seconds
        If no timeout is provided, it will be set to 1 hour (3600 seconds)
        """
        if timeout is None:
            timeout = 3600
        if timeout < 60:
            return await ctx.reply("Timeout must be at least 60 seconds.")
        await self.config.guild(ctx.guild).TIMEOUT.set(timeout)
        await ctx.reply(f"Timeout set to {timeout} seconds.")

    @timeoutwords.command(name="exemptrole")
    async def tw_exemptrole(self, ctx, role: Optional[discord.Role] = None):
        """
        Set the role that is exempt from timeout words
        If no role is provided, it will be set to None
        """
        if role is None:
            await self.config.guild(ctx.guild).EXEMPT_ROLE.set(None)
            return await ctx.reply("Exempt role has been removed.")
        
        await self.config.guild(ctx.guild).EXEMPT_ROLE.set(role.id)
        await ctx.reply(f"Exempt role set to {role.mention}.")

    @timeoutwords.command(name="list")
    async def tw_list(self, ctx):
        """
        List all timeout word patterns in this server
        """

        words = await self.config.guild(ctx.guild).WORDS()
        if not words:
            return await ctx.reply("No timeout words set.")
        
        pages = []
        # 20 words per page
        word_items = list(words.items())
        for i in range(0, len(word_items), 20):
            page_words = word_items[i:i+20]
            page_content = [f"`{pattern}`: {name}" for pattern, name in page_words]
            pages.append("\n".join(page_content))
        
        await SimpleMenu(pages=pages, timeout=60).start(ctx)
    
    @timeoutwords.command(name="set", aliases=["add"])
    async def tw_set(self, ctx, pattern: str, name: str = None):
        """
        Set a timeout word pattern
        Note: patterns are case-insensitive and can be regex
        Begin patterns with \\b if you want them to be regex
        If name is not provided, it will be the same as the pattern
        Surround pattern and name with quotes if they contain spaces
        
        Example: [p]timeoutwords set \\btest\\b "Test Word"
        """
        name = name or pattern
        try:
            await self.set_words(ctx.guild, pattern, name)
        except re.error as e:
            await ctx.reply(f"Invalid regex pattern: {e}")
        except Exception as e:
            raise e
        else:
            await ctx.reply(f"Set timeout word: `{pattern}` displayed as `{name}`")

    @timeoutwords.command(name="setdefault", aliases=["adddefault"])
    async def tw_setdefault(self, ctx):
        """
        Adds a list of default timeout words
        """

        await self.set_words(ctx.guild, *[x for xs in self.default_words.items() for x in xs])
        await ctx.reply(f"Added {len(self.default_words)} default timeout words.")

    @timeoutwords.command(name="del", aliases=["remove", "rem", "delete"])
    async def tw_del(self, ctx, pattern: str):
        """
        Delete a timeout word pattern
        """

        try:
            await self.del_word(ctx.guild, pattern)
        except KeyError:
            await ctx.reply(f"Timeout word `{pattern}` not found.")
        else:
            await ctx.reply(f"Deleted timeout word: `{pattern}`")

    @timeoutwords.command(name="clear")
    async def tw_clear(self, ctx):
        """
        Clear all timeout words in this server
        """
        await self.config.guild(ctx.guild).WORDS.clear()
        self.word_cache.pop(ctx.guild.id, None)
        await ctx.reply("All timeout words have been cleared.")