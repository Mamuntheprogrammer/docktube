import json
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import imageio_ffmpeg
import yt_dlp

BASE = Path(__file__).parent
JOBS_DIR = BASE / "jobs"
DL_DIR = BASE / "downloads"
JOBS_DIR.mkdir(exist_ok=True)
DL_DIR.mkdir(exist_ok=True)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
# Make bundled ffmpeg discoverable for yt-dlp merges ("merging of multiple
# formats but ffmpeg is not installed"). yt-dlp shells out to `ffmpeg`, so it
# must be on PATH *and* passed via ffmpeg_location.
try:
    _ff_dir = str(Path(FFMPEG).parent)
    if _ff_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ff_dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass
_lock = threading.Lock()
_jobs = {}

# Force H264+AAC/MP4 first so concat -c copy usually works (seconds).
# Fallbacks keep it working when H264 isn't offered.
QUALITY_MAP = {
    "best": "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b",
    "1080p": "bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
    "720p": "bv*[vcodec^=avc1][height<=720]+ba[acodec^=mp4a]/bv*[height<=720]+ba/b[height<=720]/b",
    "480p": "bv*[vcodec^=avc1][height<=480]+ba[acodec^=mp4a]/bv*[height<=480]+ba/b[height<=480]/b",
    "360p": "bv*[vcodec^=avc1][height<=360]+ba[acodec^=mp4a]/bv*[height<=360]+ba/b[height<=360]/b",
}

_HW_ENCODER = None

def _get_hw_encoder():
    """Detect fastest available h264 encoder once: nvenc > qsv > amf > cpu."""
    global _HW_ENCODER
    if _HW_ENCODER is not None:
        return _HW_ENCODER
    for name in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            r = subprocess.run([FFMPEG, "-hide_banner", "-h", f"encoder={name}"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and "is not recognized" not in (r.stderr or "") + (r.stdout or ""):
                _HW_ENCODER = name
                return name
        except Exception:
            pass
    _HW_ENCODER = "libx264"
    return _HW_ENCODER

def safe_name(s, maxlen=80):
    s = re.sub(r'[\\/:*?"<>|]', "", s or "video")
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:maxlen] or "video")

def job_dir(jid):
    d = JOBS_DIR / jid
    d.mkdir(exist_ok=True)
    return d

def job_file(jid):
    return job_dir(jid) / "job.json"

def save_job(job):
    with open(job_file(job["id"]), "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

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

def analyze_playlist(url, tries=3):
    # Retry whole playlist extract (network hiccups) + count dead entries
    # so user can hit Analyze again before spending time downloading.
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
        raise RuntimeError(str(last_err or "analyze failed — press Analyze to retry")[:300])
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
        # yt-dlp marks private/deleted with availability field
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
    # Light pre-download check: can we resolve a downloadable format?
    fmt_sel = QUALITY_MAP.get(quality, QUALITY_MAP["best"])
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "ignoreerrors": True, "retries": 2, "socket_timeout": 12,
            "format": fmt_sel}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video.get("url"), download=False)
        if not info:
            return {"id": video.get("id"), "ok": False, "error": "unavailable/private?"}
        fmts = info.get("formats") or []
        if info.get("_type") == "playlist" or (not fmts and not info.get("url")):
            return {"id": video.get("id"), "ok": False, "error": "no playable format"}
        return {"id": video.get("id"), "ok": True, "error": None,
                "duration": info.get("duration") or video.get("duration", 0)}
    except Exception as e:
        return {"id": video.get("id"), "ok": False, "error": str(e)[:150]}

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

LOCAL_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".m4a", ".mp3")

def _clean_folder_input(s):
    s = (s or "").strip().strip('"').strip("'")
    # allow file:// prefix from browser paste
    if s.lower().startswith("file://"):
        s = s[7:]
        if s.startswith("///"):
            s = s[2:]
    return s

def list_local_files(folder):
    folder = _clean_folder_input(folder)
    p = Path(folder).expanduser()
    if not p.exists() or not p.is_dir():
        raise RuntimeError(f"folder not found: {folder}")
    files = [f for f in sorted(p.iterdir()) if f.is_file() and f.suffix.lower() in LOCAL_EXTS]
    if not files:
        raise RuntimeError(f"no video files {LOCAL_EXTS} in: {folder}")
    out = []
    for f in files:
        try:
            sz = f.stat().st_size
        except OSError:
            sz = 0
        out.append({"id": f.name, "title": f.stem, "duration": 0,
                    "thumbnail": "", "url": "", "filepath": str(f.resolve()),
                    "size": sz, "ext": f.suffix.lower()})
    return {"folder": str(p.resolve()), "title": p.name or "local",
            "count": len(out), "videos": out}

