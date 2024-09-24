import discord
from discord.ext.commands.errors import MissingRequiredArgument

from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from redbot.core.data_manager import cog_data_path, bundled_data_path

import os
import platform
import asyncio
from datetime import datetime
import shutil
import re
import numpy as np
from PIL import Image
from io import StringIO


P8_FILE_NAME = "p8"

DEFAULT_GIF_LENGTH = 5

GFX_REGEX = re.compile(r'^(--|//)[ \t]*\[gfx\](?P<width>[\dabcdef]{2})(?P<height>[\dabcdef]{2})(?P<gfx>[\dabcdef]*)\[/gfx\]', re.MULTILINE)

flag_pattern = r'^(--|//)'
FLAGS = ['palt', 'wait', 'size', 'flip', 'rec']
crop_pattern = r'[ \t]*crop[ \t]*=?[ \t]*(?P<cropx>\d+),(?P<cropy>\d+)(,(?P<cropw>-?\d+))?(,(?P<croph>-?\d+))?'
flag_pattern += '(' + ('|'.join([fr'[ \t]*{f}[ \t]*=?[ \t]*(?P<{f}>[\d.]+)' for f in FLAGS])) + '|' + crop_pattern + ')+'
FLAGS_REGEX = re.compile(flag_pattern, re.MULTILINE)

# TODO: fix code + gif_length combining w/out newlines w/out ```lua

PALETTE = {
    0: (0, 0, 0),
    1: (29, 43, 83),
    2: (126, 37, 83),
    3: (0, 135, 81),
    4: (171, 82, 54),
    5: (95, 87, 79),
    6: (194, 195, 199),
    7: (255, 241, 232),
    8: (255, 0, 77),
    9: (255, 163, 0),
    10: (255, 236, 39),
    11: (0, 228, 54),
    12: (41, 173, 255),
    13: (131, 118, 156),
    14: (255, 119, 168),
    15: (255, 204, 170),
    128: (41, 24, 20),
    129: (17, 29, 53),
    130: (66, 33, 54),
    131: (18, 83, 89),
    132: (116, 47, 41),
    133: (73, 51, 59),
    134: (162, 136, 121),
    135: (243, 239, 125),
    136: (190, 18, 80),
    137: (255, 108, 36),
    138: (168, 231, 46),
    139: (0, 181, 67),
    140: (6, 90, 181),
    141: (117, 70, 101),
    142: (255, 110, 89),
    143: (255, 157, 129),
}


class PICO8TookTooLong(Exception):
  pass

class PICO8Error(Exception):
  pass

class RudimentaryParam:
    def __init__(self, name):
        self.name = name

