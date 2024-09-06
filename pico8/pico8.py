import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config


class Pico8(commands.Cog):
    """
    Creates pictures and gifs out of PICO-8 code
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
