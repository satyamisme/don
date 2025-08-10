from time import time
from bot.helper.ext_utils.status_utils import MirrorStatus, get_readable_file_size, get_readable_time

from os.path import basename

class VideoStatus:
    def __init__(self, listener, size, gid, process, file_name):
        self._listener = listener
        self._size = size
        self._gid = gid
        self._process = process
        self._start_time = time()
        self._processed_bytes = 0
        self._name = file_name

    def gid(self):
        return self._gid

    def progress_raw(self):
        return self._processed_bytes / self._size * 100 if self._size > 0 else 0

    def progress(self):
        return f'{round(self.progress_raw(), 2)}%'

    def speed_raw(self):
        elapsed_time = time() - self._start_time
        return self._processed_bytes / elapsed_time if elapsed_time > 0 else 0

    def speed(self):
        return f'{get_readable_file_size(self.speed_raw())}/s'

    def name(self):
        return self._name

    def size(self):
        return get_readable_file_size(self._size)

    def eta(self):
        try:
            speed = self.speed_raw()
            if speed > 0:
                seconds = (self._size - self._processed_bytes) / speed
                return get_readable_time(seconds)
            else:
                return '0s'
        except:
            return '0s'

    def status(self):
        return MirrorStatus.STATUS_PROCESSING

    def processed_bytes(self):
        return get_readable_file_size(self._processed_bytes)

    def task(self):
        return self._process

    def update_progress(self, processed_bytes):
        self._processed_bytes = processed_bytes