def create_local_job(folder, files, out_format="mp4"):
    # files: [{title, filepath}] already sorted by user selection order
    jid = uuid.uuid4().hex[:10]
    jd = job_dir(jid)
    (jd / "parts").mkdir(exist_ok=True)
    if out_format not in ("mp4", "mkv"):
        out_format = "mp4"
    title = Path(_clean_folder_input(folder)).name or "local_merge"
    vids = []
    for i, f in enumerate(files):
        fp = f.get("filepath") or f.get("url") or ""
        if not fp or not os.path.exists(fp):
            continue
        vids.append({"id": Path(fp).name, "title": f.get("title") or Path(fp).stem,
                     "duration": f.get("duration", 0), "thumbnail": "",
                     "url": fp, "order": i, "status": "done", "pct": 100,
                     "downloaded": f.get("size", 0), "total": f.get("size", 0),
                     "speed": 0, "eta": 0, "filepath": str(Path(fp).resolve()),
                     "error": None})
    if not vids:
        raise RuntimeError("no existing files selected")
    job = {"id": jid, "playlist_url": folder, "playlist_title": title,
           "quality": "local", "format": out_format, "concurrency": 1,
           "status": "queued", "created": time.time(), "cancel": False,
           "local": True,
           "overall": {"pct": 100, "downloaded": sum(v["total"] for v in vids),
                       "total": sum(v["total"] for v in vids), "speed": 0, "eta": 0,
                       "done": len(vids), "failed": 0, "total_n": len(vids)},
           "merged_file": None, "merging": False, "error": None, "videos": vids}
    with _lock:
        _jobs[jid] = job
    save_job(job)
    t = threading.Thread(target=_run_local_job, args=(jid,), daemon=True)
    t.start()
    return job

def _run_local_job(jid):
    # No downloads — straight to merge. Same-type => concat copy = instant.
    job = get_job(jid)
    if not job:
        return
    job["status"] = "merging"
    job["merging"] = True
    persist(jid)
    ok = merge_parts(jid)
    job = get_job(jid)
    if not job:
        return
    job["merging"] = False
    job["status"] = "completed" if ok else "merge_failed"
    persist(jid)

