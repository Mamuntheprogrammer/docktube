import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import customtkinter as ctk

import core

BASE = Path(__file__).parent


def fmtB(n):
    if not n:
        return "0 B"
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def fmtS(n):
    return "—" if not n else fmtB(n) + "/s"


def fmtT(s):
    s = int(s or 0)
    if not s:
        return "—"
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s"


def fmtD(s):
    s = int(s or 0)
    return f"{s//60}:{s%60:02d}"


def open_path(p):
    p = str(p)
    if os.path.isfile(p):
        p = os.path.dirname(p)
    if sys.platform.startswith("win"):
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def center_popup(pop, parent, w, h):
    """Place a Toplevel popup in the middle of the parent window."""
    try:
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        pop.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        pop.geometry(f"{w}x{h}")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.geometry("980x760")
        self.minsize(760, 560)
        self.videos = []
        self.checks = []
        self.job_id = None
        self.polling = False
        self.prow_widgets = {}
        self.analyzing = False
        self._spin_after = None
        self.log_lines = []
        self._logged_errors = set()
        self._log_win = None
        self._log_win_box = None
        self._load_pop = None
        self._load_lbl = None
        self._load_prog = None
        self._load_btn = None
        self._load_cancelled = False
        self._checked_url = ""
        self._pending_url = ""
        self._build()
        # Check yt-dlp freshness shortly after the window appears.
        self.after(600, self._check_ytdlp_startup)

    # ------------------------------------------------------------ layout ---
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, corner_radius=0)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="▶  YouTube Downloader", font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=10)
        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.grid(row=0, column=1, padx=10)
        self.theme_sw = ctk.CTkSwitch(btns, text="Light", command=self._theme,
                                      onvalue="light", offvalue="dark")
        self.theme_sw.grid(row=0, column=0, padx=6)
        ctk.CTkButton(btns, text="Log", width=70, command=self._open_log_window).grid(row=0, column=1, padx=4)
        ctk.CTkButton(btns, text="Open folder", width=100,
                      command=lambda: open_path(Path(core.get_download_dir()))).grid(row=0, column=2, padx=4)

        urlf = ctk.CTkFrame(self)
        urlf.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 0))
        urlf.grid_columnconfigure(0, weight=1)
        self.url = ctk.CTkEntry(urlf, placeholder_text="Paste video or playlist URL…  (left-click pastes, right-click menu, Ctrl+V)")
        self.url.grid(row=0, column=0, sticky="ew", padx=(10, 6), pady=10)
        self.analyze_btn = ctk.CTkButton(urlf, text="⬇ Download", width=130, command=self._action)
        self.analyze_btn.grid(row=0, column=1, padx=(0, 6))
        self.paste_btn = ctk.CTkButton(urlf, text="Paste", width=80, command=self._paste_clipboard)
        self.paste_btn.grid(row=0, column=2, padx=(0, 6))
        self.opt_q = ctk.CTkOptionMenu(urlf, values=["best", "1080p", "720p", "480p", "360p"], width=100)
        self.opt_q.set("720p")
        self.opt_q.grid(row=0, column=3, padx=4)
        self.opt_f = ctk.CTkOptionMenu(urlf, values=["mp4", "mkv"], width=80)
        self.opt_f.set("mp4")
        self.opt_f.grid(row=0, column=4, padx=4)
        self.opt_c = ctk.CTkOptionMenu(urlf, values=["1", "2", "3", "4", "5", "6"], width=70)
        self.opt_c.set("3")
        self.opt_c.grid(row=0, column=5, padx=(0, 10))
        self.msg = ctk.CTkLabel(urlf, text="", text_color="gray", anchor="w")
        self.msg.grid(row=1, column=0, columnspan=6, sticky="w", padx=12, pady=(0, 4))
        # ffmpeg warning row (hidden when ffmpeg is available)
        self.ffmpeg_row = ctk.CTkFrame(urlf, fg_color="transparent")
        self.ffmpeg_row.grid(row=2, column=0, columnspan=6, sticky="ew", padx=12, pady=(0, 8))
        self.ffmpeg_lbl = ctk.CTkLabel(self.ffmpeg_row, text="", text_color="#fbbf24", anchor="w")
        self.ffmpeg_lbl.pack(side="left", fill="x", expand=True)
        self.ffmpeg_btn = ctk.CTkButton(self.ffmpeg_row, text="Install ffmpeg", width=120,
                                        command=self._install_ffmpeg)
        self.ffmpeg_btn.pack(side="right")
        # download-folder row (default: ./downloads, changeable)
        self.folder_row = ctk.CTkFrame(urlf, fg_color="transparent")
        self.folder_row.grid(row=3, column=0, columnspan=6, sticky="ew", padx=12, pady=(0, 8))
        self.folder_row.grid_columnconfigure(0, weight=1)
        self.folder_lbl = ctk.CTkLabel(self.folder_row, text="", text_color="gray", anchor="w")
        self.folder_lbl.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(self.folder_row, text="Change…", width=90,
                      command=self._choose_folder).grid(row=0, column=1, padx=(6, 0))
        self._refresh_folder_lbl()
        self._refresh_ffmpeg_row()
        self._wire_url_paste()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=10)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        lf = ctk.CTkFrame(left, fg_color="transparent")
        lf.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self.pl_label = ctk.CTkLabel(lf, text="Videos", font=("Segoe UI", 14, "bold"))
        self.pl_label.pack(side="left")
        ctk.CTkButton(lf, text="All", width=50, command=lambda: self._sel(True)).pack(side="right", padx=2)
        ctk.CTkButton(lf, text="None", width=55, command=lambda: self._sel(False)).pack(side="right", padx=2)
        self.vscroll = ctk.CTkScrollableFrame(left, label_text="")
        self.vscroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(right, text="Progress", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        of = ctk.CTkFrame(right, fg_color="transparent")
        of.grid(row=1, column=0, sticky="ew", padx=12)
        of.grid_columnconfigure(0, weight=1)
        self.o_pct = ctk.CTkLabel(of, text="0%  ·  0 done · 0 failed", anchor="w")
        self.o_pct.grid(row=0, column=0, sticky="w")
        self.o_speed = ctk.CTkLabel(of, text="—", text_color="gray")
        self.o_speed.grid(row=0, column=1, sticky="e")
        self.o_bar = ctk.CTkProgressBar(of)
        self.o_bar.set(0)
        self.o_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
        self.o_sub = ctk.CTkLabel(of, text="", text_color="gray", anchor="w")
        self.o_sub.grid(row=2, column=0, columnspan=2, sticky="w")
        bf = ctk.CTkFrame(right, fg_color="transparent")
        bf.grid(row=3, column=0, sticky="ew", padx=12, pady=8)
        self.cancel_btn = ctk.CTkButton(bf, text="Cancel", width=80, fg_color="#7f1d1d",
                                        hover_color="#991b1b", command=self._cancel,
                                        state="disabled")
        self.cancel_btn.pack(side="left", padx=2)
        self.retry_btn = ctk.CTkButton(bf, text="Retry failed", width=100, command=self._retry,
                                       state="disabled")
        self.retry_btn.pack(side="left", padx=2)
        self.pscroll = ctk.CTkScrollableFrame(right, label_text="")
        self.pscroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        # ------------------------------------------------- inline log panel ---
        logf = ctk.CTkFrame(self)
        logf.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 10))
        logf.grid_columnconfigure(0, weight=1)
        loghead = ctk.CTkFrame(logf, fg_color="transparent")
        loghead.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        ctk.CTkLabel(loghead, text="Log  (full error messages appear here)",
                     font=("Segoe UI", 12, "bold")).pack(side="left")
        ctk.CTkButton(loghead, text="Copy", width=70,
                      command=self._copy_log).pack(side="right", padx=2)
        ctk.CTkButton(loghead, text="Clear", width=70,
                      command=self._clear_log).pack(side="right", padx=2)
        ctk.CTkButton(loghead, text="Pop out", width=80,
                      command=self._open_log_window).pack(side="right", padx=2)
        self.log_box = ctk.CTkTextbox(logf, height=110, state="disabled")
        self.log_box.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.log("Ready. Paste a URL — it will be checked automatically, then press Download.")

    def _theme(self):
        ctk.set_appearance_mode(self.theme_sw.get())

    def _sel(self, v):
        for _, var in self.checks:
            var.set(v)

    # ------------------------------------------------------------ log store ---
    def log(self, msg, level="info"):
        """Append a timestamped line to the inline log + pop-out window."""
        try:
            ts = time.strftime("%H:%M:%S")
            line = f"[{ts}] {msg}"
            self.log_lines.append(line)
            # keep memory bounded
            if len(self.log_lines) > 800:
                self.log_lines = self.log_lines[-800:]
            for box in (getattr(self, "log_box", None), self._log_win_box):
                try:
                    if box is None or not box.winfo_exists():
                        continue
                    box.configure(state="normal")
                    box.insert("end", line + "\n")
                    # trim widget content too
                    try:
                        nlines = int(box.index("end-1c").split(".")[0])
                        if nlines > 900:
                            box.delete("1.0", f"{nlines - 900}.0")
                    except Exception:
                        pass
                    box.see("end")
                    box.configure(state="disabled")
                except Exception:
                    pass
        except Exception:
            pass

    def _copy_log(self):
        try:
            text = "\n".join(self.log_lines)
            self.clipboard_clear()
            self.clipboard_append(text)
            self.msg.configure(text="Log copied to clipboard.")
        except Exception:
            pass

    def _clear_log(self):
        try:
            self.log_lines = []
            self._logged_errors = set()
            for box in (getattr(self, "log_box", None), self._log_win_box):
                try:
                    if box is None or not box.winfo_exists():
                        continue
                    box.configure(state="normal")
                    box.delete("1.0", "end")
                    box.configure(state="disabled")
                except Exception:
                    pass
        except Exception:
            pass

    def _open_log_window(self):
        """Pop-out window showing the full log (for long error messages)."""
        try:
            if self._log_win is not None and self._log_win.winfo_exists():
                self._log_win.lift()
                self._log_win.focus()
                return
        except Exception:
            pass
        win = ctk.CTkToplevel(self)
        win.title("Log — full messages")
        center_popup(win, self, 680, 440)
        win.transient(self)
        ctk.CTkLabel(win, text="Log — full error messages (select + Ctrl+C to copy)",
                     font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        box = ctk.CTkTextbox(win, state="disabled")
        box.pack(fill="both", expand=True, padx=12, pady=4)
        try:
            box.configure(state="normal")
            box.insert("end", "\n".join(self.log_lines) + ("\n" if self.log_lines else ""))
            box.see("end")
            box.configure(state="disabled")
        except Exception:
            pass
        self._log_win = win
        self._log_win_box = box
        btnrow = ctk.CTkFrame(win, fg_color="transparent")
        btnrow.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(btnrow, text="Copy all", width=100,
                      command=self._copy_log).pack(side="left", padx=2)
        ctk.CTkButton(btnrow, text="Clear", width=80,
                      command=self._clear_log).pack(side="left", padx=2)
        ctk.CTkButton(btnrow, text="Close", width=80,
                      command=win.destroy).pack(side="right", padx=2)

    def _show_error_popup(self, title, message):
        """Show one full error message in its own window."""
        try:
            win = ctk.CTkToplevel(self)
            win.title("Error details")
            center_popup(win, self, 560, 300)
            win.transient(self)
            ctk.CTkLabel(win, text=title[:90],
                         font=("Segoe UI", 13, "bold"),
                         anchor="w", justify="left",
                         wraplength=520).pack(fill="x", padx=14, pady=(14, 4))
            box = ctk.CTkTextbox(win, state="disabled")
            box.pack(fill="both", expand=True, padx=14, pady=4)
            box.configure(state="normal")
            box.insert("end", message or "(no message)")
            box.see("end")
            box.configure(state="disabled")
            btnrow = ctk.CTkFrame(win, fg_color="transparent")
            btnrow.pack(fill="x", padx=14, pady=(0, 14))
            ctk.CTkButton(btnrow, text="Copy", width=90, command=lambda: (
                self.clipboard_clear(), self.clipboard_append(message or ""))).pack(side="left")
            ctk.CTkButton(btnrow, text="Close", width=90,
                          command=win.destroy).pack(side="right")
            self.log(f"Opened details: {title} — {message[:200]}")
        except Exception:
            pass

    # ------------------------------------------------- URL paste helpers ---
    def _wire_url_paste(self):
        """Left-click pastes, right-click shows Cut/Copy/Paste menu."""
        try:
            # Left mouse button: auto-paste clipboard if the field is empty.
            self.url.bind("<Button-1>", self._on_url_left_click, add="+")
            # Middle-click (X11 paste convention) always pastes.
            self.url.bind("<Button-2>", lambda e: (self._paste_clipboard(), "break")[1], add="+")
            # Right-click context menu (Windows/Linux). macOS uses Button-2.
            self.url.bind("<Button-3>", self._show_url_menu, add="+")
            if sys.platform == "darwin":
                self.url.bind("<Button-2>", self._show_url_menu, add="+")
                self.url.bind("<Control-Button-1>", self._show_url_menu, add="+")
            # Enter = Download (check first if needed).
            self.url.bind("<Return>", lambda e: (self._action(), "break")[1], add="+")
        except Exception:
            pass

    def _clipboard_text(self):
        try:
            t = self.clipboard_get()
        except Exception:
            return ""
        return (t or "").strip().strip('"').strip("'")

    def _paste_clipboard(self):
        t = self._clipboard_text()
        if not t:
            self.msg.configure(text="Clipboard is empty — copy a URL first.")
            return False
        try:
            self.url.delete(0, "end")
            self.url.insert(0, t)
            self.url.focus_set()
            self.msg.configure(text="URL pasted — checking…")
            # Auto-check with a loading popup right after pasting.
            self.after(100, lambda: self._analyze(auto_download=False))
            return True
        except Exception:
            return False

    def _on_url_left_click(self, event=None):
        """Single left-click pastes when the URL field is empty.

        Lets normal cursor placement work when text is already present.
        """
        try:
            if (self.url.get() or "").strip():
                return None  # normal click: place cursor / select
            t = self._clipboard_text()
            if not t:
                return None
            # Only auto-paste URL-like text to avoid clobbering typing.
            if not ("http" in t or "youtu" in t or "watch" in t or "." in t):
                return None
            self.after(0, self._paste_clipboard)
        except Exception:
            pass
        return None

    def _show_url_menu(self, event=None):
        try:
            import tkinter as tk
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label="Paste", command=self._paste_clipboard)
            menu.add_command(label="Select all",
                             command=lambda: (self.url.focus_set(), self.url.select_range(0, "end")))
            menu.add_command(label="Copy",
                             command=lambda: self.event_generate("<<Copy>>"))
            menu.add_command(label="Cut",
                             command=lambda: (self.event_generate("<<Cut>>")))
            menu.add_command(label="Clear",
                             command=lambda: self.url.delete(0, "end"))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        except Exception:
            pass
        return "break"

    # -------------------------------------------------- download folder ---
    def _refresh_folder_lbl(self):
        try:
            self.folder_lbl.configure(text=f"Save to: {core.get_download_dir()}")
        except Exception:
            pass

    def _choose_folder(self):
        try:
            from tkinter import filedialog
            cur = core.get_download_dir()
            sel = filedialog.askdirectory(initialdir=cur, title="Choose download folder",
                                          mustexist=False)
            if not sel:
                return
            ok, msg = core.set_download_dir(sel)
            self._refresh_folder_lbl()
            if ok:
                self.msg.configure(text=f"Download folder: {msg}")
                self.log(f"Download folder set to: {msg}")
            else:
                self.msg.configure(text=f"Could not use folder: {msg}")
                self.log(f"[FAIL] Could not set download folder: {msg}", "error")
        except Exception as e:
            self.log(f"[FAIL] Folder picker error: {e}", "error")

    # ------------------------------------------------------- ffmpeg banner ---
    def _refresh_ffmpeg_row(self):
        try:
            ff = getattr(core, "FFMPEG", None) or core.resolve_ffmpeg()
            if ff:
                self.ffmpeg_row.grid_remove()
            else:
                self.ffmpeg_row.grid()
                self.ffmpeg_lbl.configure(
                    text="⚠ ffmpeg not found — HD videos (like this one) have no single-file "
                         "format and need ffmpeg to merge. One click installs it (no admin).")
                self.ffmpeg_btn.configure(state="normal", text="Install ffmpeg")
        except Exception:
            pass

    def _install_ffmpeg(self):
        self.ffmpeg_btn.configure(state="disabled", text="Installing…")
        self.ffmpeg_lbl.configure(text="Getting ffmpeg (≈25 MB, one time)… please wait.")

        def bg():
            ok, msg = core.ensure_ffmpeg_via_imageio()
            def done():
                self._refresh_ffmpeg_row()
                if ok:
                    self.msg.configure(text=f"ffmpeg ready: {msg} — HD downloads will now merge.")
                    try:
                        self.ffmpeg_row.grid_remove()
                    except Exception:
                        pass
                else:
                    self.ffmpeg_lbl.configure(text=f"ffmpeg install failed: {msg}")
                    self.ffmpeg_btn.configure(state="normal", text="Retry install")
            self.after(0, done)
        threading.Thread(target=bg, daemon=True).start()

    # ----------------------------------------------- yt-dlp update popup ---
    def _check_ytdlp_startup(self):
        """On every launch: is yt-dlp installed + up to date?

        First install (missing) -> auto-install popup.
        Outdated -> popup offering one-click update.
        """
        pop = ctk.CTkToplevel(self)
        pop.title("yt-dlp check")
        center_popup(pop, self, 420, 190)
        pop.transient(self)
        pop.grab_set()
        lbl = ctk.CTkLabel(pop, text="Checking yt-dlp…", wraplength=380, anchor="w", justify="left")
        lbl.pack(fill="x", padx=16, pady=(16, 8))
        prog = ctk.CTkProgressBar(pop, mode="indeterminate")
        prog.pack(fill="x", padx=16, pady=4)
        prog.start()
        row = ctk.CTkFrame(pop, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)
        ok_btn = ctk.CTkButton(row, text="OK", width=100, command=pop.destroy, state="disabled")
        ok_btn.pack(side="right", padx=4)
        upd_btn = ctk.CTkButton(row, text="Update now", width=120, state="disabled")
        upd_btn.pack(side="right", padx=4)

        def bg():
            inst = core.installed_ytdlp_version()
            if not inst:
                # First install: yt-dlp missing -> auto download it.
                self.after(0, lambda: lbl.configure(
                    text="yt-dlp is not installed.\nDownloading and installing it now…"))
                ok, msg = core.update_ytdlp()
                now = core.installed_ytdlp_version()
                def done():
                    prog.stop()
                    if ok and now:
                        lbl.configure(text=f"yt-dlp {now} installed successfully.\nYou can start downloading.")
                    else:
                        lbl.configure(text=f"Could not install yt-dlp.\n{msg}\nRun: pip install -U yt-dlp")
                    ok_btn.configure(state="normal")
                    try:
                        pop.lift()
                        pop.focus()
                    except Exception:
                        pass
                self.after(0, done)
                return
            latest = core.latest_ytdlp_version()
            def done2():
                prog.stop()
                if not latest:
                    lbl.configure(text=f"yt-dlp {inst} is installed.\n"
                                       "Could not reach PyPI to check for updates (offline?).")
                    ok_btn.configure(state="normal")
                    return
                if latest == inst:
                    lbl.configure(text=f"yt-dlp is up to date (v{inst}).")
                    ok_btn.configure(state="normal")
                    # auto-close when everything is fine
                    self.after(1500, lambda: (pop.grab_release(), pop.destroy()) if pop.winfo_exists() else None)
                else:
                    try:
                        from core import _ver_tuple
                        newer = _ver_tuple(latest) > _ver_tuple(inst)
                    except Exception:
                        newer = True
                    if not newer:
                        lbl.configure(text=f"yt-dlp is up to date (v{inst}).")
                        ok_btn.configure(state="normal")
                        self.after(1500, lambda: (pop.grab_release(), pop.destroy()) if pop.winfo_exists() else None)
                        return
                    lbl.configure(text=f"yt-dlp update available:\ninstalled v{inst}  →  latest v{latest}\n"
                                       "Update now for the latest site fixes?")
                    ok_btn.configure(state="normal", text="Later")
                    upd_btn.configure(state="normal")

                    def do_update():
                        upd_btn.configure(state="disabled", text="Updating…")
                        ok_btn.configure(state="disabled")
                        lbl.configure(text=f"Updating yt-dlp {inst} → {latest}…\nPlease wait.")
                        def bg2():
                            ok, msg = core.update_ytdlp()
                            now = core.installed_ytdlp_version() or inst
                            def fin():
                                upd_btn.configure(state="disabled", text="Update now")
                                ok_btn.configure(state="normal", text="OK")
                                if ok:
                                    lbl.configure(text=f"Updated to yt-dlp v{now}.\nRestart the app if downloads behave oddly.")
                                else:
                                    lbl.configure(text=f"Update failed.\n{msg}\nTry: pip install -U yt-dlp")
                            self.after(0, fin)
                        threading.Thread(target=bg2, daemon=True).start()
                    upd_btn.configure(command=do_update)
            self.after(0, done2)

        threading.Thread(target=bg, daemon=True).start()

    # --------------------------------------------- loading popup + action ---
    def _open_loading_popup(self, url, auto_download):
        """Modal 'Checking link…' popup shown during auto-check."""
        try:
            self._close_loading_popup()
        except Exception:
            pass
        self._load_cancelled = False
        pop = ctk.CTkToplevel(self)
        pop.title("Loading…")
        center_popup(pop, self, 420, 180)
        pop.transient(self)
        pop.grab_set()
        pop.protocol("WM_DELETE_WINDOW", self._cancel_loading)
        what = "Checking link, then downloading…" if auto_download else "Checking link…"
        lbl = ctk.CTkLabel(pop, text=f"{what}\n{url[:90]}",
                           wraplength=380, anchor="w", justify="left")
        lbl.pack(fill="x", padx=16, pady=(16, 8))
        prog = ctk.CTkProgressBar(pop, mode="indeterminate")
        prog.pack(fill="x", padx=16, pady=4)
        prog.start()
        btnrow = ctk.CTkFrame(pop, fg_color="transparent")
        btnrow.pack(fill="x", padx=16, pady=12)
        btn = ctk.CTkButton(btnrow, text="Cancel", width=100, command=self._cancel_loading)
        btn.pack(side="right")
        self._load_pop = pop
        self._load_lbl = lbl
        self._load_prog = prog
        self._load_btn = btn

    def _close_loading_popup(self):
        for attr in ("_load_prog",):
            try:
                p = getattr(self, attr, None)
                if p is not None and p.winfo_exists():
                    p.stop()
            except Exception:
                pass
        try:
            pop = getattr(self, "_load_pop", None)
            if pop is not None and pop.winfo_exists():
                try:
                    pop.grab_release()
                except Exception:
                    pass
                pop.destroy()
        except Exception:
            pass
        self._load_pop = None
        self._load_lbl = None
        self._load_prog = None
        self._load_btn = None

    def _cancel_loading(self):
        """User cancelled the check — ignore the background result."""
        self._load_cancelled = True
        try:
            self._close_loading_popup()
        except Exception:
            pass
        self._analyze_done()
        self.msg.configure(text="Check cancelled.")
        self.log("Check cancelled by user.")

    # -------------------------------------------------------------- action ---
    def _action(self):
        """Single action button: check (loading popup) then download."""
        if self.analyzing:
            return
        url = core.normalize_url(self.url.get())
        if not url:
            # One more chance: clipboard may hold the URL (left-click paste).
            clip = self._clipboard_text()
            if clip:
                self.url.delete(0, "end")
                self.url.insert(0, clip)
                url = core.normalize_url(clip)
            if not url:
                self.msg.configure(text="Paste a video or playlist URL first, then press Download.")
                return
        else:
            # keep the normalized form visible
            try:
                if url != self.url.get().strip():
                    self.url.delete(0, "end")
                    self.url.insert(0, url)
            except Exception:
                pass
        # Already checked this exact URL with videos listed -> download now.
        if url == getattr(self, "_checked_url", "") and self.checks:
            self._download()
            return
        self._analyze(auto_download=True, url=url)

    def _analyze(self, auto_download=False, url=None):
        if self.analyzing:
            return
        if url is None:
            url = core.normalize_url(self.url.get())
            if not url:
                clip = self._clipboard_text()
                if clip:
                    self.url.delete(0, "end")
                    self.url.insert(0, clip)
                    url = core.normalize_url(clip)
                if not url:
                    self.msg.configure(text="Paste a video or playlist URL first, then press Download.")
                    return
            else:
                try:
                    if url != self.url.get().strip():
                        self.url.delete(0, "end")
                        self.url.insert(0, url)
                except Exception:
                    pass
        self._pending_url = url
        self.analyzing = True
        self._load_cancelled = False
        self.analyze_btn.configure(state="disabled", text="Working…")
        self.msg.configure(text="Checking…")
        self._open_loading_popup(url, auto_download)
        self._spin(0)
        threading.Thread(target=self._analyze_bg, args=(url, auto_download), daemon=True).start()

    def _spin(self, n):
        if not self.analyzing:
            return
        dots = "." * (1 + n % 3)
        try:
            pop = getattr(self, "_load_pop", None)
            lbl = getattr(self, "_load_lbl", None)
            if pop is not None and pop.winfo_exists() and lbl is not None:
                lbl.configure(text=f"Checking{dots}\n{(getattr(self, '_pending_url', '') or '')[:90]}")
            else:
                self.msg.configure(text=f"Checking{dots} (UI stays responsive)")
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
            self.analyze_btn.configure(state="normal", text="⬇ Download")
        except Exception:
            pass

    def _analyze_bg(self, url, auto_download):
        try:
            info = core.analyze_playlist(url)
            self.after(0, lambda: self._on_analyze_ok(info, auto_download))
        except Exception as e:
            full = str(e)
            err = full[:200]
            self.after(0, lambda: self._on_analyze_fail(url, err, full))

    def _on_analyze_ok(self, info, auto_download):
        if getattr(self, "_load_cancelled", False):
            return
        try:
            self._close_loading_popup()
        except Exception:
            pass
        self._analyze_done()
        self._show_videos(info)
        self.log(f"Check OK: {info.get('title', '')[:80]} ({info.get('count', 0)} videos)")
        if auto_download:
            # The video list fills in batches — wait for it, then download.
            self._wait_for_list_and_download()

    def _wait_for_list_and_download(self, tries=100):
        if getattr(self, "_load_cancelled", False):
            return
        try:
            pending = getattr(self, "_pending_videos", [])
            if pending:
                if tries <= 0:
                    self.msg.configure(text="Listing timed out — press Download to retry.")
                    return
                self.after(200, lambda: self._wait_for_list_and_download(tries - 1))
                return
        except Exception:
            pass
        try:
            if [v for v, var in self.checks if var.get()]:
                self._download()
            else:
                self.msg.configure(text="Nothing downloadable found — see Log.")
        except Exception:
            pass

    def _on_analyze_fail(self, url, err, full):
        if getattr(self, "_load_cancelled", False):
            return
        self._analyze_done()
        self.log(f"[FAIL] Check failed for {url}: {full}", "error")
        # Keep the popup open showing the error (instead of a bare msg line).
        try:
            prog = getattr(self, "_load_prog", None)
            if prog is not None and prog.winfo_exists():
                prog.stop()
            lbl = getattr(self, "_load_lbl", None)
            if lbl is not None and lbl.winfo_exists():
                lbl.configure(text=f"❌ Check failed:\n{err}\n— fix the link and try again")
            btn = getattr(self, "_load_btn", None)
            if btn is not None and btn.winfo_exists():
                btn.configure(text="Close", command=self._close_loading_popup)
            return
        except Exception:
            pass
        self.msg.configure(text=f"Check failed: {err} — press Download again to retry")

    def _show_videos(self, info):
        self.videos = info["videos"]
        self._checked_url = getattr(self, "_pending_url", "") or core.normalize_url(self.url.get())
        unav = info.get("unavailable", 0)
        single = info.get("count", 0) == 1
        cnt = info.get("count", 0)
        label_txt = info["title"][:60] + (" (video)" if single else f" ({cnt} videos)")
        self.pl_label.configure(text=label_txt)
        warn = f" · {unav} unavailable/private skipped" if unav else ""
        kind = "Single video found. Press Download." if single else f'Found {info["count"]} videos. Tick to select, then press Download.'
        self.msg.configure(text=kind + warn)
        for w in self.vscroll.winfo_children():
            w.destroy()
        self.checks = []
        self._pending_videos = list(enumerate(self.videos))
        self._add_video_batch()
        self._broken_ids = {v["id"] for v in self.videos if v.get("broken")}

    def _add_video_batch(self, batch=12):
        broken = getattr(self, "_broken_ids", set()) or set()
        for _ in range(min(batch, len(self._pending_videos))):
            i, v = self._pending_videos.pop(0)
            row = ctk.CTkFrame(self.vscroll)
            row.pack(fill="x", pady=3)
            is_broken = v.get("broken") or v["id"] in broken
            var = ctk.BooleanVar(value=not is_broken)
            ctk.CTkCheckBox(row, text="", variable=var, width=24).pack(side="left", padx=6)
            label = f"#{i+1} {v['title'][:90]}\n{fmtD(v.get('duration', 0))}" + ("  ⚠ private/deleted" if is_broken else "")
            txt = ctk.CTkLabel(row, text=label, anchor="w", justify="left", wraplength=380,
                               text_color="gray" if is_broken else ("white", "white"))
            txt.pack(side="left", padx=6, fill="x", expand=True)
            self.checks.append((v, var))
        if self._pending_videos:
            self.msg.configure(text=f"Loading {len(self.checks)}/{len(self.videos)}…")
            self.after(10, self._add_video_batch)

    # ------------------------------------------------------------- download ---
    def _download(self):
        sel = [v for v, var in self.checks if var.get()]
        if not sel:
            self.msg.configure(text="Select at least one video.")
            return
        self.msg.configure(
            text=f"Downloading {len(sel)} video{'s' if len(sel) != 1 else ''}… "
                 f"each saved separately in {Path(core.get_download_dir()).name}/")
        for w in self.pscroll.winfo_children():
            w.destroy()
        self.prow_widgets = {}
        for v in sel:
            r = ctk.CTkFrame(self.pscroll)
            r.pack(fill="x", pady=2, padx=2)
            t = ctk.CTkLabel(r, text=f"#{v['id'][:6]} {v['title'][:70]}", anchor="w")
            t.pack(fill="x", padx=8, pady=(6, 0))
            b = ctk.CTkProgressBar(r)
            b.set(0)
            b.pack(fill="x", padx=8, pady=2)
            brow = ctk.CTkFrame(r, fg_color="transparent")
            brow.pack(fill="x", padx=8, pady=(0, 6))
            brow.grid_columnconfigure(0, weight=1)
            s = ctk.CTkLabel(brow, text="queued", text_color="gray", anchor="w")
            s.grid(row=0, column=0, sticky="ew")
            det = ctk.CTkButton(brow, text="Details", width=70, state="disabled")
            det.grid(row=0, column=1, padx=(6, 0))
            vid = v["id"]
            # Clicking the status text or Details opens the FULL error.
            def _open(vid=vid):
                job = core.get_job(self.job_id) if self.job_id else None
                vv = next((x for x in (job["videos"] if job else []) if x["id"] == vid), None)
                if vv is None:
                    vv = next((x for x, _ in self.checks if x["id"] == vid), None) or {"id": vid, "title": vid}
                if vv.get("error"):
                    self._show_video_error(vv)
                else:
                    self._open_log_window()
            det.configure(command=_open)
            try:
                s.bind("<Button-1>", lambda e, f=_open: (f(), "break")[1], add="+")
            except Exception:
                pass
            self.prow_widgets[v["id"]] = (b, s, det)
        threading.Thread(target=self._dl_bg, args=(sel,), daemon=True).start()
        self.log(f"Download started: {len(sel)} video(s), quality={self.opt_q.get()}, "
                 f"format={self.opt_f.get()}.")
        try:
            self.cancel_btn.configure(state="normal")
            self.retry_btn.configure(state="disabled")
        except Exception:
            pass

    def _show_video_error(self, video):
        title = video.get("title", video.get("id", "video"))
        msg = video.get("error") or "(no error message)"
        url = video.get("url", "")
        self._show_error_popup(f"❌ {title}",
                               f"Video: {title}\nID: {video.get('id')}\nURL: {url}\n"
                               f"Status: {video.get('status')}\n\nError:\n{msg}")

    def _dl_bg(self, sel):
        job = core.create_job(core.normalize_url(self.url.get()), self.pl_label.cget("text"), sel,
                              self.opt_q.get(), self.opt_f.get(), int(self.opt_c.get()))
        self.job_id = job["id"]
        self.after(0, self._poll)

    def _poll(self):
        self.polling = True
        job = core.get_job(self.job_id)
        if not job:
            self.after(1000, self._poll)
            return
        o = job["overall"]
        self.o_bar.set((o["pct"] or 0) / 100)
        self.o_pct.configure(text=f'{o["pct"]}%  ·  {o["done"]} done · {o["failed"]} failed / {o["total_n"]}')
        self.o_speed.configure(text=fmtS(o["speed"]))
        self.o_sub.configure(
            text=f'{fmtB(o["downloaded"])}{(" / " + fmtB(o["total"])) if o["total"] else ""}  ·  '
                 f'ETA {fmtT(o["eta"])}  ·  {job["status"]}')
        for v in job["videos"]:
            w = self.prow_widgets.get(v["id"])
            if not w:
                continue
            # rows created before this patch store (bar, label); new rows store (bar, label, details btn)
            b, s = w[0], w[1]
            det = w[2] if len(w) > 2 else None
            b.set((v.get("pct") or 0) / 100)
            err = f'  ❌ {v["error"][:100]}' if v.get("error") else ""
            try:
                if v.get("status") == "failed" and v.get("error"):
                    s.configure(text=f'{v["status"]} {v.get("pct", 0)}% · {fmtB(v.get("downloaded", 0))} · '
                                     f'{fmtS(v.get("speed", 0))} · ETA {fmtT(v.get("eta", 0))}{err}  (click for full)',
                                text_color="#f87171")
                else:
                    s.configure(text=f'{v["status"]} {v.get("pct", 0)}% · {fmtB(v.get("downloaded", 0))} · '
                                     f'{fmtS(v.get("speed", 0))} · ETA {fmtT(v.get("eta", 0))}{err}')
            except Exception:
                s.configure(text=f'{v["status"]} {v.get("pct", 0)}%{err}')
            # Log each failure ONCE with the FULL message + enable Details.
            if v.get("status") == "failed" and v.get("error"):
                key = (job["id"], v["id"], v.get("error"))
                if key not in self._logged_errors:
                    self._logged_errors.add(key)
                    self.log(f"[FAIL] {v.get('title', v['id'])} [{v['id']}]: {v.get('error')}", "error")
                try:
                    if det is not None:
                        det.configure(state="normal")
                except Exception:
                    pass
            elif v.get("status") == "done":
                key = (job["id"], v["id"], "done")
                if key not in self._logged_errors:
                    self._logged_errors.add(key)
                    fp = v.get("filepath") or ""
                    self.log(f"[OK] {v.get('title', v['id'])} [{v['id']}] -> {fp}")
        if job["status"] in ("completed", "completed_with_failures", "failed", "cancelled"):
            self.polling = False
            files = [v.get("filepath") for v in job["videos"] if v.get("status") == "done"]
            fails = [v for v in job["videos"] if v.get("status") == "failed"]
            tail = f"  ·  {len(files)} file(s) in {Path(core.get_download_dir()).name}/" if files else ""
            extra = ""
            if fails:
                extra = f"  ·  {len(fails)} failed — see Log / Details for full messages"
            self.msg.configure(text=f'Status: {job["status"]}{tail}{extra}'
                               + (f'  ·  {job.get("error", "")[:150]}' if job.get("error") else ""))
            # Cancel lives only while downloading; Retry only when failed exist.
            try:
                self.cancel_btn.configure(state="disabled")
                self.retry_btn.configure(state="normal" if fails else "disabled")
            except Exception:
                pass
            key = (job["id"], job["status"])
            if key not in self._logged_errors:
                self._logged_errors.add(key)
                self.log(f"Job {job['id']} finished: {job['status']} "
                         f"({len(files)} done, {len(fails)} failed).")
                for v in fails:
                    self.log(f"   • {v.get('title', v['id'])} [{v['id']}]: {v.get('error')}", "error")
            return
        self.after(800, self._poll)

    def _cancel(self):
        if self.job_id:
            core.cancel_job(self.job_id)
            self.log(f"Cancel requested for job {self.job_id}.")

    def _retry(self):
        if self.job_id:
            # Failed videos were reset to start-from-zero; job runs again.
            core.retry_job(self.job_id)
            self.log(f"Retry requested for job {self.job_id} (failed videos restart from the start).")
            try:
                self.retry_btn.configure(state="disabled")
                self.cancel_btn.configure(state="normal")
            except Exception:
                pass
            if not self.polling:
                self.after(0, self._poll)


if __name__ == "__main__":
    App().mainloop()