class OutputBuffer:
    def __init__(self):
        self._s = StringIO()
    
    def read(self) -> str:
        self._s.seek(0)
        return self._s.read()
    
    def write(self, s: str) -> int:
        return self._s.write(s)
    
    def overwrite(self, s: str) -> int:
        self._s.close()
        self._s = StringIO()
        self.write(s)

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
        data_path = cog_data_path(self)
        self.PICO8_FOLDER = data_path / "put_pico8_folder_here"
        if not os.path.exists(self.PICO8_FOLDER):
            os.mkdir(self.PICO8_FOLDER)
        # user to copy/scp pico-8 into this location
        self.ROOT_PICO8_PATH = self.PICO8_FOLDER / "pico-8"

        self.TEMP_FOLDER = data_path / ".temp"
        self.CONFIG_FOLDER = data_path / ".pico8_root"
        self.CONFIG_FILE = self.CONFIG_FOLDER / "config.txt"
        self.CARTS_FOLDER = data_path / ".carts"

        if os.path.exists(self.TEMP_FOLDER):
            shutil.rmtree(self.TEMP_FOLDER)

        paths = [self.PICO8_FOLDER, self.TEMP_FOLDER, self.CONFIG_FOLDER, self.CARTS_FOLDER]
        for p in paths:
            if not os.path.exists(p):
                os.mkdir(p)

        bundle_path = bundled_data_path(self)
        self.TEST_GIF_PATH = bundle_path / "test_gif.txt"

        P8_FOLDER = bundle_path / "p8"
        self.INITIALIZER_P8 = P8_FOLDER / "initial.p8"
        self.templates = {
            n: read_file(P8_FOLDER / f"{n}.p8")
            for n in ['gif', 'pic']
        }

        self.foldern = 0
        self.ready = False


    async def cog_load(self):
        await self.setup_pico8()
        self.ready = True

    async def cog_unload(self):
        shutil.rmtree(self.TEMP_FOLDER)

    async def setup_pico8(self):
        if not os.path.exists(self.CONFIG_FILE):
            await self.runpico(self.INITIALIZER_P8, .5, 10, out_buffer=OutputBuffer())
            await asyncio.sleep(5)

    # I think this came from danny's repl cog
    def cleanup_code(self, content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith(('```','`​`​`')) and content.endswith(('```','`​`​`')):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        for p in ['`', '']:
            if content.startswith(p):
                if p == '`':
                    return content.strip('` \n')
                content = content[len(p):]
                return content.strip(' \n')

    def _parse_code(self, code):
        gfx_found = re.search(GFX_REGEX, code)
        flags_found = re.search(FLAGS_REGEX, code)

        setup = ''
        has_init = 'function _init' in code.lower()
        has_draw = 'function _draw' in code.lower()
        if has_init or has_draw:
            setup = code
            if has_init:
                setup += f"""
                __init=_init;_init=nil
                __init()
                """
                code = ''
            if has_draw:
                setup += f"""
                __draw=_draw;_draw=nil
                """
                code = '__draw()'
        elif '--draw' in code.lower():
            setup, code = code.split('--draw')
        
        if gfx_found:
            width = int(gfx_found.group('width'), 16)
            height = int(gfx_found.group('height'), 16)
            gfx = gfx_found.group('gfx')
            gfx_inject = f"""
            gfx = "{gfx}"
            i = 1
            for y=0,{height - 1} do
                for x=8,{width - 1 + 8} do
                    sset(x,y,tonum("0x"..sub(gfx,i,i)))
                    i += 1
                end
            end;x=nil;y=nil;i=nil;gfx=nil
            cstore()
            """
            setup = gfx_inject + setup
        options = {}
        if flags_found:
            flags = flags_found.groupdict()
            for k in [*flags.keys()]:
                if flags[k] is None:
                    del flags[k]
            palt = flags.get('palt')
            wait = flags.get('wait')
            size = flags.get('size')
            flip = flags.get('flip', 1)
            rec = flags.get('rec', 1)
            cropx = flags.get('cropx')
            cropy = flags.get('cropy')
            cropw = flags.get('cropw', -int(cropx or 0))
            croph = flags.get('croph', -int(cropy or 0))
            options = {
                'palt': PALETTE.get(int(palt),None) if palt else None,
                'wait': float(wait) if wait else None,
                'size': int(size) if size else 2,
                'flip': bool(int(flip)),
                'rec': bool(int(rec))
            }
            options['crop'] = cropx and [int(i) * options['size'] for i in [cropx, cropy, cropw, croph]]

        return [setup.strip(), code.strip(), options]

    async def add_crop(self, fn, crop_coords, pic=False):
        x,y,w,h = crop_coords
        if pic:
            img = Image.open(fn)
            if w >= 0:
                w += x
            else:
                w = img.width + w
            if h >= 0:
                h += y
            else:
                h = img.height + h
            cropped = img.crop((x, y, w, h))
            cropped.save(fn, format='png')
        else:
            p = await asyncio.create_subprocess_shell(
                f'gifsicle --colors=33 --crop={x},{y}+{w}x{h} {fn} > {fn}.temp'
            )
            stdout, stderr = await p.communicate()
            if stderr:
                print(stderr.decode())
            os.rename(f'{fn}.temp', fn)

    async def add_transparency(self, fn, color_tuple, pic=False):
        r,g,b = color_tuple
        if pic:
            img = Image.open(fn)
            img = img.convert('RGBA')
            data = np.array(img)
            red, green, blue, alpha = data.T
            blacks = (red==r)&(blue==b)&(green==g)
            data[blacks.T] = (0,0,0,0)
            im2=Image.fromarray(data)
            im2.save(fn, format='png')
        else:
            p = await asyncio.create_subprocess_shell(
                f'gifsicle --colors=33 {fn} -w | gifsicle -U --disposal=previous -t="{r},{g},{b}" -O3 > {fn}.temp'
            )
            stdout, stderr = await p.communicate()
            if stderr:
                print(stderr.decode())
            os.rename(f'{fn}.temp', fn)

    async def output_from_process(self, p, dest, err=False):
        buffer = p.stdout
        if err:
            buffer = p.stderr
        line = await buffer.readline()
        d = line.decode()
        dest.append(d)

    async def runpico(self, fn, length, timeout, scale=None, desktop_folder=None, *, out_buffer):
        fn = str(fn)
        desktop_folder = desktop_folder or self.TEMP_FOLDER
        pico8_path = self.ROOT_PICO8_PATH / await self.config.PICO8_PATH()
        cmd = (f'{pico8_path} -x -gif_len 120 '
            f'-home {self.CONFIG_FOLDER} '
            f'-root_path {self.CARTS_FOLDER} '
            f'-desktop {desktop_folder} '
        )
        if scale:
            cmd += f'-screenshot_scale {scale} -gif_scale {scale} '
        cmd += fn
        p = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # why sleep?
        # for some reason not sleeping raises a PICO8TookTooLong
        await asyncio.sleep(length)

        start = datetime.now()
        error_time = None
        out = []
        # err = []
        while True:
            task = asyncio.Task(self.output_from_process(p, out))
            task2 = asyncio.Task(self.output_from_process(p, out, True))
            done, pending = await asyncio.wait([task, task2], timeout=1)
            if pending:
                while pending:
                    pending.pop().cancel()
            if p.returncode is not None:
                outp, errp = await p.communicate()
                out.append(outp.decode())
                out.append(errp.decode())
                break
            now = datetime.now()
            if error_time and (now - error_time).total_seconds() > 1:
                p.terminate()
                output = ''.join(out[1:])
                out_buffer.write(output)
                raise PICO8Error(output)
            if ('error' in ''.join(out[1:])) and not error_time:
                error_time = now
            if (now - start).total_seconds() > timeout:
                p.terminate()
                output = ''.join(out[1:])
                out_buffer.write(output)
                if error_time:
                    raise PICO8Error(output)
                raise PICO8TookTooLong
        
        output = ''.join(out[1:])
        out_buffer.write(output)
    
    async def record(self, ctx, folder, draw_code, length, setup_code="", gif=True, options={}, second_try=False, *, out_buffer):
        # fill in code
        mode = 'gif' if gif else 'pic'
        t = self.templates[mode]
        wait = options.get('wait') or 0
        code = t.format(
            draw_code=draw_code, 
            length=length + 1 + wait,
            wait=wait + 1, 
            setup_code=setup_code,
            do_flip=options.get('flip', 1) and 'true' or 'false',
            do_record=options.get('rec', 1) and 'true' or 'false'
        )

        # save code
        p8file = folder / f"{P8_FILE_NAME}.p8"  
        with open(p8file , 'w') as f:
            f.write(code)
        
        wait = options.get('wait') or 0

        timeout = length*2 + wait*2
        
        # run pico8
        await self.runpico(
            p8file, length + 1 + wait, timeout + 1, 
            scale=options.get('size'), 
            desktop_folder=folder,
            out_buffer=out_buffer
        )
        output = out_buffer.read()
        
        ext = 'gif' if gif else 'png'
        fn = folder / f"{P8_FILE_NAME}.{ext}"

        # collect file
        try:
            os.rename(folder / f"{P8_FILE_NAME}_0.{ext}", fn)
        except FileNotFoundError:
            if output:
                raise PICO8Error(f'Unable to save {mode}. Likely due to the following:\n{output}')
            elif second_try:
                raise PICO8Error(f'Unable to save {mode}. It could be a runtime error? /shrug')
            else:
                await ctx.send('Whoops! I misplaced the gif. Sorry, gotta start again!')
                return await self.record(ctx, folder, draw_code, length, setup_code, gif, options=options, second_try=True, out_buffer=out_buffer)

        os.remove(p8file)

        return fn
    
    async def _pico_record_cmd(self, ctx, code_or_gif_length, code, pic=False):
        if not self.ready:
            await ctx.send('Still setting up PICO8. Please wait.')
            return
        
        # get gif length and code
        try:
            gif_length = abs(float(code_or_gif_length))
        except:
            gif_length = DEFAULT_GIF_LENGTH
            if code:
                if code_or_gif_length.startswith('`'):
                    code = '\n'.join([code_or_gif_length, code])
                else:
                    code = code_or_gif_length + code
            else:
                code = code_or_gif_length
        
        if not code:
            raise MissingRequiredArgument(RudimentaryParam('code'))
        
        # parse code
        code = self.cleanup_code(code.strip())
        setup, code, options = self._parse_code(code)

        # prep temp folder
        temp_folder = self.TEMP_FOLDER / str(self.foldern)
        if not os.path.exists(temp_folder):
            os.mkdir(temp_folder)
        self.foldern += 1

        # run pico8
        msg = await ctx.send('Running PICO8! Wait a moment~')
        out = OutputBuffer()
        try:
            fn = await self.record(
                ctx, temp_folder, code, gif_length, setup, 
                gif=not pic, options=options, out_buffer=out
            )
        except PICO8TookTooLong as e:
            await msg.delete()
            output = out.read()
            if output:
                await ctx.send(f'```lua\n{output}```')
            raise e
        except PICO8Error as e:
            return await ctx.send(f'```lua\n{e}```')

        
        output = out.read()
        content = f'```lua\n{output}```' if output else None

        if options.get('crop'):
            await self.add_crop(fn, options['crop'], pic)

        if options.get('palt'):
            await self.add_transparency(fn, options['palt'], pic)
        
        ext = 'png' if pic else 'gif'

        await msg.delete()
        await ctx.send(
            file=discord.File(fn, filename=f"{ctx.author.display_name}'s snippet.{ext}"),
            content=content
        )

        shutil.rmtree(temp_folder)
 

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

        await ctx.send("Setting up PICO-8...")
        
        await self.setup_pico8()

        await ctx.send("PICO-8 has been registered with this cog\nsending test gif...")

        await self._pico_record_cmd(ctx, 1, read_file(self.TEST_GIF_PATH))

    @commands.command(pass_context=True, aliases=['p8pic', 'pico8pic'])
    async def picopic(self, ctx, code_or_gif_length, *, code):
        """Posts a pic of your code run on PICO8.
        
        Your code will be placed in a loop for pic_length seconds (default 5), after which a screenshot will be taken.
        To provide setup code, separate your setup code from your draw code with a "--draw" line. Draw code goes below.

        Alternatively, you can provide _init and _draw functions, although _update is not supported

        Copy/paste sprites into your code snippet as a single comment
        to use them in the code (pasted sprites start at sprite 1)
        
        A single comment of --palt=<color> will set that color as transparent in the png

        See more comment flag options with [p]help picogif
        
        Note: Your code and the recording starts after 1 second to get rid of the loading cart icon

        Example:
            !picopic 2 `cls(time())`

            !picopic cls(time())

            !picopic 10 `​`​`lua
            t = 0 
            --draw
            t += 1
            cls(t)
            `​`​`
        """
        await self._pico_record_cmd(ctx, code_or_gif_length, code, True)

    @commands.command(pass_context=True, aliases=['p8gif', 'pico8gif'])
    async def picogif(self, ctx, code_or_gif_length, *, code):
        """Posts a gif of your code run on PICO8.
        
        Your code will be placed in a loop for gif_length seconds (default 5).
        To provide setup code, separate your setup code from your draw code with a "--draw" line. Draw code goes below.

        Alternatively, you can provide _init and _draw functions, although _update is not supported

        Copy/paste sprites into your code snippet in a comment
        to use them in the code (pasted sprites start at sprite 1)


        Other comment flags available are:
            --palt=<color>    sets that color as transparent in the gif
            --wait=<seconds>  runs your code for awhile before recording
            --size=<scale>    sets the gif scale. default: 2 (256x256)
            --flip=0          you're in charge of the graphics buffer
            --rec=0           you're in charge of the recording
            --crop=<l>,<t>[,<w>][,<h>]

        The "--crop" crops off (l)eft/(t)op pico8 pixels. When width/height aren't given, crop is mirrored on bottom and right. When width or height are negative, that amount of pixels is taken off the bottom and right.

        Note: Your code and the recording starts after 1 second to get rid of the loading cart icon

        Example:
            !picogif 2 `cls(time())`

            !picogif cls(time())

            !picogif 10 `​`​`lua
            t = 0 
            --draw
            t += 1
            cls(t)
            `​`​`

        """
        await self._pico_record_cmd(ctx, code_or_gif_length, code)


def read_file(fn):
    with open(fn) as f:
        return f.read()