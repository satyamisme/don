"""
This module contains the new video processing logic.
"""

from bot import config_dict, LOGGER, task_dict_lock, task_dict, bot_loop
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.files_utils import get_path_size
from bot.helper.ext_utils.status_utils import get_readable_file_size, get_readable_time
from bot.helper.telegram_helper.message_utils import sendStatusMessage, update_status_message
from bot.helper.mirror_utils.status_utils.video_status import VideoStatus

import asyncio
import subprocess
import json
from time import time

async def get_media_info(path):
    """
    Get media information using ffprobe.
    """
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

async def select_streams(media_info):
    """
    Select streams based on configuration.
    """
    video_stream = None
    audio_streams = []
    subtitle_streams = []

    # Select best video stream
    for stream in media_info.get('streams', []):
        if stream.get('codec_type') == 'video':
            if video_stream is None or stream.get('height', 0) > video_stream.get('height', 0):
                video_stream = stream

    # Select audio and subtitle streams based on preferred and excluded languages
    preferred_langs = [lang.strip() for lang in config_dict.get('PREFERRED_LANGUAGES', 'en').split(',')]
    excluded_langs = [lang.strip() for lang in config_dict.get('EXCLUDED_LANGUAGES', '').split(',')]

    # Audio stream selection
    for stream in media_info.get('streams', []):
        if stream.get('codec_type') == 'audio':
            lang = stream.get('tags', {}).get('language')
            if lang in preferred_langs and lang not in excluded_langs:
                audio_streams.append(stream)

    # Subtitle stream selection
    for stream in media_info.get('streams', []):
        if stream.get('codec_type') == 'subtitle':
            lang = stream.get('tags', {}).get('language')
            if lang in preferred_langs and lang not in excluded_langs:
                subtitle_streams.append(stream)

    return video_stream, audio_streams, subtitle_streams

async def run_ffmpeg(path, output_path, video_stream, audio_streams, subtitle_streams, listener, media_info):
    """
    Run ffmpeg with the selected streams and report progress.
    """
    total_size = await get_path_size(path)
    total_duration = float(media_info['format']['duration'])

    cmd = ['ffmpeg', '-progress', '-', '-i', path, '-map', f'0:{video_stream["index"]}', '-c:v', 'copy']

    for stream in audio_streams:
        cmd.extend(['-map', f'0:{stream["index"]}', '-c:a', 'copy'])

    for stream in subtitle_streams:
        cmd.extend(['-map', f'0:{stream["index"]}', '-c:s', 'copy'])

    cmd.extend(['-y', output_path])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    status = VideoStatus(listener, total_size, listener.mid, process)
    async with task_dict_lock:
        task_dict[listener.mid] = status

    async def _parser():
        async for line in process.stdout:
            line = line.decode('utf-8').strip()
            if 'out_time_ms=' in line:
                time_in_ms = int(line.split('=')[1])
                processed_bytes = (time_in_ms / (total_duration * 1000000)) * total_size
                status.update_progress(processed_bytes)

    parser_task = bot_loop.create_task(_parser())

    await process.wait()
    parser_task.cancel()

    if process.returncode == 0:
        LOGGER.info(f"Video processing successful: {output_path}")
        return output_path
    else:
        stderr_output = await process.stderr.read()
        LOGGER.error(f"ffmpeg error: {stderr_output.decode().strip()}")
        await listener.onUploadError(f"ffmpeg error: {stderr_output.decode().strip()}")
        return None


async def process_video(path, listener):
    """
    Main function to process the video.
    """
    media_info = await get_media_info(path)
    if not media_info:
        return None

    video_stream, audio_streams, subtitle_streams = await select_streams(media_info)

    if not video_stream:
        LOGGER.info("No video stream found. Skipping video processing.")
        return path

    output_path = f"{path.rsplit('.', 1)[0]}.processed.mp4"
    processed_path = await run_ffmpeg(path, output_path, video_stream, audio_streams, subtitle_streams, listener, media_info)

    if processed_path:
        listener.streams_kept = [video_stream] + audio_streams + subtitle_streams
        original_streams = media_info.get('streams', [])
        listener.streams_removed = [s for s in original_streams if s not in listener.streams_kept]

    return processed_path

async def get_metavideo(url):
    """
    Get media metadata from a URL using ffprobe.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            'ffprobe', '-hide_banner', '-loglevel', 'error', '-print_format', 'json',
            '-show_format', url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            LOGGER.error(f"ffprobe error for URL {url}: {stderr.decode().strip()}")
            return None, None

        media_info = json.loads(stdout)
        duration = media_info.get('format', {}).get('duration', 0)
        size = media_info.get('format', {}).get('size', 0)

        return duration, {'size': size}
    except Exception as e:
        LOGGER.error(f"Exception while getting media metadata for URL {url}: {e}")
        return None, None
