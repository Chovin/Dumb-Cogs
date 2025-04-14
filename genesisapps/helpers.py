import discord
import itertools
from async_lru import alru_cache


CONTAINS_PRE = r"(?P<word>(^|\W)"
CONTAINS_POST = r"(\W|$))"


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
        return self.mention
    
    def __repr__(self):
        return str(self)


class IterCache(object):
    def __init__(self, iterable):
        self.iterable = iterable
        self.iter = iter(iterable)
        self.done = False
        self.vals = []

    def __iter__(self):
        if self.done:
            return iter(self.vals)
        #chain vals so far & then gen the rest
        return itertools.chain(self.vals, self._gen_iter())

    def _gen_iter(self):
        #gen new vals, appending as it goes
        for new_val in self.iter:
            self.vals.append(new_val)
            yield new_val
        self.done = True


# https://stackoverflow.com/a/19504173
class AsyncAsYouGoCachingIterable:
    def __init__(self, async_iterable):
        self.async_iterable = async_iterable
        self._async_iter = async_iterable.__aiter__()
        self.vals = []
        self.done = False

    def __aiter__(self):
        return _AsyncCachingIterator(self)

class _AsyncCachingIterator:
    def __init__(self, parent):
        self.parent = parent
        self.index = 0

    async def __anext__(self):
        # If we're still walking through the cached values
        if self.index < len(self.parent.vals):
            val = self.parent.vals[self.index]
            self.index += 1
            return val
        
        

        # If iteration is marked as done and nothing left
        if self.parent.done:
            raise StopAsyncIteration

        # Otherwise, try to fetch next item from the underlying iterator
        try:
            val = await self.parent._async_iter.__anext__()
            self.parent.vals.append(val)
            self.index += 1
            return val
        except StopAsyncIteration:
            self.parent.done = True
            raise


@alru_cache(maxsize=128, ttl=1200)
async def forum_cached_archived_threads(forum):
    return AsyncAsYouGoCachingIterable(forum.archived_threads())


async def get_thread(forum, thread_id):
    thread = forum.get_thread(thread_id)
    if thread is None:
        async for t in await forum_cached_archived_threads(forum): 
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
