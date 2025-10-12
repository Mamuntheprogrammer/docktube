import subprocess
import threading
import time
import os
import queue

class YouTubeDownloaderCore:
    def __init__(self, yt_dlp_cmd: str = "yt-dlp"):
        self.cmd = yt_dlp_cmd
        self.output_queue = queue.Queue()

    def download(self, video_id: str, output_path: str, timeout_per_video: int = 300) -> bool:
        """Download a single video by ID. Returns True on success."""
        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)

        command = [
            self.cmd,
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--output", os.path.join(output_path, "%(title)s.%(ext)s"),
            "--embed-thumbnail",
            "--embed-metadata",
            "--progress",
            "--retries", "3",
            "--fragment-retries", "3",
            "--socket-timeout", "30",
            f"https://youtube.com/watch?v={video_id}"
        ]

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=False
            )

            # Start reading output in a thread
            threading.Thread(target=self._process_output, args=(process, video_id), daemon=True).start()

            start_time = time.time()
            while True:
                if process.poll() is not None:
                    break
                if time.time() - start_time > timeout_per_video:
                    process.terminate()
                    return False
                time.sleep(0.1)

            return process.returncode == 0
        except Exception:
            return False

    def _process_output(self, process: subprocess.Popen, video_id: str):
        try:
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    try:
                        decoded = line.decode(errors='ignore').strip()
                    except Exception:
                        decoded = str(line)
                    self.output_queue.put((video_id, decoded))
        except Exception:
            pass