def create_job(playlist_url, playlist_title, videos, quality, out_format, concurrency):
    jid = uuid.uuid4().hex[:10]
    jd = job_dir(jid)
    tmp = jd / "parts"
    tmp.mkdir(exist_ok=True)
    job = {
        "id": jid, "playlist_url": playlist_url, "playlist_title": playlist_title,
        "quality": quality, "format": out_format,
        "concurrency": max(1, min(6, int(concurrency or 3))),
        "status": "queued", "created": time.time(),
        "cancel": False,
        "overall": {"pct": 0, "downloaded": 0, "total": 0, "speed": 0, "eta": 0, "done": 0, "failed": 0, "total_n": len(videos)},
        "merged_file": None, "merging": False, "error": None,
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
    jd = job_dir(jid)
    parts = jd / "parts"
    fmt_sel = QUALITY_MAP.get(job.get("quality", "best"), QUALITY_MAP["best"])
    ext = "mp4"
    target = parts / f"{v['order']:03d}_{safe_name(v['title'])}.%(ext)s"
    opts = {
        "quiet": True, "no_warnings": True, "continuedl": True, "nooverwrites": False,
        "retries": 3, "fragment_retries": 3, "concurrent_fragment_downloads": 4,
        "format": fmt_sel, "merge_output_format": ext,
        "prefer_free_formats": False,
        "format_sort": ["vcodec:h264", "acodec:m4a", "ext:mp4"],
        "format_sort_force": True,
        "ffmpeg_location": FFMPEG, "prefer_ffmpeg": True,
        "outtmpl": str(target),
        "progress_hooks": [_hook_factory(jid, v["order"])],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([v["url"]])
        cands = sorted(parts.glob(f"{v['order']:03d}_*"))
        cands = [c for c in cands if c.suffix.lower() in (".mp4", ".mkv", ".webm", ".m4a", ".mp3")]
        if not cands:
            raise RuntimeError("file not produced")
        best = max(cands, key=lambda p: p.stat().st_size)
        v["filepath"] = str(best)
        v["status"] = "done"
        v["pct"] = 100
        v["speed"] = 0
        v["eta"] = 0
        persist(jid)
        _recalc(jid)
        return True
    except Exception as e:
        if get_job(jid).get("cancel"):
            v["status"] = "skipped"
        else:
            v["status"] = "failed"
            v["error"] = str(e)[:300]
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
        futs = {ex.submit(_download_one, jid, v): v for v in job["videos"] if v.get("status") in ("pending", "failed", "skipped")}
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
    dones = [v for v in sorted(job["videos"], key=lambda x: x["order"]) if v.get("status") == "done"]
    if not dones:
        job["status"] = "failed"
        job["error"] = "All downloads failed."
        persist(jid)
        return
    job["status"] = "merging"
    job["merging"] = True
    persist(jid)
    ok = merge_parts(jid)
    job = get_job(jid)
    job["merging"] = False
    if ok:
        job["status"] = "completed" if not fails else "completed_with_failures"
        cleanup_parts(jid, keep_merged=True)
    else:
        job["status"] = "merge_failed"
    persist(jid)

def _ffmpeg_merge(cmd, jid, total_dur, phase="Merging"):
    """Run ffmpeg with -progress pipe:1 and feed job['merge_pct'] live.

    Fixes stall: stderr is drained in a bg thread (full pipe deadlocked
    ffmpeg ~30%), and -loglevel warning keeps output small.
    """
    job = get_job(jid)
    if job is None:
        return False, "job gone"
    n = job["overall"]["done"] if isinstance(job.get("overall"), dict) else "?"
    job["merge_pct"] = 0
    job["merge_msg"] = f"{phase} {n} videos… 0% (fast pass)"
    persist(jid)
    full = list(cmd) + ["-progress", "pipe:1", "-nostats", "-loglevel", "warning"]
    p = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, bufsize=1)
    err_buf = []
    def _drain():
        try:
            for chunk in p.stderr:
                if len(err_buf) < 50:
                    err_buf.append(chunk)
        except Exception:
            pass
    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    last_save = 0.0
    try:
        for line in p.stdout:
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    ms = int(line.split("=", 1)[1] or 0)
                except ValueError:
                    continue
                if total_dur > 0:
                    pct = max(0, min(99, round(ms / 1_000_000 / total_dur * 100, 1)))
                    jj = get_job(jid)
                    if jj is not None:
                        jj["merge_pct"] = pct
                        now = time.time()
                        if now - last_save > 0.5:
                            last_save = now
                            jj["merge_msg"] = f"{phase} {n} videos… {pct}%"
                            persist(jid)
            elif line.startswith("progress=") and line.endswith("end"):
                break
    finally:
        try:
            p.wait(timeout=600)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
            p.wait()
        t.join(timeout=5)
        err = "".join(err_buf)
        if p.returncode == 0:
            jj = get_job(jid)
            if jj is not None:
                jj["merge_pct"] = 100
                persist(jid)
            return True, ""
        return False, (err or "")[-800:]

def _probe_one(path, fallback=0.0):
    """Duration + video props in ONE ffmpeg -i call. Returns dict."""
    info = {"dur": float(fallback or 0), "vcodec": "", "acodec": "",
            "w": 0, "h": 0, "fps": "", "pix": ""}
    try:
        r = subprocess.run([FFMPEG, "-i", str(path)],
                           capture_output=True, text=True, timeout=30)
        err = r.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
        if m:
            info["dur"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        mv = re.search(r"Stream #\d+:\d+.*Video:\s*(\w+)[^,]*,\s*[^,]*,\s*(\d+)x(\d+)[^,]*,\s*([\d.]+)\s*fps", err)
        if mv:
            info["vcodec"] = (mv.group(1) or "").lower()
            info["w"] = int(mv.group(2)); info["h"] = int(mv.group(3))
            info["fps"] = mv.group(4)
        else:
            mv2 = re.search(r"Video:\s*(\w+)", err)
            if mv2:
                info["vcodec"] = mv2.group(1).lower()
            mwh = re.search(r"(\d+)x(\d+)", err)
            if mwh:
                try:
                    info["w"] = int(mwh.group(1)); info["h"] = int(mwh.group(2))
                except Exception:
                    pass
        ma = re.search(r"Stream #\d+:\d+.*Audio:\s*(\w+)", err)
        if ma:
            info["acodec"] = ma.group(1).lower()
    except Exception:
        pass
    if info["dur"] <= 0:
        info["dur"] = float(fallback or 0)
    return info

def _probe_duration(path, fallback=0.0):
    return _probe_one(path, fallback)["dur"]

def _write_chapters(dones, meta_path, jid=None, durations=None):
    """FFmpeg metadata with one chapter per video for VLC/players.
    Uses pre-probed durations (no re-probe) and updates merge_msg so
    the 'Adding chapters' stage shows progress instead of hanging.
    """
    lines = [";FFMETADATA1"]
    pos_ms = 0
    wrote = 0
    for i, v in enumerate(dones):
        if durations and i < len(durations):
            dur_s = durations[i]
        else:
            fp = v.get("filepath")
            dur_s = _probe_duration(fp, v.get("duration", 0)) if fp else float(v.get("duration", 0) or 0)
        if dur_s <= 0:
            continue
        end_ms = pos_ms + int(round(dur_s * 1000))
        title = (v.get("title") or f"Part {v.get('order', 0) + 1}").replace("\n", " ").strip()[:120]
        # '=' and ';' break FFMETADATA parsing — escape them
        title = title.replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={pos_ms}", f"END={end_ms}", f"title={title}"]
        pos_ms = end_ms
        wrote += 1
        if jid is not None and i % 2 == 0:
            try:
                jj = get_job(jid)
                if jj is not None:
                    jj["merge_msg"] = f"Adding chapters for VLC… {i+1}/{len(dones)}"
                    persist(jid)
            except Exception:
                pass
    if not wrote:
        return False
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return True

def _inject_chapters(out, meta_path, jid=None, total_dur=0):
    # -map 0 is critical: without it ffmpeg may drop/duplicate streams
    # when there are 2 inputs (video + metadata). -codec copy = fast remux.
    tmp = out.with_name(out.stem + "_ch" + out.suffix)
    cmd = [FFMPEG, "-y", "-i", str(out), "-i", str(meta_path),
           "-map", "0", "-map_metadata", "1", "-codec", "copy", str(tmp)]
    if jid is not None:
        ok, err = _ffmpeg_merge(cmd, jid, total_dur or 1, phase="Adding chapters")
    else:
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok, err = (r.returncode == 0, (r.stderr or "")[-800:])
    if ok and tmp.exists() and tmp.stat().st_size > 0:
        try:
            os.replace(tmp, out)
            return True
        except OSError:
            pass
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    return False

def merge_parts(jid):
    job = get_job(jid)
    ext = job.get("format", "mp4")
    if ext not in ("mp4", "mkv"):
        ext = "mp4"
    dones = [v for v in sorted(job["videos"], key=lambda x: x["order"]) if v.get("status") == "done" and v.get("filepath") and os.path.exists(v["filepath"])]
    if not dones:
        return False
    jd = job_dir(jid)
    out = DL_DIR / f"{safe_name(job.get('playlist_title', 'playlist'))}_{jid}.{ext}"
    lst = jd / "filelist.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for v in dones:
            p = Path(v["filepath"]).resolve()
            f.write(f"file '{p.as_posix()}'\n")

    # --- 1. Parallel probe (1 ffmpeg -i per file) with live progress ---
    # This is what used to look like a "hang" on 'Adding chapters'.
    job = get_job(jid)
    job["merging"] = True
    job["status"] = "merging"
    job["merge_pct"] = 0
    job["merge_msg"] = f"Checking {len(dones)} videos… 0/{len(dones)}"
    persist(jid)
    probes = [None] * len(dones)
    def _one(i, v):
        probes[i] = _probe_one(v.get("filepath"), v.get("duration", 0))
    with ThreadPoolExecutor(max_workers=min(8, len(dones))) as ex:
        futs = {ex.submit(_one, i, v): i for i, v in enumerate(dones)}
        done_n = 0
        for _ in as_completed(futs):
            done_n += 1
            if done_n % 2 == 0 or done_n == len(dones):
                jj = get_job(jid)
                if jj is not None:
                    jj["merge_msg"] = f"Checking {len(dones)} videos… {done_n}/{len(dones)}"
                    jj["merge_pct"] = round(done_n / len(dones) * 10)  # 0-10% for probe
                    persist(jid)
    durations = [float(p["dur"] if p else 0) for p in probes]
    total_dur = sum(durations)
    if total_dur <= 0:
        total_dur = sum(float(v.get("duration") or 0) for v in dones)
    if total_dur <= 0:
        try:
            total_dur = sum(Path(v["filepath"]).stat().st_size for v in dones if v.get("filepath")) / 1_000_000 * 8 / 2
        except Exception:
            total_dur = 0

    # --- 2. Decide copy vs re-encode UPFRONT ---
    # stream-copy succeeds but freezes video (audio ok) when inputs differ
    # in codec / resolution / fps — the exact symptom reported.
    vcodecs = { (p.get("vcodec") or "") for p in probes if p }
    sizes = { (p.get("w"), p.get("h")) for p in probes if p }
    fpss = { (p.get("fps") or "") for p in probes if p }
    mismatch = len(vcodecs) > 1 or len(sizes) > 1 or len(fpss) > 1
    # widest/ tallest target so nothing is upscaled weirdly; keep even dims
    try:
        tw = max((p.get("w") or 0) for p in probes if p) or 0
        th = max((p.get("h") or 0) for p in probes if p) or 0
        tw -= tw % 2; th -= th % 2
    except Exception:
        tw, th = 0, 0

    ok = False
    err = ""
    # SUPERFAST path: concat copy with genpts (seconds, no re-encode).
    job = get_job(jid)
    if job is not None:
        job["merge_msg"] = f"Merging {len(dones)} videos… (0%)"
        persist(jid)
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-fflags", "+genpts", "-avoid_negative_ts", "make_zero",
           "-c", "copy", "-movflags", "+faststart", str(out)]
    ok, err = _ffmpeg_merge(cmd, jid, total_dur, phase="Merging")
    if ok and out.exists() and not mismatch:
        try:
            od = _probe_duration(str(out), 0)
            if total_dur > 0 and od < total_dur * 0.85:
                mismatch = True
                ok = False
        except Exception:
            pass
    if mismatch:
        ok = False  # force normalize path even if copy "succeeded"
    if not ok:
        hw = _get_hw_encoder()
        # Minimal filter: only normalize what actually differs (huge speedup
        # vs always scale+fps). Audio copy when already AAC.
        size_diff = len(sizes) > 1
        fps_diff = len(fpss) > 1
        vfilters = []
        if size_diff and tw and th:
            vfilters.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease")
            vfilters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        else:
            vfilters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        vfilters.append("setsar=1")
        if fps_diff:
            vfilters.append("fps=30")
        vf = ",".join(vfilters)
        acodecs = {(p.get("acodec") or "") for p in probes if p}
        audio_copy = acodecs == {"aac"} or acodecs == {"mp4a"}
        jj = get_job(jid)
        if jj is not None:
            jj["merge_msg"] = f"Mixed sources — fast normalize ({hw}, {len(dones)} videos)…"
            persist(jid)
        base = [FFMPEG, "-y", "-threads", "0", "-f", "concat", "-safe", "0", "-i", str(lst),
                "-vf", vf, "-pix_fmt", "yuv420p"]
        if hw == "h264_nvenc":
            vargs = ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "23"]
        elif hw == "h264_qsv":
            vargs = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"]
        elif hw == "h264_amf":
            vargs = ["-c:v", "h264_amf", "-quality", "speed", "-qp", "23"]
        else:
            vargs = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
        aargs = ["-c:a", "copy"] if audio_copy else ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
        cmd2 = base + vargs + aargs + ["-movflags", "+faststart", str(out)]
        ok, err = _ffmpeg_merge(cmd2, jid, total_dur, phase="Re-encoding")
        if not ok:
            job = get_job(jid)
            if job is not None:
                job["error"] = (err or "")[-500:]
                persist(jid)
            return False
    # --- 3. Chapters with real progress (fast remux, not re-encode) ---
    try:
        meta = jd / "chapters.meta"
        if _write_chapters(dones, meta, jid=jid, durations=durations):
            jj = get_job(jid)
            if jj is not None:
                try:
                    od = _probe_duration(str(out), total_dur) or total_dur
                except Exception:
                    od = total_dur
                jj["merge_msg"] = "Adding chapters for VLC…"
                persist(jid)
                _inject_chapters(out, meta, jid=jid, total_dur=od)
    except Exception:
        pass
    job = get_job(jid)
    if job is None:
        return False
    job["merged_file"] = str(out.resolve())
    job["merge_pct"] = 100
    job["merge_msg"] = "Done"
    persist(jid)
    return True

