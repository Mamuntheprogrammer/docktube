# YouTube Downloader (GUI only)

For content you own or have permission to download only. No DRM / paywall bypass.

## Run
```
pip install -r requirements.txt
python gui_app.py
```
Windows: double-click `run.bat`.

## How it works
- Paste a **single video URL or a playlist URL** → Check → select videos, quality, MP4/MKV, concurrency → Download.
- Single link downloads one video; playlist link lists all videos for batch download.
- Each video is saved as its own file in `downloads/` — no merging.
- No ffmpeg needed: if a system ffmpeg exists it is used to mux best video+audio, otherwise single-file formats are downloaded (hosts typically cap these at 720p).
- Progress shows per-video % + overall %, speed, size, ETA, done/failed counts. Retry / Cancel supported.
- On every launch the app checks whether **yt-dlp is up to date** (via PyPI popup):
  - First install / missing → it auto-downloads and installs yt-dlp.
  - Outdated → popup offers one-click update.

## Files
- `gui_app.py` — desktop GUI (CustomTkinter)
- `core.py` — analyze / download / history / yt-dlp update check
- `downloads/` — downloaded videos
- `jobs/` — job history (`job.json` per download)
