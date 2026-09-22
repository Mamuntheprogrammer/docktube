"""Core: analyze + download single videos or playlists (no merging).

Each selected video is downloaded as its own file into downloads/.
No bundled ffmpeg: if a system ffmpeg is found it is used to mux
best video+audio, otherwise single-file (progressive) formats are
downloaded which need no ffmpeg at all.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yt_dlp

BASE = Path(__file__).parent
# User data (settings, default downloads) must live next to the .exe when
# frozen: in one-file builds __file__ points inside a temp extraction dir
# that vanishes on exit.
try:
    DATA_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else BASE
except Exception:
    DATA_DIR = BASE
JOBS_DIR = BASE / "jobs"
SETTINGS_FILE = DATA_DIR / "settings.json"

# No history / no cache: jobs live in memory only, nothing is written
# to jobs/ (no job.json cache files).
PERSIST_JOBS = False


def _load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


_settings = _load_settings()
try:
    _dd = str((_settings.get("download_dir") or "")).strip()
    DL_DIR = Path(_dd) if _dd else DATA_DIR / "downloads"
except Exception:
    DL_DIR = DATA_DIR / "downloads"
try:
    DL_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DL_DIR = DATA_DIR / "downloads"
    try:
        DL_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def get_download_dir():
    """Current download folder (default: ./downloads)."""
    return str(DL_DIR)


def set_download_dir(path):
    """Change the download folder (created if needed) and remember it.

    Returns (ok, message). Only affects new downloads.
    """
    global DL_DIR, _settings
    try:
        p = Path(str(path or "").strip().strip('"')).expanduser()
        if not str(p):
            return False, "empty folder"
        p.mkdir(parents=True, exist_ok=True)
        if not p.is_dir():
            return False, "not a folder"
        DL_DIR = p
        _settings["download_dir"] = str(p)
        _save_settings(_settings)
        return True, str(p)
    except Exception as e:
        return False, str(e)[:200]

# System ffmpeg if the user has one installed (used for muxing
# best video+audio). Resolved below by resolve_ffmpeg(): saved portable
# copy -> folder next to the exe -> PATH -> imageio-ffmpeg package.
# None -> progressive single-file preferred, split streams as fallback.
FFMPEG = None

_lock = threading.Lock()
_jobs = {}

# Separate video+audio (needs ffmpeg to mux into one file).
# NOTE: trailing "/bv*+ba/b" is intentional — "b"/"best" alone means a
# single progressive (video+audio) file, which most modern YouTube videos
# don't have at all, so a bare ".../b" selector raises
# "Requested format is not available". Ending with bv*+ba guarantees a match.
QUALITY_MAP = {
    "best": "bv*+ba/b",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
    "720p": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
    "480p": "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b",
    "360p": "bv*[height<=360]+ba/b[height<=360]/bv*+ba/b",
}

# Single-file (progressive) preferred — downloadable with no ffmpeg.
# Hosts typically cap progressive at 360p-720p, and many videos have NO
# progressive format at all. The trailing "bv*+ba" fallback lets yt-dlp
# still download video+audio (as separate files without ffmpeg to mux them)
# instead of erroring with "Requested format is not available".
NOFMPEG_QUALITY_MAP = {
    "best": "best[ext=mp4]/best/bv*+ba/b",
    "1080p": "best[height<=1080][ext=mp4]/best[height<=1080]/best[ext=mp4]/best/bv*[height<=1080]+ba/bv*+ba/b",
    "720p": "best[height<=720][ext=mp4]/best[height<=720]/best[ext=mp4]/best/bv*[height<=720]+ba/bv*+ba/b",
    "480p": "best[height<=480][ext=mp4]/best[height<=480]/best[ext=mp4]/best/bv*[height<=480]+ba/bv*+ba/b",
    "360p": "best[height<=360][ext=mp4]/best[height<=360]/best[ext=mp4]/best/bv*[height<=360]+ba/bv*+ba/b",
}

# Last-resort selector: matches virtually any YouTube video.
FALLBACK_FORMAT = "bv*+ba/b"


def _frozen_dir():
    """Folder containing the frozen .exe (None when running from Python)."""
    try:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
    except Exception:
        pass
    return None


def _writable_bin_dir():
    """Where to store a downloaded portable ffmpeg.exe."""
    cands = []
    fd = _frozen_dir()
    if fd is not None:
        cands.append(fd / "bin")
    try:
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        cands.append(Path(local) / ("YtDownloader" if fd is not None else ".ytdownloader") / "bin")
    except Exception:
        pass
    cands.append(DATA_DIR / "bin")
    for d in cands:
        try:
            d.mkdir(parents=True, exist_ok=True)
            if d.is_dir():
                return d
        except Exception:
            continue
    return None


def resolve_ffmpeg():
    """(re)detect a usable ffmpeg binary. Order:

    1. previously downloaded portable copy (settings.json -> ffmpeg_path)
    2. ffmpeg.exe shipped next to the frozen .exe (no install needed)
    3. system PATH (a manual ffmpeg install)
    4. imageio-ffmpeg's bundled binary (pip package, dev machines)

    Returns path or None.
    """
    try:
        saved = str((_settings.get("ffmpeg_path") or "")).strip()
        if saved and os.path.exists(saved):
            return saved
    except Exception:
        pass
    try:
        fd = _frozen_dir()
        if fd is not None:
            for cand in (fd / "ffmpeg.exe", fd / "bin" / "ffmpeg.exe",
                         fd / "ffmpeg", fd / "bin" / "ffmpeg"):
                if cand.is_file():
                    return str(cand)
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None


def refresh_ffmpeg():
    """Re-run ffmpeg detection (call after an install)."""
    global FFMPEG
    FFMPEG = resolve_ffmpeg()
    return FFMPEG


# First resolution at import (helpers above must stay above this line).
FFMPEG = resolve_ffmpeg()


def _download_portable_ffmpeg(timeout=600):
    """Download a portable ffmpeg without needing pip/Python.

    Used by frozen .exe builds: fetches the imageio-ffmpeg wheel for
    Windows from PyPI with stdlib urllib, extracts just ffmpeg.exe
    (~25 MB) into a writable bin folder and remembers it in settings.
    Returns (ok, message_or_path).
    """
    import urllib.request
    import zipfile
    if os.name != "nt":
        return (False, "auto-download supports Windows only — "
                "install ffmpeg with your package manager "
                "(e.g. `brew install ffmpeg` / `sudo apt install ffmpeg`)")
    bindir = _writable_bin_dir()
    if bindir is None:
        return False, "no writable folder for ffmpeg"
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/imageio-ffmpeg/json",
            headers={"User-Agent": "ytdlp-gui/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        urls = (data.get("urls") or [])
        wheel_url = None
        for u in urls:
            fn = str(u.get("filename") or "")
            if fn.endswith("win_amd64.whl"):
                wheel_url = u.get("url")
                break
        if not wheel_url:
            return False, "no Windows build found on PyPI"
        tmp_zip = bindir / "_ffmpeg_dl.zip"
        wreq = urllib.request.Request(wheel_url, headers={"User-Agent": "ytdlp-gui/1.0"})
        with urllib.request.urlopen(wreq, timeout=timeout) as r, open(tmp_zip, "wb") as f:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
        extracted = None
        with zipfile.ZipFile(tmp_zip) as z:
            for name in z.namelist():
                if name.startswith("imageio_ffmpeg/binaries/ffmpeg-win") and name.endswith(".exe"):
                    z.extract(name, bindir)
                    extracted = bindir / name
                    break
        try:
            tmp_zip.unlink()
        except OSError:
            pass
        if not extracted or not extracted.is_file():
            return False, "ffmpeg.exe not found inside downloaded package"
        dest = bindir / "ffmpeg.exe"
        try:
            if dest != extracted:
                if dest.exists():
                    dest.unlink()
                extracted.replace(dest)
        except OSError:
            dest = extracted
        global _settings
        _settings["ffmpeg_path"] = str(dest)
        _save_settings(_settings)
        refresh_ffmpeg()
        return True, str(dest)
    except Exception as e:
        return False, f"download failed: {str(e)[:200]}"


def ensure_ffmpeg_via_imageio(timeout=300):
    """Provide ffmpeg, with or without Python/pip.

    1. Return immediately if any ffmpeg is already detectable.
    2. Try `pip install imageio-ffmpeg` (dev machines; skipped in .exe).
    3. Fall back to a direct portable download (works in frozen .exe
       with no Python installed — needs internet once, ~25 MB).

    Returns (ok, message_or_path). Never needs admin rights.
    """
    if resolve_ffmpeg():
        refresh_ffmpeg()
        return True, FFMPEG
    if not getattr(sys, "frozen", False):
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "imageio-ffmpeg"],
                capture_output=True, text=True, timeout=timeout)
            path = resolve_ffmpeg()
            if path:
                refresh_ffmpeg()
                return True, path
        except Exception:
            pass
    return _download_portable_ffmpeg(timeout=timeout)


def normalize_url(url):
    """Normalize youtu.be / shorts / tracking params to a canonical URL."""
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        return url
    try:
        # youtu.be/<id> -> youtube.com/watch?v=<id>
        m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", url)
        if m:
            vid = m.group(1)
            t = re.search(r"[?&]t=([^&]+)", url)
            tail = f"&t={t.group(1)}" if t else ""
            return f"https://www.youtube.com/watch?v={vid}{tail}"
        # shorts -> watch
        m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
        # strip tracking params like si=
        url = re.sub(r"[?&]si=[^&]*", "", url)
        url = url.replace("?&", "?").rstrip("?&")
    except Exception:
        pass
    return url


def friendly_format_error(err, quality):
    """Explain 'Requested format is not available' in plain language."""
    s = str(err or "")
    if "Requested format is not available" in s:
        if not FFMPEG:
            return (s[:200] + " — this video has no single-file (progressive) format. "
                    "Install ffmpeg (button above) so video+audio can be merged, then Retry. "
                    "Or it was saved as separate video/audio files in downloads/")
        return (s[:200] + f" — no {quality} stream matched; the downloader already "
                "retried with best available. Try quality 'best'.")
    return s[:300]


def format_for(quality):
    """Pick a yt-dlp format selector fitting ffmpeg availability."""
    if FFMPEG:
        return QUALITY_MAP.get(quality, QUALITY_MAP["best"])
    return NOFMPEG_QUALITY_MAP.get(quality, NOFMPEG_QUALITY_MAP["best"])


def safe_name(s, maxlen=80):
    s = re.sub(r'[\\/:*?"<>|]', "", s or "video")
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:maxlen] or "video")


# ---------------------------------------------------------------- jobs ---

def job_dir(jid):
    d = JOBS_DIR / jid
    if PERSIST_JOBS:
        d.mkdir(parents=True, exist_ok=True)
    return d


def job_file(jid):
    return JOBS_DIR / jid / "job.json"


def save_job(job):
    if not PERSIST_JOBS:
        return
    try:
        job_dir(job["id"])
        with open(job_file(job["id"]), "w", encoding="utf-8") as f:
            json.dump(job, f, indent=2)
    except OSError:
        pass


def load_job(jid):
    with open(job_file(jid), encoding="utf-8") as f:
        return json.load(f)


def get_job(jid):
    with _lock:
        if jid in _jobs:
            return _jobs[jid]
    try:
        job = load_job(jid)
        with _lock:
            _jobs[jid] = job
        return job
    except FileNotFoundError:
        return None


def persist(jid):
    with _lock:
        job = _jobs.get(jid)
    if job:
        save_job(job)


# -------------------------------------------------------------- analyze ---

def analyze_playlist(url, tries=3):
    """Accept a single-video URL or a playlist URL.

    Returns {title, count, unavailable, videos:[{id,title,duration,
    thumbnail,url}]}. Single videos come back as a 1-item list.
    """
    url = normalize_url(url)
    opts = {
        "quiet": True, "no_warnings": True, "extract_flat": True,
        "skip_download": True, "ignoreerrors": True,
        "retries": 3, "socket_timeout": 15,
    }
    last_err = None
    info = None
    for attempt in range(max(1, tries)):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                break
        except Exception as e:
            last_err = e
            if attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
    if not info:
        raise RuntimeError(str(last_err or "check failed — press Check to retry")[:300])
    # Single video URL (no entries) — still usable
    if info.get("_type") != "playlist" and not info.get("entries"):
        vid = info.get("id", "")
        return {"title": info.get("title", "Video"), "count": 1, "unavailable": 0,
                "videos": [{"id": vid, "title": info.get("title", vid),
                            "duration": info.get("duration") or 0,
                            "thumbnail": ((info.get("thumbnails") or [{}])[-1].get("url") or ""),
                            "url": info.get("webpage_url") or url}]}
    entries = info.get("entries") or []
    videos = []
    unavailable = 0
    for e in entries:
        if not e or not e.get("id"):
            unavailable += 1
            continue
        vid = e.get("id", "")
        title = e.get("title") or vid
        if e.get("availability") in ("private", "needs_auth") or "[Private" in str(title) or "[Deleted" in str(title):
            unavailable += 1
            videos.append({"id": vid, "title": title, "duration": e.get("duration") or 0,
                           "thumbnail": "", "url": f"https://www.youtube.com/watch?v={vid}",
                           "broken": True})
            continue
        dur = e.get("duration")
        thumb = None
        ths = e.get("thumbnails") or []
        if ths:
            thumb = ths[-1].get("url")
        if not thumb and vid:
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        url_out = e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else url)
        if url_out and not url_out.startswith("http"):
            url_out = f"https://www.youtube.com/watch?v={vid}"
        videos.append({
            "id": vid, "title": title,
            "duration": dur or 0,
            "thumbnail": thumb or "",
            "url": url_out,
        })
    return {"title": info.get("title", "Playlist"), "count": len(videos),
            "unavailable": unavailable, "videos": videos}


def _check_one(video, quality="720p"):
    # NOTE: do NOT pass a format selector here. Filtering by format during
    # a check-only extract_info turns downloadable videos into false
    # "Requested format is not available" failures (e.g. videos with no
    # progressive single-file format). Just verify the video is playable.
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "ignoreerrors": True, "retries": 2, "socket_timeout": 12}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(normalize_url(video.get("url")), download=False)
        if not info:
            return {"id": video.get("id"), "ok": False, "error": "unavailable/private?"}
        fmts = info.get("formats") or []
        if info.get("_type") == "playlist" or (not fmts and not info.get("url")):
            return {"id": video.get("id"), "ok": False, "error": "no playable format"}
        return {"id": video.get("id"), "ok": True, "error": None,
                "duration": info.get("duration") or video.get("duration", 0)}
    except Exception as e:
        return {"id": video.get("id"), "ok": False, "error": friendly_format_error(e, quality)[:150]}


def precheck_videos(videos, quality="720p", concurrency=6):
    """Verify each video BEFORE download. Returns [{id, ok, error}]."""
    out = []
    with ThreadPoolExecutor(max_workers=max(1, min(8, int(concurrency or 6)))) as ex:
        futs = {ex.submit(_check_one, v, quality): v for v in videos}
        for f in as_completed(futs):
            try:
                out.append(f.result(timeout=60))
            except Exception as e:
                v = futs[f]
                out.append({"id": v.get("id"), "ok": False, "error": str(e)[:150]})
    return out


# ------------------------------------------------------------- download ---

def create_job(playlist_url, playlist_title, videos, quality, out_format, concurrency):
    """Download every selected video as its own file (no merge)."""
    jid = uuid.uuid4().hex[:10]
    job_dir(jid)
    if out_format not in ("mp4", "mkv"):
        out_format = "mp4"
    job = {
        "id": jid, "playlist_url": playlist_url, "playlist_title": playlist_title,
        "quality": quality, "format": out_format,
        "concurrency": max(1, min(6, int(concurrency or 3))),
        "status": "queued", "created": time.time(),
        "cancel": False,
        "overall": {"pct": 0, "downloaded": 0, "total": 0, "speed": 0, "eta": 0,
                    "done": 0, "failed": 0, "total_n": len(videos)},
        "error": None,
        "videos": [
            {"id": v["id"], "title": v["title"], "duration": v.get("duration", 0),
             "thumbnail": v.get("thumbnail", ""), "url": v["url"],
             "order": i, "status": "pending", "pct": 0,
             "downloaded": 0, "total": 0, "speed": 0, "eta": 0,
             "filepath": None, "error": None}
            for i, v in enumerate(videos)
        ],
    }
    with _lock:
        _jobs[jid] = job
    save_job(job)
    t = threading.Thread(target=_run_job, args=(jid,), daemon=True)
    t.start()
    return job


def _hook_factory(jid, order):
    def hook(d):
        job = get_job(jid)
        if not job:
            return
        v = next((x for x in job["videos"] if x["order"] == order), None)
        if not v:
            return
        # Remember real filenames yt-dlp reports (most reliable way to
        # find the produced file afterwards — no glob-pattern pitfalls).
        try:
            fn = d.get("filename")
            if fn:
                seen = v.setdefault("_seen_files", [])
                if fn not in seen:
                    seen.append(fn)
            for k in ("info_dict",):
                info = d.get(k) or {}
                for fk in ("filepath", "_filename"):
                    ffn = info.get(fk)
                    if ffn:
                        seen = v.setdefault("_seen_files", [])
                        if ffn not in seen:
                            seen.append(ffn)
        except Exception:
            pass
        st = d.get("status")
        if st == "downloading":
            v["status"] = "downloading"
            v["downloaded"] = d.get("downloaded_bytes", 0) or 0
            v["total"] = d.get("total_bytes") or d.get("total_bytes_estimate") or v["total"] or 0
            v["speed"] = d.get("speed") or 0
            v["eta"] = d.get("eta") or 0
            if v["total"]:
                v["pct"] = round(v["downloaded"] / v["total"] * 100, 1)
        elif st == "finished":
            v["downloaded"] = v["total"] or v["downloaded"]
            v["pct"] = 100
        _recalc(jid)
    return hook


class _ListLogger:
    """Capture yt-dlp warnings/errors so failures say WHY, not just what."""

    def __init__(self):
        self.messages = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        try:
            self.messages.append(f"warn: {msg}")
        except Exception:
            pass

    def error(self, msg):
        try:
            self.messages.append(f"error: {msg}")
        except Exception:
            pass


def _find_produced_files(v):
    """Locate downloaded file(s) using literal name matching.

    NOTE: must NOT use Path.glob() with the stem — the " [videoid]"
    suffix contains brackets which glob treats as a character-class
    pattern, so glob silently matches nothing ("file not produced"
    even though the file exists). iterdir()+startswith is literal.
    """
    found = []
    try:
        stem = f"{safe_name(v['title'])} [{v['id']}]"
    except Exception:
        stem = None
    # 1) filenames reported by yt-dlp progress hooks (most reliable)
    try:
        for fn in (v.get("_seen_files") or []):
            try:
                p = Path(fn)
                if p.is_file():
                    found.append(p)
                elif stem:
                    # post-merge rename: same stem, container ext
                    sib = p.parent / f"{stem}{p.suffix}"
                    if sib.is_file() and sib not in found:
                        found.append(sib)
            except Exception:
                continue
    except Exception:
        pass
    # 2) literal directory scan (no glob patterns!)
    if stem and DL_DIR.exists():
        prefix = stem + "."
        id_tag = f"[{v.get('id')}]"
        try:
            for p in DL_DIR.iterdir():
                try:
                    if not p.is_file():
                        continue
                    if p in found:
                        continue
                    if p.name.startswith(prefix):
                        found.append(p)
                except OSError:
                    continue
        except OSError:
            pass
        # 3) last resort: any file carrying this video's id tag
        if not found:
            try:
                for p in DL_DIR.iterdir():
                    try:
                        if p.is_file() and id_tag in p.name:
                            found.append(p)
                    except OSError:
                        continue
            except OSError:
                pass
    # playable media first; skip yt-dlp temp parts
    playable = {".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".m4a"}
    clean = [p for p in found
             if not p.name.endswith((".part", ".ytdl", ".temp", ".tmp"))]
    scored = [p for p in clean if p.suffix.lower() in playable] or clean
    return scored


def _recalc(jid):
    with _lock:
        job = _jobs.get(jid)
        if not job:
            return
        vs = job["videos"]
        n = len(vs) or 1
        job["overall"]["pct"] = round(sum(v.get("pct", 0) for v in vs) / n, 1)
        job["overall"]["downloaded"] = sum(v.get("downloaded", 0) for v in vs)
        job["overall"]["total"] = sum(v.get("total", 0) for v in vs)
        job["overall"]["speed"] = sum(v.get("speed", 0) for v in vs if v.get("status") == "downloading")
        etas = [v.get("eta", 0) for v in vs if v.get("status") == "downloading" and v.get("eta")]
        job["overall"]["eta"] = max(etas) if etas else 0
        job["overall"]["done"] = sum(1 for v in vs if v.get("status") == "done")
        job["overall"]["failed"] = sum(1 for v in vs if v.get("status") == "failed")
        job["overall"]["total_n"] = n
    save_job(job)


def _download_one(jid, v):
    job = get_job(jid)
    if not job or job.get("cancel"):
        v["status"] = "skipped"
        return False
    if v.get("status") == "done" and v.get("filepath") and os.path.exists(v["filepath"]):
        return True
    v["status"] = "downloading"
    v["error"] = None
    persist(jid)
    quality = job.get("quality", "best")
    fmt_sel = format_for(quality)
    ext = job.get("format", "mp4")
    if ext not in ("mp4", "mkv"):
        ext = "mp4"
    v_url = normalize_url(v["url"])
    # One file per video, straight into downloads/
    target = DL_DIR / f"{safe_name(v['title'])} [{v['id']}].%(ext)s"

    def base_opts(fmt, logger):
        opts = {
            "quiet": True, "no_warnings": True, "continuedl": True, "nooverwrites": False,
            "retries": 3, "fragment_retries": 3, "concurrent_fragment_downloads": 4,
            "format": fmt,
            "format_sort": ["ext:mp4:m4a", "res", "fps", "codec:avc:m4a"],
            "outtmpl": str(target),
            "progress_hooks": [_hook_factory(jid, v["order"])],
            "logger": logger,
        }
        ff = FFMPEG or resolve_ffmpeg()
        if ff:
            # Mux best video+audio into the requested container.
            opts["merge_output_format"] = ext
            opts["ffmpeg_location"] = ff
            opts["prefer_ffmpeg"] = True
        return opts

    # Try requested quality first, then fall back to fully permissive.
    # This fixes "Requested format is not available" on videos with no
    # progressive single-file format (e.g. https://youtu.be/vj7hysh0mOI).
    attempts = [fmt_sel]
    if fmt_sel != FALLBACK_FORMAT:
        attempts.append(FALLBACK_FORMAT)
    last_err = None
    for fmt in attempts:
        logger = _ListLogger()
        try:
            with yt_dlp.YoutubeDL(base_opts(fmt, logger)) as ydl:
                ydl.download([v_url])
            cands = _find_produced_files(v)
            if not cands:
                detail = "; ".join(logger.messages[-4:]) if logger.messages else ""
                # The download may actually have landed in downloads/ under a
                # slightly different name — tell the user what to look for.
                hint = f"look for '*[{v['id']}]*' in downloads/"
                raise RuntimeError(
                    "file not produced" + (f" ({detail})" if detail else "") + f" — {hint}")
            # prefer a merged mp4/mkv over tiny split parts
            def score(p):
                try:
                    s = p.stat().st_size
                except OSError:
                    s = 0
                bonus = 1.5 if p.suffix.lower() in (".mp4", ".mkv") else 1.0
                return s * bonus
            best = max(cands, key=score)
            v["filepath"] = str(best)
            v["status"] = "done"
            v["pct"] = 100
            v["speed"] = 0
            v["eta"] = 0
            if fmt != fmt_sel:
                v["error"] = None
            persist(jid)
            _recalc(jid)
            return True
        except Exception as e:
            last_err = e
            msg = str(e)
            # Only retry on format-matching errors; other errors fail fast.
            if "Requested format is not available" not in msg and "format" not in msg.lower():
                break
            continue
    try:
        if get_job(jid).get("cancel"):
            v["status"] = "skipped"
        else:
            v["status"] = "failed"
            v["error"] = friendly_format_error(last_err, quality)
    except Exception:
        v["status"] = "failed"
        v["error"] = friendly_format_error(last_err, quality)
    v["speed"] = 0
    persist(jid)
    _recalc(jid)
    return False


def _run_job(jid):
    job = get_job(jid)
    if not job:
        return
    job["status"] = "downloading"
    job["cancel"] = False
    persist(jid)
    with ThreadPoolExecutor(max_workers=job.get("concurrency", 3)) as ex:
        futs = {ex.submit(_download_one, jid, v): v
                for v in job["videos"] if v.get("status") in ("pending", "failed", "skipped")}
        for _ in as_completed(futs):
            if get_job(jid).get("cancel"):
                for f in futs:
                    f.cancel()
                break
    job = get_job(jid)
    if job.get("cancel"):
        job["status"] = "cancelled"
        persist(jid)
        return
    fails = [v for v in job["videos"] if v.get("status") == "failed"]
    dones = [v for v in job["videos"] if v.get("status") == "done"]
    if not dones:
        job["status"] = "failed"
        job["error"] = "All downloads failed."
    elif fails:
        job["status"] = "completed_with_failures"
    else:
        job["status"] = "completed"
    persist(jid)


def cancel_job(jid):
    job = get_job(jid)
    if job:
        job["cancel"] = True
        persist(jid)
    return job


def _reset_video_for_retry(v):
    """Reset a failed video so retry starts from zero, not resumed."""
    # Delete partial/produced files (incl. .part / split .f*. pieces) so
    # the retry downloads from the start instead of resuming garbage.
    try:
        stem = f"{safe_name(v.get('title', ''))} [{v.get('id')}]"
        prefix = stem + "."
        if DL_DIR.exists():
            for p in DL_DIR.iterdir():
                try:
                    # Literal prefix match (no glob: stem contains [id]
                    # brackets). Covers "stem.mp4", "stem.f398.mp4",
                    # "stem.mp4.part", etc.
                    if p.is_file() and p.name.startswith(prefix):
                        p.unlink()
                except OSError:
                    continue
            # also drop hook-reported temp files for this video
            for fn in (v.get("_seen_files") or []):
                try:
                    pp = Path(fn)
                    if pp.is_file() and pp.parent == DL_DIR:
                        pp.unlink()
                except OSError:
                    continue
    except Exception:
        pass
    v["status"] = "pending"
    v["error"] = None
    v["pct"] = 0
    v["downloaded"] = 0
    v["total"] = 0
    v["speed"] = 0
    v["eta"] = 0
    v["filepath"] = None
    try:
        v["_seen_files"] = []
    except Exception:
        pass


def retry_job(jid, video_id=None):
    job = get_job(jid)
    if not job or job.get("status") == "downloading":
        return job
    if video_id:
        for v in job["videos"]:
            if v["id"] == video_id or str(v["order"]) == str(video_id):
                _reset_video_for_retry(v)
    else:
        for v in job["videos"]:
            if v.get("status") in ("failed", "skipped", "pending"):
                _reset_video_for_retry(v)
    job["status"] = "queued"
    job["cancel"] = False
    job["error"] = None
    persist(jid)
    t = threading.Thread(target=_run_job, args=(jid,), daemon=True)
    t.start()
    return job


# -------------------------------------------------------------- history ---

def list_history():
    out = []
    if not JOBS_DIR.exists():
        return out
    for jf in sorted(JOBS_DIR.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        try:
            with open(jf, encoding="utf-8") as f:
                j = json.load(f)
            out.append({"id": j["id"], "title": j.get("playlist_title"), "status": j.get("status"),
                        "overall": j.get("overall"), "created": j.get("created"),
                        "format": j.get("format"),
                        "files": [v.get("filepath") for v in j.get("videos", []) if v.get("filepath")]})
        except Exception:
            pass
    return out


def _dir_size(p: Path):
    total = 0
    try:
        for f in p.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def cache_info():
    jobs_size = _dir_size(JOBS_DIR) if JOBS_DIR.exists() else 0
    dl_size = _dir_size(DL_DIR) if DL_DIR.exists() else 0
    n_jobs = len(list(JOBS_DIR.glob("*/job.json"))) if JOBS_DIR.exists() else 0
    return {"jobs_size": jobs_size, "downloads_size": dl_size,
            "jobs_count": n_jobs,
            "jobs_dir": str(JOBS_DIR.resolve()),
            "downloads_dir": str(DL_DIR.resolve())}


def delete_job(jid, delete_files=False):
    import shutil
    job = get_job(jid)
    if delete_files and job:
        for v in job.get("videos", []):
            fp = v.get("filepath")
            try:
                if fp and os.path.exists(fp):
                    os.remove(fp)
            except OSError:
                pass
    with _lock:
        _jobs.pop(jid, None)
    jd = JOBS_DIR / jid
    if jd.exists():
        try:
            shutil.rmtree(jd, ignore_errors=True)
        except OSError:
            pass
    return True


def clear_history(delete_files=False):
    import shutil
    with _lock:
        ids = [p.parent.name for p in JOBS_DIR.glob("*/job.json")] if JOBS_DIR.exists() else []
        _jobs.clear()
    removed_jobs = 0
    removed_files = 0
    if delete_files and DL_DIR.exists():
        for f in list(DL_DIR.iterdir()):
            try:
                if f.is_file():
                    f.unlink()
                    removed_files += 1
            except OSError:
                pass
    if JOBS_DIR.exists():
        for jid in ids:
            jd = JOBS_DIR / jid
            try:
                shutil.rmtree(jd, ignore_errors=True)
                removed_jobs += 1
            except OSError:
                pass
    return {"removed_jobs": removed_jobs, "removed_files": removed_files, **cache_info()}


# ------------------------------------------------- yt-dlp self-update ---

def installed_ytdlp_version():
    """Return installed yt-dlp version string, or None if missing."""
    try:
        from importlib.metadata import version
        return version("yt-dlp")
    except Exception:
        try:
            return yt_dlp.version.__version__
        except Exception:
            return None


def latest_ytdlp_version(timeout=12):
    """Return latest yt-dlp version from PyPI, or None on network error."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={"User-Agent": "ytdlp-gui/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data.get("info") or {}).get("version")
    except Exception:
        return None


def _ver_tuple(s):
    try:
        return tuple(int(x) for x in re.findall(r"\d+", s or ""))
    except Exception:
        return ()


def ytdlp_update_available():
    """(installed, latest, available_bool). available False if unknown."""
    inst = installed_ytdlp_version()
    latest = latest_ytdlp_version()
    if not inst or not latest:
        return inst, latest, False
    try:
        available = _ver_tuple(latest) > _ver_tuple(inst)
    except Exception:
        available = latest != inst
    return inst, latest, available


def update_ytdlp(timeout=300):
    """pip install -U yt-dlp. Returns (ok, message)."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-600:]
        return ok, tail or ("updated" if ok else "update failed")
    except Exception as e:
        return False, str(e)[:300]
