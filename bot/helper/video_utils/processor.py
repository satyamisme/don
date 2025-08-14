from bot import config_dict, LOGGER, task_dict_lock, task_dict, bot_loop
from bot.helper.ext_utils.files_utils import get_path_size
from bot.helper.mirror_utils.status_utils.video_status import VideoStatus
import asyncio
import json
from time import time
import os.path as ospath
from aiofiles.os import rename as aiorename

async def get_media_info(path):
    """Get media information using ffprobe."""
    try:
        process = await asyncio.create_subprocess_exec(
            'ffprobe', '-hide_banner', '-loglevel', 'error', '-print_format', 'json',
            '-show_format', '-show_streams', path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            LOGGER.error(f"ffprobe error: {stderr.decode().strip()}")
            return None
        return json.loads(stdout)
    except Exception as e:
        LOGGER.error(f"Exception while getting media info: {e}")
        return None

async def run_ffmpeg(command, path, listener):
    """Run the generated ffmpeg command and report progress."""
    total_size = await get_path_size(path)
    media_info = await get_media_info(path)
    total_duration = float(media_info['format'].get('duration', 1))

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    status = VideoStatus(listener, total_size, listener.mid, process)
    async with task_dict_lock:
        task_dict[listener.mid] = status

    async def _log_stderr():
        async for line in process.stderr:
            LOGGER.info(f"ffmpeg: {line.decode().strip()}")

    stderr_task = bot_loop.create_task(_log_stderr())
    await process.wait()
    stderr_task.cancel()

    if process.returncode == 0:
        LOGGER.info(f"Video processing successful: {command[-1]}")
        return command[-1]
    else:
        LOGGER.error(f"ffmpeg exited with non-zero return code: {process.returncode}")
        await listener.onUploadError(f"ffmpeg exited with non-zero return code: {process.returncode}")
        return None

async def process_video(path, listener):
    """Main function to process the video based on user's final logic."""
    LOGGER.info("Starting video processing for: %s", path)

    if hasattr(listener, 'streams_kept') and listener.streams_kept:
        LOGGER.info("Streams already processed by manual selection, skipping automatic processing.")
        return path

    listener.original_name = ospath.basename(path)
    media_info = await get_media_info(path)
    if not media_info or 'streams' not in media_info:
        await listener.onUploadError("Could not get media info from the input file.")
        return None

    all_streams = media_info['streams']
    LOGGER.info("Found %d streams in the media file.", len(all_streams))

    lang_map = {
        'te': 'tel', 'tel': 'tel', 'telugu': 'tel', 'తెలుగు': 'tel',
        'hi': 'hin', 'hin': 'hin', 'hindi': 'hin', 'हिंदी': 'hin',
        'en': 'eng', 'eng': 'eng', 'english': 'eng', 'ఇంగ్లీష్': 'eng',
        'ta': 'tam', 'tam': 'tam', 'tamil': 'tam', 'தமிழ்': 'tam',
        'ml': 'mal', 'mal': 'mal', 'malayalam': 'mal', 'മലയാളം': 'mal',
        'kn': 'kan', 'kan': 'kan', 'kannada': 'kan', 'ಕನ್ನಡ': 'kan',
        'ur': 'urd', 'urd': 'urd', 'urdu': 'urd', 'اردو': 'urd',
        'bn': 'ben', 'ben': 'ben', 'bengali': 'ben', 'বাংলা': 'ben',
    }

    def get_lang_code(stream):
        tags = stream.get('tags', {})
        lang = tags.get('language', 'und').lower()
        title = tags.get('title', '').lower()

        if lang in lang_map:
            return lang_map[lang]

        for key, value in lang_map.items():
            if key in title:
                LOGGER.info("Found language '%s' from title '%s' for stream %d", value, title, stream.get('index'))
                return value
        return lang

    all_video_streams = [s for s in all_streams if s.get('codec_type') == 'video']
    audio_streams_to_process = [s for s in all_streams if s.get('codec_type') == 'audio']

    art_streams = [s for s in all_video_streams if s.get('disposition', {}).get('attached_pic')]
    main_video_streams = [s for s in all_video_streams if not s.get('disposition', {}).get('attached_pic')]

    lang_string = config_dict.get('PREFERRED_LANGUAGES', 'tel,hin,eng')
    preferred_langs = [lang.strip().strip('"\'') for lang in lang_string.split(',')]
    LOGGER.info("Using language priority: %s", preferred_langs)

    selected_audio = []
    found_preferred = False

    for pref_lang in preferred_langs:
        lang_streams = [s for s in audio_streams_to_process if get_lang_code(s) == pref_lang]
        if lang_streams:
            selected_audio.extend(lang_streams)
            found_preferred = True
            LOGGER.info("Found priority language '%s'. Selecting %d audio stream(s).", pref_lang, len(lang_streams))
            break

    if not found_preferred:
        LOGGER.info("No priority audio language found, keeping all %d audio tracks.", len(audio_streams_to_process))
        selected_audio = audio_streams_to_process

    streams_to_keep_in_ffmpeg = main_video_streams + art_streams + selected_audio
    LOGGER.info("Total streams to keep (before subtitle check): %d", len(streams_to_keep_in_ffmpeg))

    if len(streams_to_keep_in_ffmpeg) == len(all_streams):
         LOGGER.info("No streams to remove, skipping processing.")
         listener.streams_kept = main_video_streams + selected_audio
         listener.streams_removed = [s for s in all_streams if s.get('codec_type') == 'subtitle']
         listener.art_streams = art_streams
         return path

    cmd = ['ffmpeg', '-i', path, '-v', 'error']
    for stream in streams_to_keep_in_ffmpeg:
        cmd.extend(['-map', f'0:{stream["index"]}'])

    cmd.extend(['-c', 'copy', '-avoid_negative_ts', 'make_zero', '-fflags', '+genpts', '-max_interleave_delta', '0'])

    base_name, _ = path.rsplit('.', 1)
    output_path = f"{base_name}.processed.mkv"
    cmd.extend(['-f', 'matroska', '-y', output_path])

    LOGGER.info("Running ffmpeg command: %s", " ".join(cmd))
    processed_path = await run_ffmpeg(cmd, path, listener)

    if processed_path:
        final_path = processed_path.replace('.processed.mkv', '.mkv')
        await aiorename(processed_path, final_path)
        LOGGER.info("Video processing successful. Output: %s", final_path)

        listener.streams_kept = main_video_streams + selected_audio
        listener.art_streams = art_streams

        kept_indices = {s['index'] for s in listener.streams_kept + listener.art_streams}
        listener.streams_removed = [s for s in all_streams if s['index'] not in kept_indices]

        LOGGER.info("Final decision: Kept %d streams, Removed %d streams.", len(listener.streams_kept), len(listener.streams_removed))

        return final_path

    return None

