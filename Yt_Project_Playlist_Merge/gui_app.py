import io
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import customtkinter as ctk
import requests
from PIL import Image

import core

BASE = Path(__file__).parent

def fmtB(n):
    if not n: return "0 B"
    for u in ["B","KB","MB","GB","TB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def fmtS(n):
    return "—" if not n else fmtB(n)+"/s"

def fmtT(s):
    s = int(s or 0)
    if not s: return "—"
    m, s = divmod(s, 60); h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s"

def fmtD(s):
    s = int(s or 0); return f"{s//60}:{s%60:02d}"

def open_path(p):
    p = str(p)
    if os.path.isfile(p): p = os.path.dirname(p)
    if sys.platform.startswith("win"): os.startfile(p)
    elif sys.platform == "darwin": subprocess.Popen(["open", p])
    else: subprocess.Popen(["xdg-open", p])

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ThumbCache:
    def __init__(self):
        self.d = {}
    def get(self, url):
        if url in self.d: return self.d[url]
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            im.thumbnail((160, 90))
            img = ctk.CTkImage(light_image=im, dark_image=im, size=(120, 68))
            self.d[url] = img
            return img
        except Exception:
            return None

thumbs = ThumbCache()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Playlist → Single Video Downloader")
        self.geometry("980x760")
        self.minsize(760, 560)
        self.videos = []
        self.checks = []
        self.job_id = None
        self.polling = False
        self.prow_widgets = {}
        self.analyzing = False
        self.local_mode = False
        self.local_folder = ""
        self._spin_after = None
        self._thumb_exe = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb")
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, corner_radius=0)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="▶  Playlist Merger", font=("Segoe UI", 20, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=10)
        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.grid(row=0, column=1, padx=10)
        self.theme_sw = ctk.CTkSwitch(btns, text="Light", command=self._theme, onvalue="light", offvalue="dark")
        self.theme_sw.grid(row=0, column=0, padx=6)
        ctk.CTkButton(btns, text="History", width=80, command=self._history).grid(row=0, column=1, padx=4)
        ctk.CTkButton(btns, text="Open folder", width=100, command=lambda: open_path(core.DL_DIR.resolve())).grid(row=0, column=2, padx=4)

        urlf = ctk.CTkFrame(self)
        urlf.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 0))
        urlf.grid_columnconfigure(0, weight=1)
        self.url = ctk.CTkEntry(urlf, placeholder_text="Paste playlist URL or local folder (e.g. D:\\Videos)…")
        self.url.grid(row=0, column=0, sticky="ew", padx=(10, 6), pady=10)
        self.analyze_btn = ctk.CTkButton(urlf, text="Analyze", width=110, command=self._analyze)
        self.analyze_btn.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(urlf, text="Browse", width=70, command=self._browse).grid(row=0, column=2, padx=(0, 6))
        self.opt_q = ctk.CTkOptionMenu(urlf, values=["best", "1080p", "720p", "480p", "360p"], width=100)
        self.opt_q.set("720p"); self.opt_q.grid(row=0, column=3, padx=4)
        self.opt_f = ctk.CTkOptionMenu(urlf, values=["mp4", "mkv"], width=80)
        self.opt_f.set("mp4"); self.opt_f.grid(row=0, column=4, padx=4)
        self.opt_c = ctk.CTkOptionMenu(urlf, values=["1", "2", "3", "4", "5", "6"], width=70)
        self.opt_c.set("3"); self.opt_c.grid(row=0, column=5, padx=(0, 10))
        self.msg = ctk.CTkLabel(urlf, text="", text_color="gray", anchor="w")
        self.msg.grid(row=1, column=0, columnspan=6, sticky="w", padx=12, pady=(0, 8))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=10)
        body.grid_columnconfigure(0, weight=1); body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(1, weight=1)
        lf = ctk.CTkFrame(left, fg_color="transparent")
        lf.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self.pl_label = ctk.CTkLabel(lf, text="Videos", font=("Segoe UI", 14, "bold"))
        self.pl_label.pack(side="left")
        ctk.CTkButton(lf, text="All", width=50, command=lambda: self._sel(True)).pack(side="right", padx=2)
        ctk.CTkButton(lf, text="None", width=55, command=lambda: self._sel(False)).pack(side="right", padx=2)
        self.vscroll = ctk.CTkScrollableFrame(left, label_text="")
        self.vscroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))
        dlrow = ctk.CTkFrame(left, fg_color="transparent")
        dlrow.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        dlrow.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(dlrow, text="⬇ Download + Merge", height=38, command=self._download).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.verify_btn = ctk.CTkButton(dlrow, text="Verify ✓", width=90, height=38, command=self._verify)
        self.verify_btn.grid(row=0, column=1)

        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.grid_columnconfigure(0, weight=1); right.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(right, text="Progress", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        of = ctk.CTkFrame(right, fg_color="transparent")
        of.grid(row=1, column=0, sticky="ew", padx=12)
        of.grid_columnconfigure(0, weight=1)
        self.o_pct = ctk.CTkLabel(of, text="0%  ·  0 done · 0 failed", anchor="w")
        self.o_pct.grid(row=0, column=0, sticky="w")
        self.o_speed = ctk.CTkLabel(of, text="—", text_color="gray")
        self.o_speed.grid(row=0, column=1, sticky="e")
        self.o_bar = ctk.CTkProgressBar(of); self.o_bar.set(0)
        self.o_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
        self.o_sub = ctk.CTkLabel(of, text="", text_color="gray", anchor="w")
        self.o_sub.grid(row=2, column=0, columnspan=2, sticky="w")
        bf = ctk.CTkFrame(right, fg_color="transparent")
        bf.grid(row=3, column=0, sticky="ew", padx=12, pady=8)
        ctk.CTkButton(bf, text="Cancel", width=80, fg_color="#7f1d1d", hover_color="#991b1b", command=self._cancel).pack(side="left", padx=2)
        ctk.CTkButton(bf, text="Retry failed", width=100, command=self._retry).pack(side="left", padx=2)
        ctk.CTkButton(bf, text="Re-merge", width=90, command=self._remerge).pack(side="left", padx=2)
        self.open_btn = ctk.CTkButton(bf, text="Open result", width=100, command=self._open_result, state="disabled")
        self.open_btn.pack(side="left", padx=2)
        self.pscroll = ctk.CTkScrollableFrame(right, label_text="")
        self.pscroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _theme(self):
        ctk.set_appearance_mode(self.theme_sw.get())

    def _sel(self, v):
        for _, var in self.checks:
            var.set(v)

    def _browse(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Select folder with videos to merge")
        if d:
            self.url.delete(0, "end")
            self.url.insert(0, d)
            self._analyze()

    def _is_local_path(self, s):
        import re as _re
        s = (s or "").strip().strip('"').strip("'")
        if not s or s.startswith("http"):
            return False
        if _re.match(r"^[A-Za-z]:[\\/]", s):
            return True
        try:
            return Path(s.expanduser() if hasattr(s, "expanduser") else s).exists() if False else __import__("os").path.isdir(s)
        except Exception:
            return False

    def _analyze(self):
        if self.analyzing:
            return
        url = self.url.get().strip().strip('"').strip("'")
        if not url:
            self.msg.configure(text="Paste a playlist URL or folder path first.")
            return
        # Local folder mode — instant, no download
        import os as _os
        if _os.path.isdir(url):
            self.local_mode = True
            self.local_folder = url
            try:
                info = core.list_local_files(url)
                self._show_local(info)
            except Exception as e:
                self.msg.configure(text=f"Folder error: {e}")
            return
        self.local_mode = False
        self.analyzing = True
        self.analyze_btn.configure(state="disabled", text="Working…")
        self.msg.configure(text="Analyzing…")
        self._spin(0)
        threading.Thread(target=self._analyze_bg, args=(url,), daemon=True).start()

    def _show_local(self, info):
        self.videos = info["videos"]
        self.local_folder = info.get("folder", self.local_folder)
        self.pl_label.configure(text=f'📁 {info["title"]} ({info["count"]} files)')
        self.msg.configure(text=f"Found {info['count']} local files in {self.local_folder}. Tick order = merge order. Same type = instant merge.")
        for w in self.vscroll.winfo_children(): w.destroy()
        self.checks = []
        self._broken_ids = set()
        self._pending_videos = list(enumerate(self.videos))
        self._add_local_batch()

    def _spin(self, n):
        if not self.analyzing:
            return
        dots = "." * (1 + n % 3)
        try:
            self.msg.configure(text=f"Analyzing{dots} (UI stays responsive)")
        except Exception:
            pass
        self._spin_after = self.after(400, lambda: self._spin(n + 1))

    def _analyze_done(self):
        self.analyzing = False
        if self._spin_after:
            try:
                self.after_cancel(self._spin_after)
            except Exception:
                pass
            self._spin_after = None
        try:
            self.analyze_btn.configure(state="normal", text="Analyze")
        except Exception:
            pass

    def _analyze_bg(self, url):
        try:
            info = core.analyze_playlist(url)
            self.after(0, lambda: (self._analyze_done(), self._show_videos(info)))
        except Exception as e:
            err = str(e)[:200] + " — press Analyze again to retry"
            self.after(0, lambda m=err: (self._analyze_done(), self.msg.configure(text=f"Analyze failed: {m}")))

    def _show_videos(self, info):
        self.videos = info["videos"]
        unav = info.get("unavailable", 0)
        self.pl_label.configure(text=f'{info["title"]} ({info["count"]})')
        warn = f" · {unav} unavailable/private skipped — press Analyze to retry" if unav else ""
        self.msg.configure(text=f"Found {info['count']} videos. Tick to select.{warn}")
        for w in self.vscroll.winfo_children(): w.destroy()
        self.checks = []
        self._pending_videos = list(enumerate(self.videos))
        self._add_video_batch()
        # auto-uncheck private/deleted so they never waste download time
        # (applied after rows are built via _verify-style flag)
        self._broken_ids = {v["id"] for v in self.videos if v.get("broken")}

    def _add_local_batch(self, batch=30):
        for _ in range(min(batch, len(self._pending_videos))):
            i, v = self._pending_videos.pop(0)
            row = ctk.CTkFrame(self.vscroll)
            row.pack(fill="x", pady=3)
            var = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(row, text="", variable=var, width=24).pack(side="left", padx=6)
            txt = ctk.CTkLabel(row, text=f"#{i+1} {v['title'][:80]}\n{v.get('ext','')} · {fmtB(v.get('size',0))} · {v.get('filepath','')[-80:]}", anchor="w", justify="left", wraplength=320)
            txt.pack(side="left", padx=6, fill="x", expand=True)
            self.checks.append((v, var))
        if self._pending_videos:
            self.after(10, self._add_local_batch)

    def _verify(self):
        if getattr(self, "local_mode", False):
            self.msg.configure(text="Local files need no verify — all exist. Press Merge.")
            return
        sel = [v for v, var in self.checks if var.get()]
        if not sel:
            self.msg.configure(text="Select at least one video to verify.")
            return
        self.msg.configure(text=f"Verifying {len(sel)} videos before download… (auto-unticks failures)")
        self.verify_btn.configure(state="disabled", text="Checking…")
        def bg():
            try:
                res = core.precheck_videos(sel, self.opt_q.get(), 6)
                bad = {r["id"] for r in res if not r.get("ok")}
                def done():
                    n_bad = 0
                    for v, var in self.checks:
                        if v["id"] in bad:
                            var.set(False)
                            n_bad += 1
                    if n_bad:
                        self.msg.configure(text=f"⚠ {n_bad} will fail — unticked. Untick stays, or press Analyze to retry list, then Download.")
                    else:
                        self.msg.configure(text=f"✓ All {len(sel)} look downloadable. Safe to Download.")
                    self.verify_btn.configure(state="normal", text="Verify ✓")
                self.after(0, done)
            except Exception as e:
                self.after(0, lambda: (self.msg.configure(text=f"Verify error: {e} — press Verify again"),
                                       self.verify_btn.configure(state="normal", text="Verify ✓")))
        threading.Thread(target=bg, daemon=True).start()

    def _add_video_batch(self, batch=12):
        broken = getattr(self, "_broken_ids", set()) or set()
        for _ in range(min(batch, len(self._pending_videos))):
            i, v = self._pending_videos.pop(0)
            row = ctk.CTkFrame(self.vscroll)
            row.pack(fill="x", pady=3)
            is_broken = v.get("broken") or v["id"] in broken
            var = ctk.BooleanVar(value=not is_broken)
            ctk.CTkCheckBox(row, text="", variable=var, width=24).pack(side="left", padx=6)
            imgl = ctk.CTkLabel(row, text="…", width=120, height=68)
            imgl.pack(side="left", padx=4)
            label = f"{v['title'][:90]}\n{fmtD(v.get('duration',0))}" + ("  ⚠ private/deleted" if is_broken else "")
            txt = ctk.CTkLabel(row, text=label, anchor="w", justify="left", wraplength=260,
                               text_color="gray" if is_broken else ("white", "white"))
            txt.pack(side="left", padx=6, fill="x", expand=True)
            self.checks.append((v, var))
            self._thumb_exe.submit(self._thumb_bg, v.get("thumbnail", ""), imgl)
        if self._pending_videos:
            self.msg.configure(text=f"Loading {len(self.checks)}/{len(self.videos)}…")
            self.after(10, self._add_video_batch)

    def _thumb_bg(self, url, label):
        if not url:
            return
        img = thumbs.get(url)
        if img:
            try:
                if label.winfo_exists():
                    self.after(0, lambda l=label, im=img: l.configure(text="", image=im) if l.winfo_exists() else None)
            except Exception:
                pass

    def _download(self):
        sel = [v for v, var in self.checks if var.get()]
        if not sel:
            self.msg.configure(text="Select at least one video.")
            return
        if getattr(self, "local_mode", False):
            self.msg.configure(text=f"Merging {len(sel)} local files… (instant if same type)")
        else:
            self.msg.configure(text=f"Starting {len(sel)} downloads…")
        self.open_btn.configure(state="disabled")
        for w in self.pscroll.winfo_children(): w.destroy()
        self.prow_widgets = {}
        for v in sel:
            r = ctk.CTkFrame(self.pscroll); r.pack(fill="x", pady=2, padx=2)
            t = ctk.CTkLabel(r, text=f"#{v['id'][:6]} {v['title'][:70]}", anchor="w")
            t.pack(fill="x", padx=8, pady=(6,0))
            b = ctk.CTkProgressBar(r); b.set(0); b.pack(fill="x", padx=8, pady=2)
            s = ctk.CTkLabel(r, text="queued", text_color="gray", anchor="w")
            s.pack(fill="x", padx=8, pady=(0,6))
            self.prow_widgets[v["id"]] = (b, s)
        threading.Thread(target=self._dl_bg, args=(sel,), daemon=True).start()

    def _dl_bg(self, sel):
        if getattr(self, "local_mode", False):
            job = core.create_local_job(self.local_folder, sel, self.opt_f.get())
        else:
            job = core.create_job(self.url.get().strip(), self.pl_label.cget("text"), sel,
                                  self.opt_q.get(), self.opt_f.get(), int(self.opt_c.get()))
        self.job_id = job["id"]
        self.after(0, self._poll)

    def _poll(self):
        self.polling = True
        job = core.get_job(self.job_id)
        if not job:
            self.after(1000, self._poll); return
        if job.get("status") == "merging" or job.get("merging"):
            import time as _t
            mpct = job.get("merge_pct") or 0
            mmsg = job.get("merge_msg") or f'Merging {job["overall"]["done"]} videos…'
            if mpct <= 0:
                self.o_bar.set((_t.time() % 1.0))
            else:
                self.o_bar.set(mpct / 100)
            self.o_pct.configure(text=f"🔀 Merging… {mpct}%")
            self.o_speed.configure(text="ffmpeg")
            self.o_sub.configure(text=mmsg)
            self.msg.configure(text=f"🔀 {mmsg} — please wait, UI stays responsive")
            self.after(500, self._poll)
            return
        o = job["overall"]
        self.o_bar.set((o["pct"] or 0) / 100)
        self.o_pct.configure(text=f'{o["pct"]}%  ·  {o["done"]} done · {o["failed"]} failed / {o["total_n"]}')
        self.o_speed.configure(text=fmtS(o["speed"]))
        self.o_sub.configure(text=f'{fmtB(o["downloaded"])}{(" / "+fmtB(o["total"])) if o["total"] else ""}  ·  ETA {fmtT(o["eta"])}  ·  {job["status"]}')
        for v in job["videos"]:
            w = self.prow_widgets.get(v["id"])
            if not w: continue
            b, s = w
            b.set((v.get("pct") or 0) / 100)
            err = f'  ❌ {v["error"][:100]}' if v.get("error") else ""
            s.configure(text=f'{v["status"]} {v.get("pct",0)}% · {fmtB(v.get("downloaded",0))} · {fmtS(v.get("speed",0))} · ETA {fmtT(v.get("eta",0))}{err}')
        if job["status"] in ("completed", "completed_with_failures", "failed", "merge_failed", "cancelled"):
            self.polling = False
            self.msg.configure(text=f'Status: {job["status"]}' + (f'  ·  {job["merged_file"]}' if job.get("merged_file") else "") + (f'  ·  {job.get("error","")[:150]}' if job.get("error") else ""))
            if job.get("merged_file") and os.path.exists(job["merged_file"]):
                self.open_btn.configure(state="normal")
            return
        self.after(800, self._poll)

    def _cancel(self):
        if self.job_id: core.cancel_job(self.job_id)

    def _retry(self):
        if self.job_id:
            core.retry_job(self.job_id)
            if not self.polling: self.after(0, self._poll)

    def _remerge(self):
        if not self.job_id: return
        self.msg.configure(text="🔀 Re-merging… please wait")
        if not self.polling: self.after(0, self._poll)
        def bg():
            core.merge_parts(self.job_id)
            job = core.get_job(self.job_id)
            if job and job.get("merged_file"):
                self.after(0, lambda: (self.msg.configure(text=f'Merged: {job["merged_file"]}'), self.open_btn.configure(state="normal")))
        threading.Thread(target=bg, daemon=True).start()

    def _open_result(self):
        job = core.get_job(self.job_id)
        if job and job.get("merged_file"): open_path(job["merged_file"])

    def _history(self):
        win = ctk.CTkToplevel(self)
        win.title("History / Cache"); win.geometry("600x480")
        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 0))
        try:
            ci = core.cache_info()
            cache_txt = f"Cache: {fmtB(ci.get('parts_size',0))} temp ({ci.get('parts_count',0)} parts) · Jobs: {fmtB(ci.get('jobs_size',0))} · Downloads: {fmtB(ci.get('downloads_size',0))}"
        except Exception:
            cache_txt = "Cache info unavailable"
            ci = {}
        info_l = ctk.CTkLabel(top, text=cache_txt, text_color="gray", anchor="w")
        info_l.pack(fill="x", pady=(0, 6))
        btnrow = ctk.CTkFrame(top, fg_color="transparent")
        btnrow.pack(fill="x")
        del_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(btnrow, text="also delete merged video files", variable=del_var, width=20).pack(side="left", padx=(0, 8))

        box = ctk.CTkScrollableFrame(win); box.pack(fill="both", expand=True, padx=12, pady=12)

        def _redraw():
            for w in box.winfo_children():
                w.destroy()
            try:
                ci2 = core.cache_info()
                info_l.configure(text=f"Cache: {fmtB(ci2.get('parts_size',0))} temp ({ci2.get('parts_count',0)} parts) · Jobs: {fmtB(ci2.get('jobs_size',0))} · Downloads: {fmtB(ci2.get('downloads_size',0))}")
            except Exception:
                pass
            items = core.list_history()
            if not items:
                ctk.CTkLabel(box, text="No history yet.", text_color="gray").pack(pady=20)
                return
            for h in items:
                r = ctk.CTkFrame(box); r.pack(fill="x", pady=4)
                ctk.CTkLabel(r, text=f'{h.get("title") or h["id"]}  ·  {h.get("status")}', anchor="w").pack(fill="x", padx=8, pady=(6, 0))
                sub = f'{h["id"]}  ·  {(h.get("overall") or {}).get("done",0)}/{(h.get("overall") or {}).get("total_n",0)}  ·  {h.get("merged_file") or ""}'
                ctk.CTkLabel(r, text=sub, text_color="gray", anchor="w").pack(fill="x", padx=8)
                br = ctk.CTkFrame(r, fg_color="transparent"); br.pack(fill="x", padx=8, pady=6)
                ctk.CTkButton(br, text="Resume / Watch", width=120,
                              command=lambda j=h["id"]: (setattr(self, "job_id", j), win.destroy(), self.after(0, self._poll))).pack(side="left", padx=(0, 6))
                def _del(j=h["id"]):
                    core.delete_job(j, delete_merged=del_var.get())
                    if getattr(self, "job_id", None) == j:
                        self.job_id = None
                    _redraw()
                ctk.CTkButton(br, text="Delete", width=80, fg_color="#7f1d1d", hover_color="#991b1b",
                              command=_del).pack(side="left")

        def _clear_cache():
            core.clear_cache()
            try:
                thumbs.d.clear()
            except Exception:
                pass
            self.msg.configure(text="Cache cleared (temp parts removed, merged videos kept).")
            _redraw()

        def _clear_all():
            core.clear_history(delete_merged=del_var.get())
            self.job_id = None
            self.msg.configure(text="History cleared." + (" Merged files deleted." if del_var.get() else ""))
            _redraw()

        ctk.CTkButton(btnrow, text="Clear cache", width=100, command=_clear_cache).pack(side="left", padx=2)
        ctk.CTkButton(btnrow, text="Clear history", width=110, fg_color="#7f1d1d", hover_color="#991b1b", command=_clear_all).pack(side="left", padx=2)
        _redraw()

if __name__ == "__main__":
    App().mainloop()