def cleanup_parts(jid, keep_merged=True):
    jd = job_dir(jid)
    parts = jd / "parts"
    if parts.exists():
        for p in parts.iterdir():
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass

def cancel_job(jid):
    job = get_job(jid)
    if job:
        job["cancel"] = True
        persist(jid)
    return job

def retry_job(jid, video_id=None):
    job = get_job(jid)
    if not job or job.get("status") in ("downloading", "merging") or job.get("merging"):
        return job
    if video_id:
        for v in job["videos"]:
            if v["id"] == video_id or str(v["order"]) == str(video_id):
                v["status"] = "pending"
                v["error"] = None
                v["pct"] = 0
    else:
        for v in job["videos"]:
            if v.get("status") in ("failed", "skipped", "pending"):
                v["status"] = "pending"
                v["error"] = None
    job["status"] = "queued"
    job["cancel"] = False
    job["error"] = None
    persist(jid)
    t = threading.Thread(target=_run_job, args=(jid,), daemon=True)
    t.start()
    return job

def list_history():
    out = []
    for jf in sorted(JOBS_DIR.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        try:
            with open(jf, encoding="utf-8") as f:
                j = json.load(f)
            out.append({"id": j["id"], "title": j.get("playlist_title"), "status": j.get("status"),
                        "overall": j.get("overall"), "merged_file": j.get("merged_file"),
                        "created": j.get("created"), "format": j.get("format")})
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
    n_parts = 0
    parts_size = 0
    if JOBS_DIR.exists():
        for pf in JOBS_DIR.rglob("parts/*"):
            try:
                if pf.is_file():
                    n_parts += 1
                    parts_size += pf.stat().st_size
            except OSError:
                pass
    return {"jobs_size": jobs_size, "downloads_size": dl_size,
            "jobs_count": n_jobs, "parts_count": n_parts,
            "parts_size": parts_size,
            "jobs_dir": str(JOBS_DIR.resolve()),
            "downloads_dir": str(DL_DIR.resolve())}

def clear_cache():
    """Delete temp parts / filelist / chapters.meta, keep job.json + merged files."""
    freed = 0
    removed = 0
    if JOBS_DIR.exists():
        for parts in JOBS_DIR.glob("*/parts"):
            for p in list(parts.iterdir()):
                try:
                    if p.is_file():
                        freed += p.stat().st_size
                        p.unlink()
                        removed += 1
                except OSError:
                    pass
        for extra in list(JOBS_DIR.glob("*/filelist.txt")) + list(JOBS_DIR.glob("*/chapters.meta")):
            try:
                if extra.is_file():
                    freed += extra.stat().st_size
                    extra.unlink()
                    removed += 1
            except OSError:
                pass
    return {"freed_bytes": freed, "removed_files": removed, **cache_info()}

def delete_job(jid, delete_merged=False):
    import shutil
    job = get_job(jid)
    merged = job.get("merged_file") if job else None
    if delete_merged and merged:
        try:
            if os.path.exists(merged):
                os.remove(merged)
        except OSError:
            pass
    with _lock:
        _jobs.pop(jid, None)
    jd = JOBS_DIR / jid
    if jd.exists():
        import shutil as _sh
        try:
            _sh.rmtree(jd, ignore_errors=True)
        except OSError:
            pass
    return True

def clear_history(delete_merged=False):
    import shutil
    with _lock:
        ids = [p.parent.name for p in JOBS_DIR.glob("*/job.json")] if JOBS_DIR.exists() else []
        _jobs.clear()
    removed_jobs = 0
    removed_files = 0
    if delete_merged and DL_DIR.exists():
        # only files that look like our merged outputs: *_<10hex>.mp4/.mkv
        for f in list(DL_DIR.glob("*_*.mp4")) + list(DL_DIR.glob("*_*.mkv")):
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
    return {"removed_jobs": removed_jobs, "removed_merged": removed_files, **cache_info()}
