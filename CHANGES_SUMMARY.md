# Summary of Changes for Automatic Track Removal

This document summarizes the changes made to implement the automatic track removal and reporting feature.

## 1. Core Logic: `bot/helper/video_utils/processor.py`

-   **Function:** `process_video(path, listener)`
-   **Changes:** This function was completely rewritten to be the central point for the automatic logic.
    -   **Language Detection:** It now contains an extensive `lang_map` to recognize various language codes (2-letter, 3-letter) and native script names (e.g., `తెలుగు`, `हिंदी`) from the video's metadata. A helper function `get_lang_code()` was added to perform this detection from stream tags.
    -   **Priority Logic:** It implements the `Telugu -> Hindi -> English` audio track priority. It finds the highest-priority language present in the file and selects all audio tracks of that language. If no priority languages are found, it keeps all audio tracks as a fallback.
    -   **Track Removal:** It builds an `ffmpeg` command that only includes the selected video and audio streams, effectively removing all other audio tracks and all subtitle tracks.
    -   **Result Recording:** After `ffmpeg` runs successfully, it populates the `listener.streams_kept`, `listener.streams_removed`, and `listener.art_streams` lists. This is crucial for reporting the results accurately.
    -   **Logging:** Extensive logging was added to trace the entire decision-making process.

## 2. Orchestration: `bot/helper/listeners/tasks_listener.py`

-   **Function:** `onDownloadComplete()`
-   **Changes:**
    -   **Automatic Trigger:** The logic was changed to automatically trigger `process_video` for any downloaded video file.
    -   **File Splitting:** The condition for splitting large files was fixed to ensure that splitting is correctly performed *after* video processing if the resulting file is still too large.
-   **Function:** `onUploadComplete(name, ...)`
-   **Changes:**
    -   **Race Condition Fix:** The function signature was changed to accept the `name` of the file as a parameter to make it stateless and avoid race conditions in multi-leech scenarios.
    -   **Split File Message:** Logic was added to correctly call the right message formatting function (`format_message` or `format_split_message`) for single vs. split files.

## 3. Message Formatting: `bot/helper/ext_utils/message_formatter.py`

-   **Functions:** `format_message(...)` and `format_split_message(...)`
-   **Changes:** These functions were updated to make the filename in the final status message a clickable markdown link that points to the uploaded file in the chat.

## 4. Supporting Fixes

-   **Uploader Files** (e.g., `telegram_uploader.py`): Updated to support the new `onUploadComplete` signature.
-   **`status_utils.py`**: Fixed a crash when displaying the status of video tasks due to inconsistent variable names.
-   **`media_utils.py` & `processor.py`**: Fixed a circular import bug by moving the `get_metavideo` function.
