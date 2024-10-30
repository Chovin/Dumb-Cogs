import discord

# can't inherit from discord.Member cause trying to set id gives an error
# and I didn't want to look into it further
class MissingMember(object):
    def __init__(self, id: int, guild: discord.Guild):
        self.id = id
        self.guild = guild
        self.roles = []
        self.mention = f"<@{self.id}>"
        self.bot = False
    
    def __getattribute__(self, name: str):
        if name != 'roles':
            return object.__getattribute__(self, name)
        member = self.guild.get_member(self.id)
        if member:
            return member.roles
        return []    
    
    def __str__(self):
        return self.mention()


async def get_thread(forum, thread_id):
    thread = forum.get_thread(thread_id)
    if thread is None:
        async for t in forum.archived_threads():
            if t.id == thread_id:
                return t
    return thread


def role_mention(role):
    return str(role) if role.id == role.guild.default_role.id else role.mention


def int_to_emoji(n: int):
    if n < 0:
        raise ValueError("n must be >= 0")
    
    emojis = ["0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣"]
    if n < 10:
        return emojis[n]
    
    s = ""
    while n > 0:
        d = n % 10
        n = n // 10
        s = emojis[d] + s

    return s 
