import os
import time
import threading
import customtkinter as ctk
from tkinter import messagebox, filedialog, ttk
from PIL import Image, ImageTk

from core.fetcher import YouTubeFetcher
from core.downloader import YouTubeDownloaderCore
from core.utils import is_valid_url, adjust_color

class YouTubeDownloaderApp:
    def __init__(self):
        self.window = ctk.CTk()
        self.window.title("DockTube – YouTube Downloader")
        self.window.geometry("1015x600")
        self.window.resizable(True, True)

        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.ico")
        icon_path = os.path.normpath(icon_path)
        if os.path.exists(icon_path):
            try:
                self.window.iconbitmap(icon_path)
            except Exception:
                pass

        # Services
        self.fetcher = YouTubeFetcher()
        self.downloader_core = YouTubeDownloaderCore()

        # State
        self.output_queue = self.downloader_core.output_queue
        self.videos = {}
        self.download_progresses = {}
        self.fetching = False
        self.downloading = False
        self.paused = False

        # Title animation state
        self.current_title = "Video"
        self.last_title_update = time.time()
        self.fade_direction = 1
        self.title_opacity = 1.0

        self._configure_styles()
        self._build_ui()

        # Start loops
        self.animate_title()
        self.check_output()

    def _configure_styles(self):
        style = ttk.Style()
        style.layout('Vertical.TProgressbar',
                     [('Vertical.Progressbar.trough',
                       {'children': [('Vertical.Progressbar.pbar',
                                    {'side': 'left', 'sticky': 'ns'})],
                        'sticky': 'nswe'})])
        style.configure('Vertical.TProgressbar', background='#2FA572', troughcolor='#E0E0E0', thickness=10)
        style.configure("Treeview", background="#ffffff", foreground="#212529", rowheight=30, fieldbackground="#ffffff")
        style.configure("Treeview.Heading", background="#f8f9fa", foreground="#1a73e8", font=('Arial', 10, 'bold'))

    def _build_ui(self):
        # Title
        title_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        title_frame.grid(row=0, column=0, pady=20)

        self.title_dock = ctk.CTkLabel(title_frame, text="Dock", font=("Arial", 28, "bold"), text_color="#282828")
        self.title_dock.grid(row=0, column=0, padx=2)
        self.title_tube = ctk.CTkLabel(title_frame, text="Tube", font=("Arial", 28, "bold"), text_color="#FF0000")
        self.title_tube.grid(row=0, column=1, padx=(0, 8))
        self.title_separator = ctk.CTkLabel(title_frame, text="–", font=("Arial", 28, "bold"), text_color="#282828")
        self.title_separator.grid(row=0, column=2, padx=8)

        youtube_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        youtube_frame.grid(row=0, column=3, padx=2)
        youtube_text = "YouTube"
        youtube_colors = ["#FF0000"] * len(youtube_text)
        for i, (letter, color) in enumerate(zip(youtube_text, youtube_colors)):
            label = ctk.CTkLabel(youtube_frame, text=letter, font=("Arial", 28, "bold"), text_color=color)
            label.grid(row=0, column=i, padx=0)

        type_container = ctk.CTkFrame(title_frame, fg_color="transparent", width=150, height=40)
        type_container.grid(row=0, column=4, padx=(8, 2))
        type_container.grid_propagate(False)
        self.title_type = ctk.CTkLabel(type_container, text="Video", font=("Arial", 28, "bold"), text_color="#1a73e8")
        self.title_type.place(relx=0.5, rely=0.5, anchor="center")
        self.title_downloader = ctk.CTkLabel(title_frame, text="Downloader", font=("Arial", 28, "bold"), text_color="#282828")
        self.title_downloader.grid(row=0, column=5, padx=(8, 2))

        # Input frame
        input_frame = ctk.CTkFrame(self.window)
        input_frame.grid(row=1, column=0, padx=20, pady=(5, 10), sticky="ew")
        input_frame.grid_columnconfigure(1, weight=1)

        url_label = ctk.CTkLabel(input_frame, text="URL:", font=("Arial", 12, "bold"), anchor="e", width=70)
        url_label.grid(row=0, column=0, padx=(10, 5), pady=(10, 5), sticky="e")
        self.url_entry = ctk.CTkEntry(input_frame, width=350, placeholder_text="Enter video or playlist URL", font=("Arial", 12), height=32)
        self.url_entry.grid(row=0, column=1, padx=(5, 10), pady=(10, 5), sticky="ew")

        url_buttons_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        url_buttons_frame.grid(row=0, column=2, columnspan=2, pady=(10, 5), sticky="w")

        paste_button = ctk.CTkButton(url_buttons_frame, text="📋 Paste", width=70, command=self.paste_and_fetch, font=("Arial", 12))
        paste_button.grid(row=0, column=0, padx=5)
        clear_button = ctk.CTkButton(url_buttons_frame, text="✕ Clear", width=70, command=lambda: self.url_entry.delete(0, 'end'), fg_color="#dc3545", hover_color="#bb2d3b", font=("Arial", 12))
        clear_button.grid(row=0, column=1, padx=5)

        path_label = ctk.CTkLabel(input_frame, text="Save to:", font=("Arial", 12, "bold"), anchor="e", width=70)
        path_label.grid(row=1, column=0, padx=(10, 5), pady=(5, 10), sticky="e")
        self.path_entry = ctk.CTkEntry(input_frame, width=350, font=("Arial", 12), height=32)
        self.path_entry.grid(row=1, column=1, padx=(5, 10), pady=(5, 10), sticky="ew")
        self.path_entry.insert(0, os.path.join(os.path.expanduser("~"), "Downloads"))

        path_buttons_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        path_buttons_frame.grid(row=1, column=2, columnspan=2, pady=(5, 10), sticky="w")

        browse_button = ctk.CTkButton(path_buttons_frame, text="📂 Browse", width=70, command=self.browse_path, font=("Arial", 12))
        browse_button.grid(row=0, column=0, padx=5)
        open_folder_button = ctk.CTkButton(path_buttons_frame, text="📁 Open", width=70, command=self.open_download_folder, font=("Arial", 12))
        open_folder_button.grid(row=0, column=1, padx=5)

        self.url_entry.bind('<Control-v>', lambda e: self.paste_and_fetch())

        # List frame
        list_frame = ctk.CTkFrame(self.window)
        list_frame.grid(row=3, column=0, padx=20, pady=10, sticky="nsew")
        self.window.grid_rowconfigure(3, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(1, weight=1)

        controls_frame = ctk.CTkFrame(list_frame)
        controls_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        check_all_btn = ctk.CTkButton(controls_frame, text="Check All", width=100, command=lambda: self.toggle_all_checks(True), fg_color="#1a73e8", hover_color="#1557b0")
        check_all_btn.grid(row=0, column=0, padx=5)
        uncheck_all_btn = ctk.CTkButton(controls_frame, text="Uncheck All", width=100, command=lambda: self.toggle_all_checks(False), fg_color="#6c757d", hover_color="#5a6268")
        uncheck_all_btn.grid(row=0, column=1, padx=5)

        self.tree = ttk.Treeview(list_frame, columns=("check", "title", "size", "type", "progress"), show="headings", selectmode="none")
        self.tree.heading("check", text="#")
        self.tree.heading("title", text="Title")
        self.tree.heading("size", text="Size")
        self.tree.heading("type", text="Type")
        self.tree.heading("progress", text="Progress")
        self.tree.column("check", width=50, anchor="center", minwidth=50)
        self.tree.column("title", width=400, minwidth=200)
        self.tree.column("size", width=100, anchor="center", minwidth=80)
        self.tree.column("type", width=100, anchor="center", minwidth=80)
        self.tree.column("progress", width=300, anchor="center", minwidth=200)

        self.tree.tag_configure('oddrow', background='#f8f9fa')
        self.tree.tag_configure('evenrow', background='#ffffff')

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        scrollbar.grid(row=1, column=1, sticky="ns")

        self.tree.bind("<Button-1>", self.toggle_check)

        # Status and control buttons
        status_frame = ctk.CTkFrame(self.window)
        status_frame.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(status_frame, text="Ready", wraplength=500, font=("Arial", 12), justify="center")
        self.status_label.grid(row=0, column=0, pady=10, sticky="ew")

        self.overall_progress = ctk.CTkProgressBar(status_frame, width=400)
        self.overall_progress.configure(mode="determinate", progress_color="#2FA572", height=10)
        self.overall_progress.grid(row=1, column=0, pady=5)
        self.overall_progress.grid_remove()
        self.overall_progress.set(0)

        control_buttons_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        control_buttons_frame.grid(row=5, column=0, pady=20)

        self.download_button = ctk.CTkButton(control_buttons_frame, text="🔽 Download", command=self.start_download, width=120, font=("Arial", 12, "bold"), corner_radius=10)
        self.download_button.grid(row=0, column=0, padx=5)
        self.pause_button = ctk.CTkButton(control_buttons_frame, text="⏸ Pause", command=self.toggle_pause, width=100, state="disabled", font=("Arial", 12, "bold"), corner_radius=10)
        self.pause_button.grid(row=0, column=1, padx=5)
        self.stop_button = ctk.CTkButton(control_buttons_frame, text="⏹ Stop", command=self.stop_download, width=100, state="disabled", fg_color="#dc3545", hover_color="#bb2d3b", font=("Arial", 12, "bold"), corner_radius=10)
        self.stop_button.grid(row=0, column=2, padx=5)
        reset_button = ctk.CTkButton(control_buttons_frame, text="🔄 Reset", command=self.reset_gui, fg_color="#dc3545", hover_color="#bb2d3b", width=100, font=("Arial", 12, "bold"), corner_radius=10)
        reset_button.grid(row=0, column=3, padx=5)

    # (remaining methods: browse_path, update_status, process_output, check_output, download_video,
    # start_download, toggle_check, toggle_all_checks, get_video_info, update_fetch_timer,
    # fetch_video_info, update_video_list, update_video_progress, run, cancel_fetch, reset_gui,
    # toggle_pause, stop_download, open_download_folder, animate_title, _adjust_color, paste_and_fetch, is_valid_url)

    # For brevity the full method implementations are attached as simple wrappers calling core modules

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, path)

    def update_status(self, message, progress=None):
        self.status_label.configure(text=message)
        if progress is not None:
            self.overall_progress.set(progress)

    def process_output(self, process, video_id: str):
        # Deprecated in modular UI; core downloader pushes to shared queue
        pass

    def check_output(self):
        try:
            while True:
                video_id, line = self.downloader_core.output_queue.get_nowait()
                # Minimal parsing: detect percent
                if "%" in line:
                    try:
                        pct = float(re.search(r"(\d+\.?\d*)%", line).group(1))
                        self.update_video_progress(video_id, pct)
                        title = self.videos.get(video_id, {}).get('title', '')
                        short_title = (title[:30] + '...') if len(title) > 30 else title
                        self.status_label.configure(text=f"Downloading: {short_title} - {pct:.1f}%")
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            self.window.after(100, self.check_output)

    def download_video(self, video_id: str, output_path: str):
        return self.downloader_core.download(video_id, output_path)

    def start_download(self):
        save_path = self.path_entry.get().strip()
        if not save_path:
            messagebox.showerror("Error", "Please select a save location")
            return
        if not os.path.exists(save_path):
            try:
                os.makedirs(save_path)
            except Exception as e:
                messagebox.showerror("Error", f"Could not create directory: {str(e)}")
                return

        self.selected_videos = []
        for item in self.tree.get_children():
            values = self.tree.item(item)["values"]
            if values[0] == "☒":
                video_tag = [tag for tag in self.tree.item(item)["tags"] if tag.startswith("video_")][0]
                video_id = video_tag.replace("video_", "")
                self.selected_videos.append((video_id, item))

        if not self.selected_videos:
            messagebox.showerror("Error", "Please select at least one video to download")
            return

        self.downloading = True
        self.paused = False
        self.download_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        self.overall_progress.grid()
        self.overall_progress.set(0)
        for video_id, _ in self.selected_videos:
            self.download_progresses[video_id] = 0
        self.status_label.configure(text="Starting downloads...")

        def download_thread():
            success_count = 0
            for video_id, _ in self.selected_videos:
                if not self.downloading:
                    break
                while self.paused:
                    time.sleep(0.1)
                    if not self.downloading:
                        break
                if not self.downloading:
                    break
                self.window.after(0, lambda vid=video_id: self.status_label.configure(text=f"Downloading {self.videos[vid]['title']}..."))
                if self.download_video(video_id, save_path):
                    success_count += 1
            if self.downloading:
                self.window.after(0, lambda: self.status_label.configure(text=f"Download completed! {success_count} of {len(self.selected_videos)} videos downloaded successfully."))
            self.downloading = False
            self.paused = False
            self.window.after(0, lambda: self.download_button.configure(state="normal"))
            self.window.after(0, lambda: self.pause_button.configure(state="disabled"))
            self.window.after(0, lambda: self.stop_button.configure(state="disabled"))

        threading.Thread(target=download_thread, daemon=True).start()

    def toggle_check(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            if column == "#1":
                item = self.tree.identify_row(event.y)
                if item:
                    current_text = self.tree.item(item)["values"][0]
                    new_text = "☐" if current_text == "☒" else "☒"
                    values = list(self.tree.item(item)["values"])
                    values[0] = new_text
                    self.tree.item(item, values=values)

    def toggle_all_checks(self, checked: bool):
        for item in self.tree.get_children():
            values = list(self.tree.item(item)["values"])
            values[0] = "☒" if checked else "☐"
            self.tree.item(item, values=values)

    def get_video_info(self, url: str):
        try:
            videos = self.fetcher.fetch(url)
            return videos
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return []

    def update_fetch_timer(self, start_time):
        if not self.fetching:
            return
        elapsed = int(time.time() - start_time)
        try:
            self.status_label.configure(text=f"Fetching video information... {elapsed}s")
            self.timer_id = self.window.after(1000, lambda: self.update_fetch_timer(start_time))
        except Exception:
            self.fetching = False
            if hasattr(self, 'timer_id'):
                self.window.after_cancel(self.timer_id)

    def fetch_video_info(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a URL")
            return
        self.url_entry.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.fetching = True
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_label.configure(text="Fetching video information... 0s")
        start_time = time.time()
        self.timer_id = self.window.after(1000, lambda: self.update_fetch_timer(start_time))

        def fetch_thread():
            try:
                videos = self.get_video_info(url)
                if videos:
                    self.window.after(0, lambda: self.update_video_list(videos))
                    self.window.after(0, lambda: self.status_label.configure(text=f"Found {len(videos)} video{'s' if len(videos) > 1 else ''}. Ready to download."))
                else:
                    self.window.after(0, lambda: self.status_label.configure(text="No videos found"))
                    self.window.after(0, lambda: messagebox.showwarning("Warning", "No videos found in the URL"))
            except Exception as e:
                self.window.after(0, lambda: self.status_label.configure(text="Error fetching video information"))
                self.window.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.fetching = False
                if hasattr(self, 'timer_id'):
                    self.window.after_cancel(self.timer_id)
                self.window.after(0, lambda: self.url_entry.configure(state="normal"))
                self.window.after(0, lambda: self.download_button.configure(state="normal"))

        threading.Thread(target=fetch_thread, daemon=True).start()

    def update_video_list(self, videos):
        for idx, video in enumerate(videos, 1):
            video_tag = f"video_{video['id']}"
            row_tags = ['evenrow' if idx % 2 == 0 else 'oddrow', video_tag]
            item = self.tree.insert("", "end", values=(
                "☐",
                video['title'],
                video['size'],
                video['type'],
                "0%"
            ), tags=row_tags)
            self.videos[video['id']] = {
                'title': video['title'],
                'size': video['size'],
                'type': video['type'],
                'item_id': item
            }
            self.download_progresses[video['id']] = 0

    def update_video_progress(self, video_id: str, progress: float):
        try:
            if video_id in self.videos:
                item = self.videos[video_id]['item_id']
                values = list(self.tree.item(item)["values"])
                if progress < 0:
                    values[4] = "Failed - Skipping"
                    self.tree.item(item, values=values, tags=("error",))
                    self.tree.tag_configure("error", foreground="red")
                else:
                    bar_width = 30
                    filled = int((progress / 100) * bar_width)
                    if progress < 50:
                        bar = '▶' * filled + '░' * (bar_width - filled)
                    elif progress < 90:
                        bar = '█' * int(bar_width/2) + '♪' * (filled - int(bar_width/2)) + '░' * (bar_width - filled)
                    else:
                        bar = '█' * filled + '░' * (bar_width - filled)
                    values[4] = f"{bar} {progress:.1f}%"
                    if progress == 100:
                        self.tree.tag_configure("completed", foreground="#2FA572")
                        self.tree.item(item, values=values, tags=("completed",))
                    elif progress > 0:
                        self.tree.tag_configure("downloading", foreground="#1a73e8")
                        self.tree.item(item, values=values, tags=("downloading",))
                self.download_progresses[video_id] = progress

            if hasattr(self, 'selected_videos') and self.selected_videos:
                total_progress = sum(self.download_progresses.get(vid, 0) for vid, _ in self.selected_videos)
                avg_progress = total_progress / len(self.selected_videos)
                current = self.overall_progress.get() * 100
                if abs(avg_progress - current) > 0.1:
                    step = (avg_progress - current) / 10
                    def update_progress(remaining_steps, target):
                        if remaining_steps > 0 and self.downloading and not self.paused:
                            current_val = self.overall_progress.get() * 100
                            new_val = min(current_val + step, target)
                            self.overall_progress.set(new_val / 100)
                            self.window.after(50, lambda: update_progress(remaining_steps - 1, target))
                    update_progress(10, avg_progress)
        except Exception as e:
            print(f"Error updating progress: {str(e)}")

    def run(self):
        self.window.mainloop()

    def cancel_fetch(self):
        self.fetching = False
        self.window.after(0, lambda: self.url_entry.configure(state="normal"))
        self.window.after(0, lambda: self.download_button.configure(state="normal"))
        self.window.after(0, lambda: self.status_label.configure(text="Fetch cancelled"))
        for widget in self.window.grid_slaves(row=2):
            widget.destroy()

    def reset_gui(self):
        self.fetching = False
        self.downloading = False
        self.paused = False
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.videos.clear()
        self.download_progresses.clear()
        self.overall_progress.set(0)
        self.overall_progress.grid_remove()
        self.status_label.configure(text="Ready")
        self.url_entry.delete(0, 'end')
        self.download_button.configure(state="normal")
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.configure(text="Resume" if self.paused else "Pause")
        status = "Paused" if self.paused else "Resuming download..."
        self.status_label.configure(text=status)

    def stop_download(self):
        self.downloading = False
        self.paused = False
        self.download_button.configure(state="normal")
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text="Download stopped")

    def open_download_folder(self):
        path = self.path_entry.get().strip()
        if path and os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showerror("Error", "Download folder does not exist")

    def animate_title(self):
        current_time = time.time()
        elapsed = current_time - self.last_title_update
        if elapsed < 2.0:
            if self.fade_direction == 1:
                self.title_opacity = elapsed / 2.0
            else:
                self.title_opacity = 1.0 - (elapsed / 2.0)
            if self.current_title == "Video":
                color = adjust_color("#1a73e8", self.title_opacity)
            else:
                color = adjust_color("#EA4335", self.title_opacity)
            try:
                self.title_type.configure(text_color=color)
            except Exception:
                pass
        elif elapsed >= 1.0:
            self.current_title = "Playlist" if self.current_title == "Video" else "Video"
            self.title_type.configure(text=self.current_title)
            self.last_title_update = current_time
            self.fade_direction *= -1
            self.title_opacity = 0.0 if self.fade_direction == 1 else 1.0
            if self.current_title == "Video   ":
                color = "#1a73e8"
            else:
                color = "#EA4335"
            try:
                self.title_type.configure(text_color=color)
            except Exception:
                pass
            self.title_downloader.lift()
        self.window.after(20, self.animate_title)

    def paste_and_fetch(self):
        try:
            url = self.window.clipboard_get().strip()
        except Exception:
            url = ''
        if url:
            self.url_entry.delete(0, 'end')
            self.url_entry.insert(0, url)
            if is_valid_url(url):
                self.fetch_video_info()

    def is_valid_url(self, url: str) -> bool:
        return is_valid_url(url)
