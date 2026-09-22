# Playlist → Single Video Downloader

For content you own or have permission to download only. No DRM / paywall bypass.

## Run
```
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

Windows: double-click `run.bat`.

## How it works
- Paste playlist URL → Analyze → select videos, quality, MP4/MKV, concurrency → Download + Merge.
- Progress shows per-video % + overall %, speed, size, ETA, done/failed counts. Failing videos don't stop others; Retry / Re-merge / Cancel supported.
- Merge uses FFmpeg concat `-c copy` (no re-encode), falls back to libx264+aac if codecs differ.
- Jobs persist in `jobs/<id>/job.json` so refresh/resume works. Final files in `downloads/`.

## Tech
Flask + yt-dlp + imageio-ffmpeg (bundled FFmpeg binary) + ThreadPoolExecutor workers + vanilla JS frontend with dark/light theme.
