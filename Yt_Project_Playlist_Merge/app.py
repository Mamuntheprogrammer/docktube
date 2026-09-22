import os
import subprocess
import sys
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
import core

BASE = Path(__file__).parent
app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")
CORS(app)

@app.route("/")
def index():
    return send_from_directory(str(BASE / "static"), "index.html")

@app.route("/api/health")
def health():
    return jsonify({"ok": True, "ffmpeg": core.FFMPEG})

@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Paste a playlist or video URL."}), 400
    try:
        return jsonify(core.analyze_playlist(url))
    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 500

@app.route("/api/local/list", methods=["POST"])
def local_list():
    data = request.get_json(force=True)
    folder = (data.get("folder") or data.get("url") or "").strip()
    if not folder:
        return jsonify({"error": "Paste a folder path, e.g. D:\\Videos"}), 400
    try:
        return jsonify(core.list_local_files(folder))
    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 400

@app.route("/api/local/merge", methods=["POST"])
def local_merge():
    data = request.get_json(force=True)
    folder = data.get("folder", "")
    files = data.get("videos") or data.get("files") or []
    if not files:
        return jsonify({"error": "No files selected."}), 400
    try:
        job = core.create_local_job(folder, files, data.get("format", "mp4"))
        return jsonify({"id": job["id"]})
    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 400

@app.route("/api/jobs", methods=["POST"])
def start_job():
    data = request.get_json(force=True)
    videos = data.get("videos") or []
    if not videos:
        return jsonify({"error": "No videos selected."}), 400
    job = core.create_job(
        data.get("playlist_url", ""), data.get("playlist_title", "playlist"),
        videos, data.get("quality", "best"), data.get("format", "mp4"),
        data.get("concurrency", 3),
    )
    return jsonify({"id": job["id"]})

@app.route("/api/jobs/<jid>")
def job_status(jid):
    job = core.get_job(jid)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)

@app.route("/api/jobs/<jid>/cancel", methods=["POST"])
def job_cancel(jid):
    job = core.cancel_job(jid)
    return jsonify(job or {"error": "not found"})

@app.route("/api/jobs/<jid>/retry", methods=["POST"])
def job_retry(jid):
    data = request.get_json(force=True, silent=True) or {}
    job = core.retry_job(jid, data.get("video_id"))
    return jsonify(job or {"error": "not found"})

@app.route("/api/jobs/<jid>/merge", methods=["POST"])
def job_merge(jid):
    ok = core.merge_parts(jid)
    job = core.get_job(jid)
    if ok:
        job["status"] = "completed"
        core.persist(jid)
        core.cleanup_parts(jid)
    return jsonify(job)

@app.route("/api/precheck", methods=["POST"])
def precheck():
    data = request.get_json(force=True)
    videos = data.get("videos") or []
    if not videos:
        return jsonify({"error": "No videos to check."}), 400
    return jsonify({"results": core.precheck_videos(
        videos, data.get("quality", "720p"), data.get("concurrency", 6))})

@app.route("/api/history")
def history():
    return jsonify(core.list_history())

@app.route("/api/cache/info")
def cache_info():
    return jsonify(core.cache_info())

@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    return jsonify(core.clear_cache())

@app.route("/api/jobs/<jid>", methods=["DELETE"])
def job_delete(jid):
    data = request.get_json(force=True, silent=True) or {}
    # ?delete_file=1 also deletes merged video file
    delete_file = str(request.args.get("delete_file", "")).lower() in ("1", "true", "yes")
    if isinstance(data.get("delete_merged"), bool):
        delete_file = data["delete_merged"]
    elif isinstance(data.get("delete_file"), bool):
        delete_file = data["delete_file"]
    core.delete_job(jid, delete_merged=delete_file)
    return jsonify({"ok": True})

@app.route("/api/history/clear", methods=["POST"])
def history_clear():
    data = request.get_json(force=True, silent=True) or {}
    delete_merged = bool(data.get("delete_merged", False))
    if str(request.args.get("delete_merged", "")).lower() in ("1", "true", "yes"):
        delete_merged = True
    return jsonify(core.clear_history(delete_merged=delete_merged))

@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data = request.get_json(force=True, silent=True) or {}
    target = data.get("path") or str(core.DL_DIR.resolve())
    if os.path.isfile(target):
        target = os.path.dirname(target)
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/file/<jid>")
def download_file(jid):
    job = core.get_job(jid)
    if not job or not job.get("merged_file") or not os.path.exists(job["merged_file"]):
        return jsonify({"error": "Merged file not found."}), 404
    return send_file(job["merged_file"], as_attachment=True)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)
