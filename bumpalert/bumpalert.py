import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from redbot.core.utils.menus import menu

import asyncio
import random
from datetime import datetime, timedelta


class BumpAlert(commands.Cog):
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )

        self.config.register_member(**{
            "LAST_BUMP_MSG": None,
        })

        self.config.register_guild(**{
            "MEMBERS": {},
            "USERNAMES": {},
            "LEADERBOARD": {},
            "TOTAL_LEADERBOARD": {},
            "WINS_LEADERBOARD": {},
            "POINTS_LEADERBOARD": {},
            "CHANNELS": {},
            "PAUSED": False
        })
    
    async def cog_load(self):
        await self.bot.wait_until_ready()
        leaderboards = await self.config.all_guilds()
        for gid in leaderboards:
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            lb = leaderboards[gid].get("LEADERBOARD", {})
            if not lb:
                continue
            total_lb = leaderboards[gid].get("TOTAL_LEADERBOARD", {})
            if not total_lb:
                total_lb = lb
                await self.config.guild(guild).TOTAL_LEADERBOARD.set(total_lb)

    @commands.Cog.listener()
    async def on_message(self, message):
        if (message.interaction and message.interaction.name) != 'bump':
            return
        
        # channels = await self.config.guild(message.guild).CHANNELS()
        # if str(message.channel.id) not in channels:
        #     return

        secs_till_bump = 2*60*60
        ts = int((datetime.now() + timedelta(seconds=secs_till_bump)).timestamp())

        lb = await self.config.guild(message.guild).LEADERBOARD()
        total_lb = await self.config.guild(message.guild).TOTAL_LEADERBOARD()
        uid = str(message.interaction.user.id)
        lb[uid] = lb.get(uid, 0) + 1
        total_lb[uid] = total_lb.get(uid, 0) + 1

        await self.config.guild(message.guild).LEADERBOARD.set(lb)
        await self.config.guild(message.guild).TOTAL_LEADERBOARD.set(total_lb)

        members = await self.config.guild(message.guild).MEMBERS()
        embed = None 
        lb = await self.config.guild(message.guild).LEADERBOARD()
        if lb:
            embed = discord.Embed(title="Bump Leaderboard", description=(await self.leaderboard_pages(message.guild, lb))[0])
            embed.set_author(name=message.guild.name, icon_url=message.guild.icon.url)
        for smid in members:
            if members[smid] is False:
                continue
            try:
                m = message.guild.get_member(int(smid))
            except:
                continue
            last_notif_id = await self.config.member(m).LAST_BUMP_MSG()
            if last_notif_id:
                oldmsg = await m.fetch_message(last_notif_id)
                try:
                    await oldmsg.edit(content=f'next bump at <t:{ts}:F> (<t:{ts}:R>)',embed=embed)
                except:
                    pass


        # wait
        nt = ts - datetime.now().timestamp()
        await asyncio.sleep(nt)

        # if paused, don't notify
        if await self.config.guild(message.guild).PAUSED():
            return

        members = await self.config.guild(message.guild).MEMBERS()
        member_ids = [smid for smid in members]
        random.shuffle(member_ids)
        for smid in member_ids:
            if members[smid] is False:
                continue
            try:
                m = message.guild.get_member(int(smid))
            except:
                continue
            last_notif_id = await self.config.member(m).LAST_BUMP_MSG()
            if last_notif_id:
                oldmsg = await m.fetch_message(last_notif_id)
                try: 
                    await oldmsg.delete()
                except:
                    pass
            try:
                msg = await m.send(f'bump time in {message.channel.jump_url}')
            except:
                continue
            else:
                await self.config.member(m).LAST_BUMP_MSG.set(msg.id)
    
    @commands.command()
    async def bumpalert(self, ctx):
        cid = str(ctx.channel.id)
        mid = str(ctx.author.id)
        members = await self.config.guild(ctx.guild).MEMBERS()
        usernames = await self.config.guild(ctx.guild).USERNAMES()
        usernames[mid] = ctx.author.name
        members[mid] = not members.get(mid, False)
        await self.config.guild(ctx.guild).MEMBERS.set(members)
        await self.config.guild(ctx.guild).USERNAMES.set(usernames)
        await self.config.guild(ctx.guild).CHANNELS.set_raw(cid, value=True)
        if members[mid]:
            await ctx.reply("You will now be notified when it's time to bump")
        else:
            await ctx.reply("You will no longer be notified when it's time to bump")

    
    @commands.command(aliases=['bumplb'])
    async def bumpleaderboard(self, ctx):
        """Shows a leaderboard of how often people have bumped the server"""
        pages = await self.gather_leaderboard_pages(ctx.guild)
        if pages:
            await menu(ctx, pages)
        else:
            await ctx.reply('No one has bumped yet')
    
    async def gather_leaderboard_pages(self, guild, lb_override=None):
        if lb_override is None:
            lb = await self.config.guild(guild).LEADERBOARD()
        else:
            lb = lb_override
        wins_lb = await self.config.guild(guild).WINS_LEADERBOARD()
        points_lb = await self.config.guild(guild).POINTS_LEADERBOARD()
        total_lb = await self.config.guild(guild).TOTAL_LEADERBOARD()

        pages = await self.leaderboard_pages(guild, lb, "Bumps")
        wins_pages = await self.leaderboard_pages(guild, wins_lb, "Wins")
        points_pages = await self.leaderboard_pages(guild, points_lb, "Points")
        total_pages = await self.leaderboard_pages(guild, total_lb, "Total Bumps")

        pages = [f'### Bump Leaderboard\n{p}' for p in pages]
        wins_pages = [f'### Bumprace Wins Leaderboard\n{p}' for p in wins_pages]
        points_pages = [f'### Bumprace Points Leaderboard\n{p}' for p in points_pages]
        total_pages = [f'### Total Bumps Leaderboard\n{p}' for p in total_pages]
        pages = pages + wins_pages + points_pages + total_pages
        pages = [f'{p} {i+1}/{len(pages)}' for i, p in enumerate(pages)]

        return pages
    
    async def leaderboard_pages(self, guild, data, point_name="Bumps"):
        usernames = await self.config.guild(guild).USERNAMES()
        display_names = {}
        username_changed = False
        for uid in data.keys():
            member = guild.get_member(int(uid))
            if member:
                display_names[uid] = member.display_name
                if usernames.get(uid) != member.name:
                    username_changed = True
                usernames[uid] = member.name
            else:
                display_names[uid] = usernames.get(uid, "Unknown User")

        if username_changed:
            await self.config.guild(guild).USERNAMES.set(usernames)

        lb = sorted(data.items(), key=lambda x: x[1], reverse=True)
        lb = [f'{f"{i+1}.":<4} {x[1]:<11} {display_names[x[0]]}' for i, x in enumerate(lb)]
        pages = ['\n'.join(lb[i:i+10]) for i in range(0, len(lb), 10)]
        pages = [f'```md\n{"#":<4} {point_name:<11} {"Name"}\n{p}\n```\n-# ({i+1}/{len(pages)})' for i, p in enumerate(pages)]
        return pages
    
    def humanize_list(self, items):
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " and " + items[-1]
    
    @commands.command(aliases=['bumpalertpause'])
    @checks.mod_or_permissions(manage_guild=True)
    async def bumpracepause(self, ctx):
        """Pauses the current bumprace"""
        await self.config.guild(ctx.guild).PAUSED.set(True)
        await ctx.reply("Bumprace paused.")
    
    @commands.command(aliases=['bumpalertresume'])
    @checks.mod_or_permissions(manage_guild=True)
    async def bumpraceresume(self, ctx):
        """Resumes the current bumprace"""
        await self.config.guild(ctx.guild).PAUSED.set(False)
        await ctx.reply("Bumprace resumed.")

    @commands.command(aliases=['bumpalertreset'])
    @checks.mod_or_permissions(manage_guild=True)
    async def bumpracereset(self, ctx):
        """Resets the bumprace, tallying wins and starting a new leaderboard"""
        olb = await self.config.guild(ctx.guild).LEADERBOARD()
        wins_lb = await self.config.guild(ctx.guild).WINS_LEADERBOARD()
        points_lb = await self.config.guild(ctx.guild).POINTS_LEADERBOARD()

        usernames = await self.config.guild(ctx.guild).USERNAMES()

        lb = sorted(olb.items(), key=lambda x: x[1], reverse=True)
        rankings = {}
        ranking = 1
        points = {1:3, 2:2, 3:1}
        winners = {}
        for uid, bumps in lb:
            if ranking not in rankings:
                rankings[ranking] = bumps
            elif bumps < rankings[ranking]:
                ranking += 1
                rankings[ranking] = bumps
            if ranking >= 4:
                break
            
            if ranking == 1:
                wins_lb[uid] = wins_lb.get(uid, 0) + 1
                member = ctx.guild.get_member(int(uid))
                if member:
                    winners[uid] = member.mention
                else:
                    winners[uid] = usernames.get(uid, "Unknown User")
            
            points_lb[uid] = points_lb.get(uid, 0) + points.get(ranking, 0)
    
        await self.config.guild(ctx.guild).WINS_LEADERBOARD.set(wins_lb)
        await self.config.guild(ctx.guild).POINTS_LEADERBOARD.set(points_lb)
        await self.config.guild(ctx.guild).LEADERBOARD.set({})
        win_prompt = "The winner is "
        if len(winners) > 1:
            win_prompt = "The winners are "
        await ctx.reply("Bumprace leaderboard reset. " + win_prompt + self.humanize_list([f'**{winners[uid]}**' for uid in winners]) + "!")
        
        pages = await self.gather_leaderboard_pages(ctx.guild, olb)
        if pages:
            await menu(ctx, pages)
        else:
            await ctx.reply('No one has bumped yet')
