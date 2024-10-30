from redbot.core.data_manager import cog_data_path

from pathlib import Path


class StatusImage:
    def __init__(self, cog, guild, config, status):
        self.guild = guild
        self.config = config
        self.status = status
        self.cog = cog
        self.path: Path
        self.BASE_PATH = cog_data_path(self.cog) / "status_images"
        if not self.BASE_PATH.exists():
            self.BASE_PATH.mkdir()
    
    @classmethod
    async def new(cls, cog, guild, config, status, attachment=None):
        self = cls(cog, guild, config, status)
        if attachment:
            await self.set(attachment)
        try:
            self.path = await self.config.guild(guild).STATUS_IMAGES.get_raw(status)
        except KeyError:
            self.path = None
        return self

    async def set(self, attachment):
        ext = attachment.filename.split('.')[-1]
        self.path = str(self.BASE_PATH / f"{self.status}.{ext}")
        await attachment.save(self.path)
        await self.config.guild(self.guild).STATUS_IMAGES.set_raw(self.status, value=self.path)

    def __str__(self):
        return self.path
    

async def statuses(config_group):
    try:
        cl = await config_group.CHECKLIST_TEMPLATE()
        alarms = await config_group.ALARMS()
    except AttributeError:
        cl = await config_group.CHECKLIST()
        alarms = await config_group.TRACK_ALARMS()
    
    ret = [{"value": "Joined", "compound": False}]
    ret += [{"value": ci["value"], "compound": False, "type": ci['type']} for k, ci in cl.items()]
    ret += [{"value": alarm, "compound": True, "display": f"{alarm} alarm"} for alarm in alarms]

    return ret