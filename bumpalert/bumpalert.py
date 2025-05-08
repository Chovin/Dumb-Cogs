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
            "LEADERBOARD": {},
            "CHANNELS": {}
        })

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
        uid = str(message.interaction.user.id)
        lb[uid] = lb.get(uid, 0) + 1
        
        await self.config.guild(message.guild).LEADERBOARD.set(lb)

        members = await self.config.guild(message.guild).MEMBERS()
        embed = None 
        lb = await self.config.guild(message.guild).LEADERBOARD()
        if lb:
            embed = discord.Embed(title="Bump Leaderboard", description=self.leaderboard_pages(message.guild, lb)[0])
            embed.set_author(name=message.guild.name, icon_url=message.guild.icon.url)
        for smid in members:
            if members[smid] is False:
                continue
            m = message.guild.get_member(int(smid))
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

        members = await self.config.guild(message.guild).MEMBERS()
        member_ids = [smid for smid in members]
        random.shuffle(member_ids)
        for smid in member_ids:
            if members[smid] is False:
                continue
            m = message.guild.get_member(int(smid))
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
        members[mid] = not members.get(mid, False)
        await self.config.guild(ctx.guild).MEMBERS.set(members)
        await self.config.guild(ctx.guild).CHANNELS.set_raw(cid, value=True)
        if members[mid]:
            await ctx.reply("You will now be notified when it's time to bump")
        else:
            await ctx.reply("You will no longer be notified when it's time to bump")

    
    @commands.command(aliases=['bumplb'])
    async def bumpleaderboard(self, ctx):
        """Shows a leaderboard of how often people have bumped the server"""
        lb = await self.config.guild(ctx.guild).LEADERBOARD()
        pages = self.leaderboard_pages(ctx.guild, lb)
        if pages:
            await menu(ctx, [f'### Bump Leaderboard\n{p}' for p in pages])
        else:
            await ctx.reply('No one has bumped yet')
    
    def leaderboard_pages(self, guild, data):
        lb = sorted(data.items(), key=lambda x: x[1], reverse=True)
        lb = [f'{f"{i+1}.":<4} {x[1]:<11} {guild.get_member(int(x[0])).display_name}' for i, x in enumerate(lb)]
        pages = ['\n'.join(lb[i:i+10]) for i in range(0, len(lb), 10)]
        pages = [f'```md\n{"#":<4} {"Bumps":<11} {"Name"}\n{p}\n```\n-# {i+1}/{len(pages)}' for i, p in enumerate(pages)]
        return pages