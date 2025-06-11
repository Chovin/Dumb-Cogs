import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
import asyncio
import copy
from datetime import datetime, timedelta
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.menus import SimpleMenu
from typing import Optional
from discord.ext import tasks



class EveryoneMenu(SimpleMenu):
    async def interaction_check(self, interaction: discord.Interaction):
        return True

    async def start(self, channel: discord.TextChannel, *, user: Optional = None):
        self._fallback_author_to_ctx = True
        if user is not None:
            self.author = user
        self.ctx = channel
        kwargs = await self.get_page(self.current_page)
        self.message = await channel.send(**kwargs)


class Eligibles(commands.Cog):

    DEFAULT_GROUP = {
        "NAME": None,
        "EXEMPT_ROLE_ID": None,
        "ELIGIBLE_ROLES": [],  # and
        "TENURE_DAYS": None,
        "NOTIFY_CHANNEL": None,
        "ELIGIBLE_MEMBERS": {}
    }
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )

        self.config.register_guild(**{
            "GROUPS": {}
        })

        self.update_daily.start()

    async def cog_unload(self):
        self.update_daily.cancel()

    async def eligibility_tick(self, guilds, tick=False):
        for g in guilds:
            groups = await self.config.guild(g).GROUPS()
            for group in groups.values():
                eligibles = self.get_eligible(g.members, group)
                eligible_set = set(str(m.id) for m in eligibles)
                new_els = eligible_set - set(group["ELIGIBLE_MEMBERS"])
                ms = list(filter(None, [g.get_member(int(mid)) for mid in new_els]))
                if ms:
                    channel = g.get_channel(group["NOTIFY_CHANNEL"])
                    await self.display_eligible(channel, ms, group, True)
                    if tick:
                        for m in ms:
                            group["ELIGIBLE_MEMBERS"][str(m.id)] = True
                        await self.config.guild(g).GROUPS.set_raw(group['NAME'], value=group)

    async def display_eligible(self, ctx, eligible, group, new):
        if new:
            eligible = [m for m in eligible if str(m.id) not in group['ELIGIBLE_MEMBERS']]
        pages = [
            f"## {group['NAME']} {'newly ' if new else ''}eligible\n" + 
            "\n".join([f"-# **•** {m.mention} <t:{int(m.joined_at.timestamp())}:R>" for m in eligible[i:i+15]])
            for i in range(0, len(eligible), 15)
        ]
        if not pages:
            pages = [f"## {group['NAME']} {'newly ' if new else ''}eligible\n"]
        await EveryoneMenu(pages=pages, timeout=60*5).start(ctx)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.bot:
            return
        before_ids = set([r.id for r in before.roles])
        after_ids = set([r.id for r in after.roles])
        if before_ids == after_ids:
            return
        
        # no new roles
        new_roles = after_ids - before_ids
        if not new_roles:
            return
        
        groups = await self.config.guild(before.guild).GROUPS()
        for g in groups.values():
            roles = set(g["ELIGIBLE_ROLES"])
            for rid in new_roles:
                if rid in roles:
                    await self.eligibility_tick([before.guild])
                    return

    @tasks.loop(hours=24)
    async def update_daily(self):
        guild_groups = await self.config.all_guilds()
        await self.eligibility_tick([self.bot.get_guild(gid) for gid in guild_groups if self.bot.get_guild(gid)], tick=True)
            
    @commands.group(aliases=['eligibles'])
    async def eligible(self, ctx):
        pass

    @eligible.command(name="list")
    async def eligible_list(self, ctx, name=None, new=True):
        """List the elegible members of an eligibility group. 

        use n or no for [new] to show all eligible members and not just newly eligible ones
        """
        gs = await self.config.guild(ctx.guild).GROUPS()
        if name not in gs:
            await ctx.reply((f"{name} is not an eligibility group. " if name else '')+
                "These are the current groups:\n" + "\n".join(f'**{k}**' for k in gs.keys())
            )
            return
        group = gs[name]
        eligible = self.get_eligible(ctx.guild.members, group)
        await self.display_eligible(ctx, eligible, group, new)
    
    def get_eligible(self, members, group):
        erid = group['EXEMPT_ROLE_ID']
        rids = group["ELIGIBLE_ROLES"]
        treq = timedelta(days=group['TENURE_DAYS'])
        if not members:
            return []
        now = datetime.now(members[0].joined_at.tzinfo)
        ret = []
        for m in members:
            rs = {r.id for r in m.roles}
            if erid in rs:
                continue
            if not (rids[0] is None or set(rids).issubset(rs)):
                continue
            if (m.joined_at + treq) < now:
                ret.append(m)
        return ret

    def eligiblity_group_display(self, guild, group):
        return (
            f"## {group['NAME']}\n"
            "Exempt Role: " + guild.get_role(group['EXEMPT_ROLE_ID']).mention + "\n"
            f"Days Since Join Req: {group['TENURE_DAYS']}\n"
            "Roles must have: " + ', '.join([guild.get_role(r).mention for r in filter(None, group['ELIGIBLE_ROLES'])]) + "\n"
            "Mention in channel: " + guild.get_channel(group['NOTIFY_CHANNEL']).mention
        )
    
    @eligible.command(name="delete", aliases=["del", "rem", "remove"])
    @checks.mod()
    async def eligible_rem(self, ctx, name: str):
        groups = await self.config.guild(ctx.guild).GROUPS()
        if name not in groups:
            await ctx.reply("That group doesn't exist")
            return
        
        del groups[name]
        await self.config.guild(ctx.guild).GROUPS.set(groups)
        await ctx.reply(f"group **{name}** deleted")

    @eligible.command(name="set")
    @checks.mod()
    async def eligible_set(self, ctx, name, exempt_role: discord.Role):

        groups = await self.config.guild(ctx.guild).GROUPS()
        new_group = copy.deepcopy(self.DEFAULT_GROUP)
        new_group['NAME'] = name
        # already existing group
        if name in groups:
            await ctx.send(
                'There is already a group set up with that name:\n' + 
                self.eligiblity_group_display(ctx.guild, groups[name]) + "\n\n"
                "Are you sure you want to change it?: Y/N"
            )
            pred = MessagePredicate.yes_or_no(ctx)
            await self.bot.wait_for("message", check=pred)
            if pred.result is False:
                return
            new_group = groups[name]

        # exempt role
        new_group['EXEMPT_ROLE_ID'] = exempt_role.id
        
        # amount of days needed
        await ctx.send("How many days must a member have been in this server to be eligible? (0 is valid)")
        
        pred = MessagePredicate.valid_float(ctx)
        await self.bot.wait_for("message", check=pred)
        days = max(float(pred.result),0)
        
        new_group['TENURE_DAYS'] = days
        
        new_group['NOTIFY_CHANNEL'] = ctx.channel.id

        # roles needed
        await ctx.send("List the roles separated by commas that your members must have to be eligible ('none' is valid and makes it so no roles are needed)")
        
        pred = MessagePredicate.same_context(ctx)

        def parse_roles(message):
            rss = [rs.strip() for rs in message.content.split(',')]
            if rss[0].lower() == 'none':
                print('none was used')
                return [None]
            ret = []
            for rs in rss:
                if rs.startswith('<@&') and rs.endswith('>'):
                    rs = rs[3:-1]
                if rs.isdigit():
                    role = message.guild.get_role(int(rs))
                else:
                    role = discord.utils.get(message.guild.roles, name=rs)
                if not role:
                    raise NameError(f'{rs} is not a role')
                ret.append(role)
            return ret

        def comb_pred(message):
            if not pred(message):
                return False
            try:
                roles = parse_roles(message)
            except NameError:
                return False
            pred.result = roles
            return True
            
        await self.bot.wait_for("message", check=comb_pred)
        roles = pred.result

        new_group['ELIGIBLE_ROLES'] = [r.id if r else r for r in roles]
        print(new_group['ELIGIBLE_ROLES'])

        # save
        await self.config.guild(ctx.guild).GROUPS.set_raw(name, value=new_group)
        
        await ctx.send("Eligibility group set:\n" + self.eligiblity_group_display(ctx.guild, new_group))

    
