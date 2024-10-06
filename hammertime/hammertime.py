import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config

from discord.ui import View, Select

from collections import defaultdict
import pytz
from datetime import datetime, timedelta
import functools
import dateutil.parser
from dateutil.tz import gettz
from dateutil.parser import ParserError
import re


RE_RELATIVE_TIME = re.compile(r"(?P<amt>\d+|an?) ?(?P<period>(y(ea)?rs?)|(months?)|(weeks?)|(days?)|(h(ou)?rs?)|(min(ute)?s?)|(sec(ond)?s?))(?P<past> ago)?")
RE_AT_IN = re.compile(r"(\s|^)(at|in)\s\d")
RE_AT = re.compile(r"(\s|^)(at\s(?P<time>\d{1,2}:?\d{0,2})\s?(?P<ampm>am|pm)?(\W|$))")
TIMEOUT = "TIMEOUT"


class TimeZoneSelectView(View):
    def __init__(self, interact_member: discord.Member, time_zones):
        super().__init__(timeout=10)
        self.interact_member = interact_member
        self.time_zones = time_zones
        self.value = TIMEOUT

        for i in range(0, len(time_zones), 24):
            zones = time_zones[i:i + 24]
            options = [discord.SelectOption(label=tz, value=tz) for tz in zones]
            if i + 24 >= len(time_zones):
                options.append(discord.SelectOption(label="My timezone is not listed / Remove my timezone", value='None'))
            select = Select(
                placeholder="Select your timezone",
                min_values=1, max_values=1,
                options=options
            )
            select.callback = functools.partial(self.select_callback, select)
    
            self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction):
        return interaction.user.id == self.interact_member.id

    async def stop(self, response=None):
        for item in self.children:
            item.disabled = True

        for child in self.children:
            if child.values:
                self.value = child.values[0]
                if self.value == 'None':
                    self.value = None

        await ((response and response.edit_message) or self.message.edit)(view=self)
        super().stop()

    async def select_callback(self, select: discord.ui.Select, interaction: discord.Interaction):
        await self.stop(interaction.response)
        
    async def on_timeout(self):
        await self.stop()


class TimeZoneMapKey(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        argument = argument.lower()
        try:
            argument = int(argument.replace(':', '').replace('gmt', '').replace('utc', ''))
        except:
            pass
        return argument


class UserOrStringConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        try:
            return await commands.MemberConverter().convert(ctx, argument)
        except:
            return argument


def th(n):
    if 4 <= n%100 <= 20:
        return 'th'
    else:
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n%10, 'th')


def strftimeth(dt, fmt):
    return dt.strftime(fmt.format(th=th(dt.day)))


def parse_datetime(txt: str, tz_str: str):
    txt = txt.lower().strip()

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)
    
    txt = txt.replace('today', today.strftime('%Y-%m-%d'))
    txt = txt.replace('tomorrow', tomorrow.strftime('%Y-%m-%d'))
    txt = txt.replace('yesterday', yesterday.strftime('%Y-%m-%d'))

    tz = gettz(tz_str)
    tz_str = "ZONE"
    return dateutil.parser.parse(f"{txt} {tz_str}", fuzzy=True, tzinfos={tz_str: tz})


def parse_delta(txt: str, tz_str: str):
    txt = txt.lower().strip()

    tz = gettz(tz_str)

    if txt == 'now':
        return datetime.now(tz)

    if not re.search(RE_RELATIVE_TIME, txt):
        raise ParserError
    
    now = datetime.now(tz)
    for m in re.finditer(RE_RELATIVE_TIME, txt):

        amt = m.group('amt')
        period = m.group('period')
        past = m.group('past')
        try:
            amt = int(amt)
        except ValueError:
            amt = 1

        periods = {
            p[0]: p for p in
            ["years", "months", "weeks", "days", "hours", "minutes", "seconds"]
        }
        period = periods[period[0]]

        if past == ' ago':
            amt *= -1

        now += timedelta(**{period: amt})

    return now


class AmbiguousTimeZoneError(Exception):
    pass


class NoTimeZoneError(Exception):
    pass


