from time import time
from bot import bot_name
from bot.helper.ext_utils.status_utils import get_readable_file_size, get_readable_time
from datetime import datetime

def _format_video_stream(stream):
    """Formats video stream details for display."""
    codec = stream.get('codec_name', 'N/A')
    profile = stream.get('profile', '')
    level = stream.get('level')
    if profile and level:
        level_str = str(level)
        if len(level_str) == 2:
            level_str = f"{level_str[0]}.{level_str[1]}"
        codec = f"{codec} {profile}@{level_str}"
    elif profile:
        codec = f"{codec} {profile}"

    resolution = f"{stream.get('width', 0)}x{stream.get('height', 0)}"

    r_frame_rate = stream.get('r_frame_rate', '0/1')
    try:
        num, den = map(int, r_frame_rate.split('/'))
        fps = f"{num / den:.3f}" if den != 0 else "0.000"
    except:
        fps = "N/A"

    return f"{codec}, {resolution}, {fps} fps"

def _format_audio_stream(stream):
    """Formats audio stream details for display."""
    index = stream.get('index')
    codec = stream.get('codec_name', 'N/A')
    lang = stream.get('tags', {}).get('language', 'und').upper()
    channels = stream.get('channel_layout', 'N/A')
    bitrate = stream.get('bit_rate')
    if bitrate:
        bitrate_kbps = int(bitrate) // 1000
        bitrate_str = f"{bitrate_kbps} kbps"
    else:
        bitrate_str = "N/A"
    return f"{index}. {codec} {lang}, {channels}, {bitrate_str}"

def _format_subtitle_stream(stream):
    """Formats subtitle stream details for display."""
    index = stream.get('index')
    codec = stream.get('codec_name', 'N/A')
    lang = stream.get('tags', {}).get('language', 'und').upper()
    default = "Default" if stream.get('disposition', {}).get('default') else ""
    return f"{index}. {codec} {lang}, {default}".strip(', ')

def _format_art_stream(stream):
    """Formats album art stream details for display."""
    codec = stream.get('codec_name', 'N/A')
    resolution = f"{stream.get('width', 0)}x{stream.get('height', 0)}"
    title = stream.get('tags', {}).get('title', '')
    return f"Art: {codec.upper()}, {resolution}, {title}"

async def format_message(listener, size, link=None, f_link=None):
    """
    Formats the final completion message based on the approved UI.
    """
    msg = []

    # Header
    msg.append("✅ **Processing Complete**")

    # File Info
    new_name = listener.name
    original_name = getattr(listener, 'original_name', None)

    if f_link:
        if original_name and original_name != new_name:
            msg.append(f"📽️ [`{original_name}`]({f_link}) → [`{new_name}`]({f_link})")
        else:
            msg.append(f"📽️ [`{new_name}`]({f_link})")
    else:
        if original_name and original_name != new_name:
            msg.append(f"📽️ `{original_name}` → `{new_name}`")
        else:
            msg.append(f"📽️ `{new_name}`")

    elapsed = get_readable_time(time() - listener.message.date.timestamp())
    date = datetime.now().strftime('%d %b %Y')
    size_str = get_readable_file_size(size)

    msg.append(f"📏 {size_str} | ⏱️ {elapsed} | 📅 {date}")

    streams_kept = getattr(listener, 'streams_kept', [])
    streams_removed = getattr(listener, 'streams_removed', [])
    art_streams = getattr(listener, 'art_streams', [])

    # Streams Kept
    if streams_kept:
        msg.append("**Streams Kept:**")
        video_streams = [s for s in streams_kept if s['codec_type'] == 'video']
        audio_streams = [s for s in streams_kept if s['codec_type'] == 'audio']
        subtitle_streams = [s for s in streams_kept if s['codec_type'] == 'subtitle']

        for stream in video_streams:
            msg.append(f"🎥 `{_format_video_stream(stream)}`")
        for stream in audio_streams:
            msg.append(f"🔊 `{_format_audio_stream(stream)}`")
        for stream in subtitle_streams:
            msg.append(f"📜 `{_format_subtitle_stream(stream)}`")

    # Streams Removed
    if streams_removed:
        msg.append("**Streams Removed:**")
        audio_streams_removed = [s for s in streams_removed if s['codec_type'] == 'audio']
        subtitle_streams_removed = [s for s in streams_removed if s['codec_type'] == 'subtitle']

        for stream in audio_streams_removed:
            msg.append(f"🚫 `{_format_audio_stream(stream)}`")
        for stream in subtitle_streams_removed:
            msg.append(f"🚫 `{_format_subtitle_stream(stream)}`")

    # Album Art
    if art_streams:
        msg.append("**Album Art (Metadata Only):**")
        for stream in art_streams:
            msg.append(f"🖼️ `{_format_art_stream(stream)}`")

    # Footer
    kept_video_count = len([s for s in streams_kept if s['codec_type'] == 'video'])
    kept_audio_count = len([s for s in streams_kept if s['codec_type'] == 'audio'])
    kept_subtitle_count = len([s for s in streams_kept if s['codec_type'] == 'subtitle'])
    total_kept = kept_video_count + kept_audio_count + kept_subtitle_count

    footer = f"📊 **Final:** {total_kept} streams ({kept_video_count}v, {kept_audio_count}a, {kept_subtitle_count}s)"
    if link:
        footer += f" | 🔗 [Download]({link})"

    footer += f" | ⚡ #{'leech' if listener.isLeech else 'mirror'} | 👤 {listener.tag} | 🤖 @{bot_name} | v2.1-debug"
    msg.append(footer)

    return "\n".join(msg)

async def format_split_message(listener, size, files):
    """
    Formats the completion message for split files.
    """
    msg = []

    # Header
    msg.append("✅ **Processing & Splitting Complete**")

    # File Info
    name = listener.name
    total_size = get_readable_file_size(size)
    parts = len(files)

    first_link = list(files.keys())[0] if files else None
    if first_link:
        msg.append(f"**Original Name:** [`{name}`]({first_link})")
    else:
        msg.append(f"**Original Name:** `{name}`")
    msg.append(f"**Total Size:** {total_size}")
    msg.append(f"**Parts:** {parts}")

    # List of parts
    for index, (link, file_name) in enumerate(files.items(), start=1):
        msg.append(f"**Part {index}:** `{file_name}`")
        msg.append(f"🔗 [Download Part {index}]({link})")

    # Footer
    footer = f"⚡ #{'leech' if listener.isLeech else 'mirror'} | 👤 {listener.tag} | 🤖 @{bot_name}"
    msg.append(footer)

    return "\n".join(msg)
