# processor.py - Auto Track Removal with Language Priority & Native Script Support
# Compatible with: executor.py, tasks_listener.py, extra_selector.py

from __future__ import annotations
from ast import literal_eval
from asyncio import Event, wait_for, wrap_future, gather
from functools import partial
from pyrogram.filters import regex, user
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.types import CallbackQuery
from time import time
from bot import VID_MODE
from bot.helper.ext_utils.bot_utils import new_thread
from bot.helper.ext_utils.status_utils import get_readable_file_size, get_readable_time
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import sendMessage, editMessage, deleteMessage
from bot.helper.video_utils import executor as exc

class ExtraSelect:
    def __init__(self, executor: exc.VidEcxecutor):
        self._listener = executor.listener
        self._time = time()
        self._reply = None
        self.executor = executor
        self.event = Event()
        self.is_cancel = False
        self.extension: list[str] = [None, None, 'mkv']
        self.status = ''
        self.executor.streams_kept = []
        self.executor.streams_removed = []

    async def auto_select(self, streams):
        from bot import config_dict

        # ISO 639-1 → 639-2 mapping
        ISO_LANG_MAP = {
            'en': 'eng', 'hi': 'hin', 'te': 'tel', 'ta': 'tam', 'es': 'spa',
            'fr': 'fra', 'de': 'deu', 'ja': 'jpn', 'ko': 'kor', 'zh': 'zho',
            'ar': 'ara', 'ru': 'rus', 'pt': 'por', 'it': 'ita', 'nl': 'nld',
            'sv': 'swe', 'pl': 'pol', 'tr': 'tur', 'el': 'ell', 'th': 'tha'
        }

        # Native script names → ISO 639-2
        NATIVE_LANG_MAP = {
            'తెలుగు': 'tel', 'తెలుగు': 'tel',
            'హిందీ': 'hin', 'हिंदी': 'hin', 'हिन्दी': 'hin',
            'ఇంగ్లీష్': 'eng', 'इंग्लिश': 'eng', 'English': 'eng',
            'தமிழ்': 'tam', 'മലയാളം': 'mal', 'ಕನ್ನಡ': 'kan',
            'اردو': 'urd', 'বাংলা': 'ben'
        }

        # Priority order
        PRIORITY_LANGS = ['tel', 'hin', 'eng']

        # Auto-parse PREFERRED_LANGUAGES or fallback
        raw_preferred = config_dict.get('PREFERRED_LANGUAGES', 'te,hi,en')
        if not raw_preferred.strip():
            raw_preferred = 'te,hi,en'

        # Normalize to 3-letter codes
        preferred_langs = [
            ISO_LANG_MAP.get(lang.strip().lower(), lang.strip().lower())
            for lang in raw_preferred.split(',') if lang.strip()
        ]
        PRIORITY_LANGS = [ISO_LANG_MAP.get(lang, lang) for lang in preferred_langs]

        if not self.executor.data:
            self.executor.data = {'stream': {}}

        streams_to_remove = []
        audio_streams = {}
        other_streams = []

        # Process each stream
        for stream in streams:
            index = stream.get('index')
            codec_type = stream.get('codec_type')
            lang_tag = stream.get('tags', {}).get('language', 'und').lower()

            # Normalize ISO code
            lang = ISO_LANG_MAP.get(lang_tag, lang_tag)

            # If still 'und', check native script in title/comment
            if lang == 'und':
                title = stream.get('tags', {}).get('title', '').strip()
                comment = stream.get('tags', {}).get('comment', '').strip()
                full_text = f"{title} {comment}".lower()

                for native_name, iso_code in NATIVE_LANG_MAP.items():
                    if native_name in full_text or native_name.lower() in full_text:
                        lang = iso_code
                        break

            stream['tags']['language'] = lang.lower()
            self.executor.data['stream'][index] = {
                'map': index, 'type': codec_type, 'lang': lang.lower()
            }

            if codec_type == 'audio':
                audio_streams[index] = stream
            else:
                other_streams.append(stream)

        # === Priority Logic ===
        selected_lang = None
        for lang in PRIORITY_LANGS:
            if any(s['tags']['language'] == lang for s in audio_streams.values()):
                selected_lang = lang
                break

        if selected_lang:
            for index, stream in audio_streams.items():
                if stream['tags']['language'] == selected_lang:
                    self.executor.streams_kept.append(stream)
                else:
                    streams_to_remove.append(index)
                    self.executor.streams_removed.append(stream)
        else:
            # No priority language → keep all audio
            self.executor.streams_kept.extend(audio_streams.values())

        # Always keep video and subtitles
        self.executor.streams_kept.extend(other_streams)

        # Finalize
        self.executor.data['sdata'] = streams_to_remove
        self.event.set()

    @new_thread
    async def _event_handler(self):
        pfunc = partial(cb_extra, obj=self)
        handler = self._listener.client.add_handler(
            CallbackQueryHandler(pfunc, filters=regex('^extra') & user(self._listener.user_id)),
            group=-1
        )
        try:
            await wait_for(self.event.wait(), timeout=180)
        except:
            pass
        finally:
            self._listener.client.remove_handler(*handler)

    async def update_message(self, text: str, buttons):
        if not self._reply:
            self._reply = await sendMessage(text, self._listener.message, buttons)
        else:
            await editMessage(text, self._reply, buttons)

    def streams_select(self, streams: dict = None):
        buttons = ButtonMaker()
        if not self.executor.data:
            self.executor.data.setdefault('stream', {})
            self.executor.data['sdata'] = []
            for stream in streams:
                index = stream.get('index')
                codec_type = stream.get('codec_type')
                lang = stream.get('tags', {}).get('language', 'und').lower()
                if codec_type not in ['video', 'audio', 'subtitle']:
                    continue
                self.executor.data['stream'][index] = {
                    'info': f'{codec_type.title()} ~ {lang.upper()}',
                    'map': index,
                    'type': codec_type,
                    'lang': lang
                }
                if codec_type == 'audio':
                    self.executor.data['is_audio'] = True
                elif codec_type == 'subtitle':
                    self.executor.data['is_sub'] = True

        mode = self.executor.mode
        ddict = self.executor.data

        for key, value in ddict['stream'].items():
            if mode == 'extract':
                buttons.button_data(value['info'], f'extra {mode} {key}')
            else:
                if value['type'] != 'video':
                    buttons.button_data(value['info'], f'extra {mode} {key}')

        text = (f'<b>STREAM REMOVE SETTINGS ~ {self._listener.tag}</b>\n'
                f'<code>{self.executor.name}</code>\n'
                f'File Size: <b>{get_readable_file_size(self.executor.size)}</b>\n')

        if sdata := ddict.get('sdata'):
            text += 'Stream will be removed:\n'
            for i, sindex in enumerate(sdata, 1):
                info = ddict['stream'][sindex]['info']
                text += f"{i}. {info.replace('✅ ', '')}\n"

        text += 'Select available stream below!\n'
        text += f'<i>Time Out: {get_readable_time(180 - (time()-self._time))}</i>'

        if mode == 'extract':
            buttons.button_data('Extract All', f'extra {mode} video audio subtitle')
            buttons.button_data('ALT Mode', f"extra {mode} alt {ddict.get('alt_mode', False)}", 'footer')
            for ext in self.extension:
                buttons.button_data(ext.upper(), f'extra {mode} extension {ext}', 'header')
        else:
            buttons.button_data('Reset', f'extra {mode} reset', 'header')
            buttons.button_data('Reverse', f'extra {mode} reverse', 'header')
            buttons.button_data('Continue', f'extra {mode} continue', 'footer')
            if ddict.get('is_audio'):
                buttons.button_data('All Audio', f'extra {mode} audio')
            if ddict.get('is_sub'):
                buttons.button_data('All Subs', f'extra {mode} subtitle')

        buttons.button_data('Cancel', 'extra cancel', 'footer')
        return text, buttons.build_menu(2)

    async def rmstream_select(self, streams: dict):
        if not self.executor.data:
            await self.auto_select(streams)
        await self.update_message(*self.streams_select(streams))

    async def get_buttons(self, *args):
        if not self.executor.data:
            future = self._event_handler()
            if extra_mode := getattr(self, f'{self.executor.mode}_select', None):
                await extra_mode(*args)
            await wrap_future(future)
        else:
            self.event.set()

        await deleteMessage(self._reply)
        if self.is_cancel:
            self._listener.suproc = 'cancelled'
            await self._listener.onUploadError(f'{VID_MODE[self.executor.mode]} stopped by user!')


# === Required by tasks_listener.py ===
# DO NOT REMOVE — this function is imported in tasks_listener.py
async def process_video(path: str, listener):
    """
    Entry point for video processing.
    Called from tasks_listener.py when vidMode and isLeech.
    """
    from bot.helper.video_utils.executor import VidEcxecutor
    executor = VidEcxecutor(listener, path, listener.gid(), metadata=False)
    return await executor.execute()
