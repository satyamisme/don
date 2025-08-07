from bot.helper.ext_utils.bot_utils import EngineStatus
from bot.helper.ext_utils.status_utils import get_readable_file_size, get_readable_time, speed_raw, speed_string_nav


class VideoStatus(EngineStatus):
    def __init__(self, listener, size, gid, process):
        super().__init__(listener, size, gid, process, 'VID')
        self.size = size
        self.gid = gid
        self.process = process
        self.listener = listener
        self._obj = listener
        self._size = size
        self.message = listener.message
        self.start_time = listener.start_time
        self.extra_details = {}

    def speed(self):
        return speed_string_nav(self.processed_bytes(), self.start_time)

    def speed_raw(self):
        return speed_raw(self.processed_bytes(), self.start_time)

    def name(self):
        return self.listener.name

    def progress_raw(self):
        try:
            return self.processed_bytes() / self.size * 100
        except:
            return 0

    def progress(self):
        return f'{round(self.progress_raw(), 2)}%'

    def eta(self):
        try:
            seconds = (self.size - self.processed_bytes()) / self.speed_raw()
            return get_readable_time(seconds)
        except:
            return '0s'

    def processed_bytes(self):
        return self.extra_details.get('processed_bytes', 0)

    def status(self):
        return "Processing Video"

    def engine(self):
        return 'FFMPEG'

    def task(self):
        return self

    def cmd(self):
        return self.extra_details.get('cmd')

    async def update(self):
        self.extra_details.update({
            'size': get_readable_file_size(self._size),
            'status': self.status(),
            'name': self.name(),
            'gid': self.gid,
            'progress': self.progress(),
            'speed': self.speed(),
            'eta': self.eta(),
            'engine': self.engine(),
            'task': self,
        })
        return self.extra_details

    def llistener(self):
        return self.listener

    def get_gid(self):
        return self.gid

    def get_process(self):
        return self.process
