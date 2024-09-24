import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from redbot.core.data_manager import cog_data_path, bundled_data_path

import os
import platform


class Pico8(commands.Cog):
    """
    Creates pictures and gifs out of PICO-8 code

    PICO-8 is a fantasy console (an emulator for a console that doesn't exist). It's a [delightful tool](https://youtu.be/K5RXMuH54iw) for making games and prototypes.

    You can get PICO-8 yourself [here](https://www.lexaloffle.com/pico-8.php) or 
    play around with the education version [in your browser](https://www.pico-8-edu.com/) (but you can't copy paste sprites directly from the education version)
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=100406911567949824,
            force_registration=True,
        )
        self.config.register_global(
            PICO8_PATH = None
        )
        self.PICO8_FOLDER = cog_data_path(self) / "put_pico8_folder_here"
        if not os.path.exists(self.PICO8_FOLDER):
            os.mkdir(self.PICO8_FOLDER)
        self.TEMP_FOLDER = cog_data_path(self) / "temp"
        self.ROOT_PICO8_PATH = self.PICO8_FOLDER / "pico-8"


    @checks.is_owner()
    @commands.command()
    async def pico8install(self, ctx: commands.Context):
        """Explains steps to install what's needed to get this cog working"""

        if ctx.guild != None:
            await ctx.send("Please use this command in a private message")
            return
        
        system = platform.system()
        gifsicle_instructions = {
            "Linux":   "\t1. `sudo apt-get install gifsicle` or whatever package installer you use for your flavor of linux",
            "Mac":    ("\t1. install [Homebrew](https://brew.sh/) if you haven't already\n"
                       "\t2. `brew install gifsicle`"),
            "Windows":("\t1. install the appropriate binary for your machine [here](https://eternallybored.org/misc/gifsicle/)\n"
                       "\t2. ensure it's in/reachable from your [PATH](https://stackoverflow.com/a/44272417)")

        }[system]
        
        path = cog_data_path(self)
        msg = (
            "This cog requires 2 things to be installed somewhere reachable by the bot:\n"
            "1. PICO-8\n"
            "\t1. Buy and download PICO-8 from [here](<https://www.lexaloffle.com/pico-8.php>) "
                      "Make sure you download the version for the platform the bot is running on!\n"
            f"\t2. Unzip pico-8 into `{self.PICO8_FOLDER}` on the compuater your bot is running on (put the entire folder in)\n"
            "2. gifsicle\n"
            f"{gifsicle_instructions}\n\n"
            "Once you've installed those two, "
            "ensure Red can reach these new tools by turning off Red, "
            "closing the terminal/session, "
            "then reopening the terminal/session and starting Red again\n\n"
            "Finally, **rerun this command** to register the PICO-8 path"
        )

        await ctx.send(msg)
        

        if not os.path.exists(self.ROOT_PICO8_PATH):
            return 
        
        exe_postfix = {
            "Linux": "pico8",
            "Darwin": "PICO-8.app/Contents/MacOS/pico8",
            "Windows": "pico8.exe"
        }[system]

        if not os.path.exists(self.ROOT_PICO8_PATH / exe_postfix):
            await ctx.send("I can't find your pico-8 executable. Are you sure you downloaded pico-8 for the right platform?")
        await self.config.PICO8_PATH.set(exe_postfix)


        await ctx.send("PICO-8 has been registered with this cog\nsending test gif...")

        JELPI = ("[gfx]2808"
            "00000000000000000f000f000f000f0000000000"
            "0f000f000f000f000ffffff00ffffff00f000f00"
            "0ffffff00ffffff00f1fff100f1fff100ffffff0"
            "0f1fff100f1fff100effffe00effffe00f1fff10"
            "0effffe00effffe000222000002220000effffe0"
            "002220000022200000888f000f88800000222000"
            "0088800000888f000f00000000000f000f888000"
            "00f0f00000f0000000000000000000000000f000"
        "[/gfx]")

        await self._pico_record_cmd(ctx, 1, """
            --{JELPI}
            --palt=0
            --crop=0,0,8,8
            cls()
            spr(1+flr(time()*2*5)%5)
        """)
