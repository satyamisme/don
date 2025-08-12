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

def _select_streams(streams):
    """Selects the best video, preferred audio, all subtitles, and art streams."""
    best_video = None
    art_streams = []
    audio_streams = []
    subtitle_streams = []

    video_candidates = []
    for stream in streams:
        if stream.get('codec_type') == 'video':
            if stream.get('disposition', {}).get('attached_pic'):
                art_streams.append(stream)
            else:
                video_candidates.append(stream)

    if video_candidates:
        best_video = max(video_candidates, key=lambda s: s.get('width', 0) * s.get('height', 0))

    preferred_langs = [lang.strip() for lang in config_dict.get('PREFERRED_LANGUAGES', 'tel,hin,eng').split(',')]
    for stream in streams:
        if stream.get('codec_type') == 'audio':
            if stream.get('tags', {}).get('language') in preferred_langs:
                audio_streams.append(stream)

    for stream in streams:
        if stream.get('codec_type') == 'subtitle':
            subtitle_streams.append(stream)

    return best_video, audio_streams, subtitle_streams, art_streams

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
    """Main function to process the video."""

    listener.original_name = ospath.basename(path)
    media_info = await get_media_info(path)
    if not media_info or 'streams' not in media_info:
        await listener.onUploadError("Could not get media info from the input file.")
        return None

    all_streams = media_info['streams']
    video_stream, audio_streams, subtitle_streams, art_streams = _select_streams(all_streams)

    if not video_stream:
        await listener.onUploadError("No suitable video stream found to process.")
        return None

    cmd = ['ffmpeg', '-i', path]
    streams_to_keep = [video_stream] + audio_streams + subtitle_streams
    for stream in streams_to_keep:
        cmd.extend(['-map', f'0:{stream["index"]}'])

    cmd.extend(['-c', 'copy'])
    cmd.extend(['-avoid_negative_ts', 'make_zero', '-fflags', '+genpts'])
    cmd.extend(['-max_interleave_delta', '0'])

    base_name, _ = path.rsplit('.', 1)
    output_path = f"{base_name}.processed.mkv"
    cmd.extend(['-f', 'matroska', '-y', output_path])

    processed_path = await run_ffmpeg(cmd, path, listener)

    if processed_path:
        final_path = processed_path.replace('.processed.mkv', '.mkv')
        await aiorename(processed_path, final_path)

        listener.streams_kept = streams_to_keep
        listener.art_streams = art_streams

        kept_indices = {s['index'] for s in streams_to_keep}
        listener.streams_removed = [s for s in all_streams if s['index'] not in kept_indices and s not in art_streams]

        return final_path

    return None

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
