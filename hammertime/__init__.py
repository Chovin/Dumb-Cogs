from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement_or_raise

from .hammertime import HammerTime

__red_end_user_data_statement__ = get_end_user_data_statement_or_raise(__file__)


async def setup(bot: Red) -> None:
    await bot.add_cog(HammerTime(bot))