class HammerTime(commands.Cog):
    """
    A tool for generating "hammertime" discord timestamps, 
    timestamps that show the correct time for every user that sees them

    Each user needs to set up their own timezone using `[p]hammertimeset tz <timezone_or_location>`,
    or you could also set timezone roles using `[p]hammertimeset role <role> <timezone_or_location>`

    Check out the tool that inspired this cog: https://hammertime.cyou/
    """
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )

        self.config.register_user(**{
            "TIMEZONE": None
        })

        self.config.register_role(**{
            "TIMEZONE": None
        })

        self.config.register_guild(**{
            "AUTO_TIME": False,
        })

        self.tz_map = self.make_timezone_map()


    def make_timezone_map(self):
        # https://stackoverflow.com/a/36068039
        tz_map = defaultdict(set)

        for name in pytz.all_timezones:
            tzone = pytz.timezone(name)
            
            for utcoffset, dstoffset, tzabbrev in getattr(
                    tzone, '_transition_info', 
                    [[None, None, datetime.now(tzone).tzname()]]
            ):
                tzabbrev = tzabbrev.lower()
                try:
                    tzabbrev = int(tzabbrev)
                except:
                    pass
                tz_map[tzabbrev].add(name)
            try:
                places = name.lower().split('/')
            except:
                pass
            else:
                for place in places[1:]:
                    tz_map[place].add(name)
            tz_map[name.lower()].add(name)

        return {k: sorted(v) for k, v in tz_map.items()}
        

    async def prompt_timezone_choice(self, ctx, tz_map_key):
        possibilities = self.tz_map.get(tz_map_key)
        if not possibilities:
            raise ValueError("Not a valid timezone")
        if len(possibilities) == 1:
            return possibilities[0]
        else:
            view = TimeZoneSelectView(ctx.author, possibilities)
            view.message = await ctx.send(view=view)
            await view.wait()
            return view.value
        

    async def get_timezone_for(self, user: discord.User):
        tz = await self.config.user(user).TIMEZONE()
        if tz is None:
            found = 0
            for role_id, conf in (await self.config.all_roles()).items():
                if user.get_role(role_id):
                    tz = conf['TIMEZONE']
                    found += 1
                if found > 1:
                    raise AmbiguousTimeZoneError
            if found == 0:
                raise NoTimeZoneError
        return tz


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
        
        if not await self.config.guild(message.guild).AUTO_TIME():
            return

        ps = await self.bot.get_prefix(message)
        if message.content.startswith(
            tuple(f"{p}{cmd}" for p in ps 
                for cmd in ['hammertime', 'ht']
            )
        ):
            return
        
        try:
            tz_str = await self.get_timezone_for(message.author)
        except (AmbiguousTimeZoneError, NoTimeZoneError):
            return

        content = message.content.lower()

        if not re.search(RE_AT_IN, content):
            return
        
        try:
            dt = parse_delta(content, tz_str)
        except ParserError:
            found = 0
            for m in re.finditer(RE_AT, content):
                found += 1
                if found > 1:
                    return
            if not m.group("ampm"):
                tz = gettz(tz_str)
                now = datetime.now(tz)
                hour = m.group("time")
                time = hour
                if ':' in hour:
                    hour = hour.split(':')[0]
                hour = int(hour)
                ampm = "pm"
                if hour <= 12:
                    ampm = now.strftime("%p")
                    if hour < int(now.strftime("%I")):
                        ampm = {"am": "pm", "pm": "am"}[ampm.lower()]
                
                content = content.replace(time, f"{time} {ampm}")
                print(content)

            try:
                dt = parse_datetime(content, tz_str)
            except ParserError:
                return
        
        ts = int(dt.timestamp())
        await message.reply(f"-# <t:{ts}:F> (<t:{ts}:R>)", mention_author=False)



    
    @commands.command(aliases=["ht"])
    async def hammertime(self, ctx, user_or_time: UserOrStringConverter = None, *, time = 'now'):
        """Use this command followed by a date/time phrase to convert it to hammertime! 
        (a discord time format that shows correctly for everyone that sees it)

        Put a person's name or mention before the time phrase to see what the time would be relative to them.
        
        Example usage:
        
        `[p]ht 1 hour ago`
        `[p]ht in 1 day and 12 hrs`
        `[p]ht irdumb Saturday at 6:30pm`
        """

        user = ctx.author

        if isinstance(user_or_time, str):
            time = f"{user_or_time} {time}"
        elif user_or_time is not None:
            user = user_or_time
            
        pre = "You have" if user == ctx.author else f"{user.mention} has"
        try:
            tz = await self.get_timezone_for(user)
        except NoTimeZoneError:
            await ctx.send(f"{pre} no timezone set. Use `{ctx.prefix}hammertimeset tz <timezone>` to set your timezone.")
            return 
        except AmbiguousTimeZoneError:
            await ctx.send(f"{pre} multiple timezone roles. Use `{ctx.prefix}hammertimeset tz <timezone>` to set your timezone.")
            return

        try:
            dt = parse_delta(time, tz)
        except ParserError:
            try:
                dt = parse_datetime(time, tz)
            except ParserError:
                await ctx.send("I couldn't understand that")
        
        ts = int(dt.timestamp())
        users_time = strftimeth(dt, "%A, %b %-d{th} at %-I:%M %p")
        await ctx.send(
            f"**Hammertime!**\n"
            f"{user.mention}'s **{users_time}** is your\n"
            f"-# `<t:{ts}:d>`: <t:{ts}:d>\n"
            f"-# `<t:{ts}:D>`: <t:{ts}:D>\n"
            f"-# `<t:{ts}:t>`: <t:{ts}:t>\n"
            f"-# `<t:{ts}:T>`: <t:{ts}:T>\n"
            f"-# `<t:{ts}:f>`: <t:{ts}:f>\n"
            f"-# `<t:{ts}:F>`: <t:{ts}:F>\n"
            f"-# `<t:{ts}:R>`: <t:{ts}:R>\n"
            f"-# Not correct? make sure your timezone is set with `{ctx.prefix}hammertimeset tz <timezone>`\n"
        )

    @commands.group()
    async def hammertimeset(self, ctx):
        """Commands to set hammertime timezone and settings"""

    @hammertimeset.command(aliases=["tz"])
    async def timezone(self, ctx, *, tz_or_location: TimeZoneMapKey):
        """Set your timezone.
        
        If you want to unset your timezone, enter a timezone, then choose the last option
        """
        try:
            choice = await self.prompt_timezone_choice(ctx, tz_or_location)
        except ValueError:
            await ctx.reply("That is not a valid timezone.")
            return

        if choice == TIMEOUT:
            await ctx.reply("Took too long.")
            return
        if choice is None:
            await self.config.user(ctx.author).TIMEZONE.clear()
            await ctx.reply("Your timezone has been unset.")
        else:
            await self.config.user(ctx.author).TIMEZONE.set(choice)
            await ctx.reply(f"Your timezone is now {choice}.")

    
    @checks.admin_or_permissions(manage_roles=True)
    @hammertimeset.command()
    async def role(self, ctx, role: discord.Role,*, tz: TimeZoneMapKey):
        """Set the timezone of a role. Everyone with this role we'll assume is in this timezone
        Except for those who manually set their timezone."""
        try:
            choice = await self.prompt_timezone_choice(ctx, tz)
        except ValueError:
            await ctx.reply("That is not a valid timezone.")
            return
        
        if choice == TIMEOUT:
            await ctx.reply("Took too long.")
            return
        if choice is None:
            await self.config.role(role).TIMEZONE.clear()
            await ctx.reply(f"The role **{role.name}**'s timezone has been unset.")
        else:
            await self.config.role(role).TIMEZONE.set(choice)
            await ctx.reply(f"The role **{role.name}**'s timezone is now {choice}.",)

    
    @commands.admin()
    @hammertimeset.command()
    async def auto(self, ctx, toggle: bool = None):
        """Toggle automatically converting times in messages if they have the word at/in in them"""
        current = await self.config.guild(ctx.guild).AUTO_TIME()
        if toggle is None:
            toggle = not current
        await self.config.guild(ctx.guild).AUTO_TIME.set(toggle)
        if toggle:
            await ctx.reply("Time auto-converting is now on.")
        else:
            await ctx.reply("Time auto-converting is now off.")

