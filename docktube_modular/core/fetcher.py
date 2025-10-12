import subprocess
import json
from typing import List

class YouTubeFetcher:
    """Fetches video/playlist metadata using yt-dlp (JSON output)."""
    def __init__(self, yt_dlp_cmd: str = "yt-dlp"):
        self.cmd = yt_dlp_cmd

    def fetch(self, url: str, timeout: int = 30) -> List[dict]:
        command = [self.cmd, "--no-download", "--flat-playlist", "-J", url]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                raise RuntimeError(result.stderr or "yt-dlp returned non-zero exit code")
            data = json.loads(result.stdout or "{}")
            videos = []
            if isinstance(data, dict) and 'entries' in data:
                for entry in data['entries']:
                    if entry:
                        videos.append({
                            'id': entry.get('id', ''),
                            'title': entry.get('title', 'Unknown Title'),
                            'size': 'TBD',
                            'type': 'MP4'
                        })
            elif isinstance(data, dict) and data:
                videos.append({
                    'id': data.get('id', ''),
                    'title': data.get('title', 'Unknown Title'),
                    'size': 'TBD',
                    'type': 'MP4'
                })
            return videos
        except Exception as e:
            raise
