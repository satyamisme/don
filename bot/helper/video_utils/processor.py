"""
This module contains the new video processing logic.
"""

from bot import config_dict, LOGGER, task_dict_lock, task_dict, bot_loop
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.files_utils import get_path_size, clean_target
from bot.helper.mirror_utils.status_utils.video_status import VideoStatus
import asyncio
import json
from time import time
import os.path as ospath

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

def build_ffmpeg_command(input_file, output_file):
    """Build the ffmpeg command with language-based mapping and safety flags."""

    preferred_langs = [lang.strip() for lang in config_dict.get('PREFERRED_LANGUAGES', 'tel,hin,eng').split(',')]

    cmd = ['ffmpeg', '-i', input_file]

    cmd.extend(['-map', '0:v', '-map', '0:s?', '-map', '0:d?'])
    for lang in preferred_langs:
        cmd.extend(['-map', f'0:a?(language:{lang})'])

    cmd.extend(['-c', 'copy'])
    cmd.extend(['-avoid_negative_ts', 'make_zero', '-fflags', '+genpts'])
    cmd.extend(['-max_interleave_delta', '0'])

    cmd.extend(['-f', 'matroska', '-y', output_file])

    return cmd

async def run_ffmpeg(command, path, listener):
    """Run the generated ffmpeg command and report progress."""
    total_size = await get_path_size(path)

    media_info = await get_media_info(path)
    if not media_info or 'format' not in media_info or 'duration' not in media_info['format']:
        total_duration = 1
    else:
        total_duration = float(media_info['format']['duration'])

    process = await asyncio.create_subprocess_exec(
        *command,
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

    async def _log_stderr():
        async for line in process.stderr:
            LOGGER.info(f"ffmpeg: {line.decode().strip()}")

    stderr_task = bot_loop.create_task(_log_stderr())

    await process.wait()

    parser_task.cancel()
    stderr_task.cancel()

    if process.returncode == 0:
        LOGGER.info(f"Video processing successful: {command[-1]}")
        return command[-1]
    else:
        LOGGER.error(f"ffmpeg exited with non-zero return code: {process.returncode}")
        await listener.onUploadError(f"ffmpeg exited with non-zero return code: {process.returncode}")
        return None

async def process_video(path, listener):
    """Main function to process the video."""

    listener.original_name = ospath.basename(path)
    original_media_info = await get_media_info(path)
    if not original_media_info:
        await listener.onUploadError("Could not get media info from the input file.")
        return None

    base_name, _ = path.rsplit('.', 1)
    output_path = f"{base_name}.mkv"

    command = build_ffmpeg_command(path, output_path)

    processed_path = await run_ffmpeg(command, path, listener)

    if processed_path:
        processed_media_info = await get_media_info(processed_path)
        if not processed_media_info:
            await listener.onUploadError("Could not get media info from the processed file.")
            listener.streams_kept = []
            listener.streams_removed = []
            listener.art_streams = []
        else:
            original_streams = original_media_info.get('streams', [])
            kept_streams = processed_media_info.get('streams', [])

            kept_indices = {s['index'] for s in kept_streams}

            listener.streams_kept = kept_streams
            listener.streams_removed = [s for s in original_streams if s['index'] not in kept_indices]

            listener.art_streams = [s for s in kept_streams if s.get('disposition', {}).get('attached_pic')]
            listener.streams_kept = [s for s in kept_streams if not s.get('disposition', {}).get('attached_pic')]

        await clean_target(path)

    return processed_path

async def get_metavideo(url):
    """Get media metadata from a URL using ffprobe."""
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
