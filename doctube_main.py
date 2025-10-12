import subprocess
import sys
import os
import customtkinter as ctk
from tkinter import messagebox, filedialog, ttk
import threading
import queue
import re
import time
from typing import Dict, List
import json
from PIL import Image, ImageTk


def resource_path(relative_path):
    """
    Get absolute path to resource, works in dev and in PyInstaller --onefile.
    """
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)



class YouTubeDownloader:
    def __init__(self):
        self.window = ctk.CTk()
        self.window.title("DockTube – YouTube Downloader")
        self.window.geometry("900x600")
        self.window.resizable(True, True)
        
        # Set window icon
        icon_path = os.path.join(os.path.dirname(__file__), "logos.ico")
        if os.path.exists(icon_path):
            self.window.iconbitmap(icon_path)
            
        # Initialize title animation
        self.current_title = "Video"  # No need for padding now
        self.last_title_update = time.time()
        self.fade_direction = 1  # 1 for fade in, -1 for fade out
        self.fade_progress = 0
        self.title_opacity = 1.0
        
        # Configure grid
        self.window.grid_columnconfigure(0, weight=1)
        
        # Configure styles
        style = ttk.Style()
        # Progress bar style
        style.layout('Vertical.TProgressbar', 
                     [('Vertical.Progressbar.trough',
                       {'children': [('Vertical.Progressbar.pbar',
                                    {'side': 'left', 'sticky': 'ns'})],
                        'sticky': 'nswe'})])
        style.configure('Vertical.TProgressbar', 
                      background='#2FA572',
                      troughcolor='#E0E0E0',
                      thickness=10)
        
        # Treeview style
        style.configure("Treeview",
                      background="#ffffff",
                      foreground="#212529",
                      rowheight=30,
                      fieldbackground="#ffffff",
                      borderwidth=2,
                      relief="solid")
        style.configure("Treeview.Heading",
                      background="#f8f9fa",
                      foreground="#1a73e8",
                      relief="raised",
                      borderwidth=2,
                      font=('Arial', 10, 'bold'))
        # Configure cell borders
        style.configure("Treeview", bordercolor="#e0e0e0", lightcolor="#ffffff", darkcolor="#e0e0e0")
        style.map("Treeview.Heading",
                 background=[('active', '#e8f0fe')],
                 foreground=[('active', '#185abc')])
        style.map("Treeview",
                 background=[('selected', '#e8f0fe')],
                 foreground=[('selected', '#1a73e8')])
                 
        # Configure tags for different states
        style.configure("Treeview", font=('Arial', 10))
        
        # Queue for output
        self.output_queue = queue.Queue()
        
        # Video information storage
        self.videos: Dict[str, dict] = {}
        self.download_progresses: Dict[str, float] = {}
        
        # Control flags
        self.fetching = False
        self.downloading = False
        # Animated Title
        title_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        title_frame.grid(row=0, column=0, pady=20)
        
        self.title_dock = ctk.CTkLabel(title_frame, text="Dock", 
                                      font=("Arial", 28, "bold"), 
                                      text_color="#282828")
        self.title_dock.grid(row=0, column=0, padx=2)
        
        self.title_tube = ctk.CTkLabel(title_frame, text="Tube", 
                                      font=("Arial", 28, "bold"), 
                                      text_color="#FF0000")
        self.title_tube.grid(row=0, column=1, padx=(0, 8))
        
        self.title_separator = ctk.CTkLabel(title_frame, text="–", 
                                          font=("Arial", 28, "bold"),
                                          text_color="#282828")
        self.title_separator.grid(row=0, column=2, padx=8)
        
        # Colored YouTube text with each letter
        youtube_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        youtube_frame.grid(row=0, column=3, padx=2)
        
        youtube_colors = ["#FF0000", "#FF0000", "#FF0000", "#FF0000", "#FF0000", "#FF0000", "#FF0000"]
        youtube_text = "YouTube"
        
        for i, (letter, color) in enumerate(zip(youtube_text, youtube_colors)):
            label = ctk.CTkLabel(youtube_frame, text=letter,
                               font=("Arial", 28, "bold"),
                               text_color=color)
            label.grid(row=0, column=i, padx=0)
        
        # Container frame for animated type to maintain fixed width and height
        type_container = ctk.CTkFrame(title_frame, fg_color="transparent", width=150, height=40)
        type_container.grid(row=0, column=4, padx=(8, 2))
        type_container.grid_propagate(False)  # Prevent frame from resizing
        
        # Animated type label with fade effect
        self.title_type = ctk.CTkLabel(type_container, text="Video", 
                                      font=("Arial", 28, "bold"),
                                      text_color="#1a73e8")
        self.title_type.place(relx=0.5, rely=0.5, anchor="center")  # Center in container
        
        # Static "Downloader" text
        self.title_downloader = ctk.CTkLabel(title_frame, text="Downloader", 
                                           font=("Arial", 28, "bold"),
                                           text_color="#282828")
        self.title_downloader.grid(row=0, column=5, padx=(8, 2))
        
        # Start title animation
        self.animate_title()
        self.setup_ui()
        
        # Start output checking
        self.check_output()
        
    def setup_ui(self):
        # Title
        # title = ctk.CTkLabel(self.window, text="DockTube – YouTube Downloader", font=("Arial", 20, "bold"))
        # title.grid(row=0, column=0, pady=20)
        
        # Input Fields Frame
        input_frame = ctk.CTkFrame(self.window)
        input_frame.grid(row=1, column=0, padx=20, pady=(5, 10), sticky="ew")
        input_frame.grid_columnconfigure(1, weight=1)
        
        # URL Input
        url_label = ctk.CTkLabel(input_frame, text="URL:", font=("Arial", 12, "bold"), anchor="e", width=70)
        url_label.grid(row=0, column=0, padx=(10, 5), pady=(10, 5), sticky="e")
        
        self.url_entry = ctk.CTkEntry(input_frame, width=350, placeholder_text="Enter video or playlist URL",
                                     font=("Arial", 12), height=32)
        self.url_entry.grid(row=0, column=1, padx=(5, 10), pady=(10, 5), sticky="ew")
        
        # URL Buttons Frame for right alignment
        url_buttons_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        url_buttons_frame.grid(row=0, column=2, columnspan=2, pady=(10, 5), sticky="w")
        
        # URL Buttons
        paste_button = ctk.CTkButton(url_buttons_frame, text="📋 Paste", width=70, 
                                   command=self.paste_and_fetch,
                                   font=("Arial", 12))
        paste_button.grid(row=0, column=0, padx=5)
        
        clear_button = ctk.CTkButton(url_buttons_frame, text="✕ Clear", width=70,
                                   command=lambda: self.url_entry.delete(0, 'end'),
                                   fg_color="#dc3545",
                                   hover_color="#bb2d3b",
                                   font=("Arial", 12))
        clear_button.grid(row=0, column=1, padx=5)
        
        # Download Path
        path_label = ctk.CTkLabel(input_frame, text="Save to:", font=("Arial", 12, "bold"), anchor="e", width=70)
        path_label.grid(row=1, column=0, padx=(10, 5), pady=(5, 10), sticky="e")
        
        self.path_entry = ctk.CTkEntry(input_frame, width=350, font=("Arial", 12), height=32)
        self.path_entry.grid(row=1, column=1, padx=(5, 10), pady=(5, 10), sticky="ew")
        self.path_entry.insert(0, os.path.join(os.path.expanduser("~"), "Downloads"))
        
        # Path Buttons Frame for right alignment
        path_buttons_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        path_buttons_frame.grid(row=1, column=2, columnspan=2, pady=(5, 10), sticky="w")
        
        browse_button = ctk.CTkButton(path_buttons_frame, text="📂 Browse", width=70, 
                                    command=self.browse_path,
                                    font=("Arial", 12))
        browse_button.grid(row=0, column=0, padx=5)
        
        open_folder_button = ctk.CTkButton(path_buttons_frame, text="📁 Open", width=70, 
                                         command=self.open_download_folder,
                                         font=("Arial", 12))
        open_folder_button.grid(row=0, column=1, padx=5)
        
        # Add Ctrl+V binding to URL entry
        self.url_entry.bind('<Control-v>', lambda e: self.paste_and_fetch())
        
        # Video List Frame
        list_frame = ctk.CTkFrame(self.window)
        list_frame.grid(row=3, column=0, padx=20, pady=10, sticky="nsew")
        self.window.grid_rowconfigure(3, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(1, weight=1)
        
        # List Controls
        controls_frame = ctk.CTkFrame(list_frame)
        controls_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        check_all_btn = ctk.CTkButton(controls_frame, text="Check All", width=100,
                                     command=lambda: self.toggle_all_checks(True),
                                     fg_color="#1a73e8",  # Blue
                                     hover_color="#1557b0")
        check_all_btn.grid(row=0, column=0, padx=5)
        
        uncheck_all_btn = ctk.CTkButton(controls_frame, text="Uncheck All", width=100,
                                       command=lambda: self.toggle_all_checks(False),
                                       fg_color="#6c757d",  # Gray
                                       hover_color="#5a6268")
        uncheck_all_btn.grid(row=0, column=1, padx=5)
        
        # Create Treeview
        self.tree = ttk.Treeview(list_frame, columns=("check", "title", "size", "type", "progress"),
                                show="headings", selectmode="none")
        
        self.tree.heading("check", text="#")
        self.tree.heading("title", text="Title")
        self.tree.heading("size", text="Size")
        self.tree.heading("type", text="Type")
        self.tree.heading("progress", text="Progress")
        
        self.tree.column("check", width=50, anchor="center", minwidth=50)
        self.tree.column("title", width=400, minwidth=200)
        self.tree.column("size", width=100, anchor="center", minwidth=80)
        self.tree.column("type", width=100, anchor="center", minwidth=80)
        self.tree.column("progress", width=300, anchor="center", minwidth=200)  # Made wider for the progress bar
        
        # Configure alternating row colors
        self.tree.tag_configure('oddrow', background='#f8f9fa')
        self.tree.tag_configure('evenrow', background='#ffffff')
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        scrollbar.grid(row=1, column=1, sticky="ns")
        
        # Bind checkbox click
        self.tree.bind("<Button-1>", self.toggle_check)
        
        # Status Frame
        status_frame = ctk.CTkFrame(self.window)
        status_frame.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1)  # Center contents
        
        # Status Label
        self.status_label = ctk.CTkLabel(status_frame, text="Ready", 
                                        wraplength=500, 
                                        font=("Arial", 12),
                                        justify="center")
        self.status_label.grid(row=0, column=0, pady=10, sticky="ew")
        
        # Overall Progress Bar (hidden by default)
        self.overall_progress = ctk.CTkProgressBar(status_frame, width=400)
        self.overall_progress.configure(
            mode="determinate",
            progress_color="#2FA572",  # Nice green color
            height=10
        )
        self.overall_progress.grid(row=1, column=0, pady=5)
        self.overall_progress.grid_remove()  # Hide initially
        self.overall_progress.set(0)
        
        # Control Buttons Frame
        control_buttons_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        control_buttons_frame.grid(row=5, column=0, pady=20)
        
        # Download Button
        self.download_button = ctk.CTkButton(
            control_buttons_frame,
            text="🔽 Download",
            command=self.start_download,
            width=120,
            font=("Arial", 12, "bold"),
            corner_radius=10
        )
        self.download_button.grid(row=0, column=0, padx=5)
        
        # Pause Button
        self.pause_button = ctk.CTkButton(
            control_buttons_frame,
            text="⏸ Pause",
            command=self.toggle_pause,
            width=100,
            state="disabled",
            font=("Arial", 12, "bold"),
            corner_radius=10
        )
        self.pause_button.grid(row=0, column=1, padx=5)
        
        # Stop Button
        self.stop_button = ctk.CTkButton(
            control_buttons_frame,
            text="⏹ Stop",
            command=self.stop_download,
            width=100,
            state="disabled",
            fg_color="#dc3545",
            hover_color="#bb2d3b",
            font=("Arial", 12, "bold"),
            corner_radius=10
        )
        self.stop_button.grid(row=0, column=2, padx=5)
        
        # Reset Button
        reset_button = ctk.CTkButton(
            control_buttons_frame,
            text="🔄 Reset",
            command=self.reset_gui,
            fg_color="#dc3545",
            hover_color="#bb2d3b",
            width=100,
            font=("Arial", 12, "bold"),
            corner_radius=10
        )
        reset_button.grid(row=0, column=3, padx=5)

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, path)

    def update_status(self, message, progress=None):
        self.status_label.configure(text=message)
        if progress is not None:
            self.progress_bar.set(progress)
            
    def process_output(self, process, video_id: str):
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                self.output_queue.put((video_id, line.strip()))
                
    def check_output(self):
        try:
            while True:
                video_id, line = self.output_queue.get_nowait()
                
                # Extract download progress
                if "[download]" in line:
                    # Check for different progress indicators
                    progress = None
                    if "of" in line and "%" in line:
                        # Regular download progress
                        try:
                            progress = float(re.search(r"(\d+\.?\d*)%", line).group(1))
                        except:
                            pass
                    elif "Downloading video" in line:
                        # Starting download
                        progress = 0.0
                    elif "Downloading audio" in line:
                        # Audio download starts at 50%
                        progress = 50.0
                    elif "Merging formats" in line:
                        # Merging starts at 90%
                        progress = 90.0
                    
                    if progress is not None:
                        self.update_video_progress(video_id, progress)
                        # Update status with simplified progress
                        if self.videos.get(video_id):
                            title = self.videos[video_id]['title']
                            short_title = (title[:30] + '...') if len(title) > 30 else title
                            self.status_label.configure(text=f"Downloading: {short_title} - {progress:.1f}%")
                    
        except queue.Empty:
            pass
        finally:
            self.window.after(50, self.check_output)  # More frequent updates for smoother progress








    def download_video(self, video_id: str, output_path: str):
        if video_id not in self.videos:
            return False
            

        yt_dlp_exe = resource_path("yt-dlp.exe")  # instead of "yt-dlp"
        # "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        # "--embed-thumbnail",

        command = [
            yt_dlp_exe,
            "--format", "best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--output", os.path.join(output_path, "%(title)s.%(ext)s"),
            "--embed-metadata",
            "--progress",
            "--retries", "3",  # Retry 3 times
            "--fragment-retries", "3",  # Retry fragment downloads 3 times
            "--socket-timeout", "30",  # 30 seconds timeout
            f"https://youtube.com/watch?v={video_id}"  # Use specific video ID
        ]

        # print("YT-DLP PATH:", yt_dlp_exe)
        # print("COMMAND:", " ".join(command))
        
        try:
            # Run the command with output capture
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # Process output in a separate thread
            threading.Thread(target=self.process_output, args=(process, video_id), daemon=True).start()
            
            try:
                # Set a 5-minute timeout for each video
                completed = False
                start_time = time.time()
                while time.time() - start_time < 300:  # 5 minutes timeout
                    if process.poll() is not None:
                        completed = True
                        break
                    time.sleep(0.1)
                
                if not completed:
                    process.terminate()
                    self.window.after(0, lambda: self.update_video_progress(video_id, -1))  # Mark as failed
                    self.window.after(0, lambda: self.status_label.configure(
                        text=f"Skipping {self.videos[video_id]['title']} (timeout)"
                    ))
                    return False
                
                if process.returncode == 0:
                    self.window.after(0, lambda: self.update_video_progress(video_id, 100.0))
                    return True
                else:
                    self.window.after(0, lambda: self.update_video_progress(video_id, -1))  # Mark as failed
                    self.window.after(0, lambda: self.status_label.configure(
                        text=f"Failed to download {self.videos[video_id]['title']} - Skipping"
                    ))
                    return False
            except Exception as e:
                self.window.after(0, lambda: self.update_video_progress(video_id, -1))  # Mark as failed
                self.window.after(0, lambda: self.status_label.configure(text=f"Error: {str(e)}"))
                return False
                
        except Exception as e:
            self.window.after(0, lambda: self.status_label.configure(text=f"Error downloading video {video_id}: {str(e)}"))
            return False

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
        
        # Get selected videos
        self.selected_videos = []  # Store as instance variable
        for item in self.tree.get_children():
            values = self.tree.item(item)["values"]
            if values[0] == "☒":  # If checked
                # Extract video ID from the tag
                video_tag = [tag for tag in self.tree.item(item)["tags"] if tag.startswith("video_")][0]
                video_id = video_tag.replace("video_", "")
                self.selected_videos.append((video_id, item))
        
        if not self.selected_videos:
            messagebox.showerror("Error", "Please select at least one video to download")
            return
        
        # Set control flags and update UI
        self.downloading = True
        self.paused = False
        self.download_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        
        # Show and reset progress bar
        self.overall_progress.grid()  # Show progress bar
        self.overall_progress.set(0)
        for video_id, _ in self.selected_videos:
            self.download_progresses[video_id] = 0
        
        self.status_label.configure(text="Starting downloads...")
        
        def download_thread():
            success_count = 0
            
            for video_id, _ in self.selected_videos:
                if not self.downloading:  # Check if stopped
                    break
                    
                while self.paused:  # Handle pause
                    time.sleep(0.1)
                    if not self.downloading:  # Check if stopped while paused
                        break
                        
                if not self.downloading:
                    break
                    
                self.window.after(0, lambda vid=video_id: self.status_label.configure(
                    text=f"Downloading {self.videos[vid]['title']}..."
                ))
                
                if self.download_video(video_id, save_path):
                    success_count += 1
            
            if self.downloading:  # Only show completion message if not stopped
                self.window.after(0, lambda: self.status_label.configure(
                    text=f"Download completed! {success_count} of {len(self.selected_videos)} videos downloaded successfully."
                ))
                
                if success_count == len(self.selected_videos):
                    self.window.after(0, lambda: messagebox.showinfo("Success", 
                        f"All {success_count} videos downloaded successfully!\nLocation: {save_path}"))
                elif success_count > 0:
                    self.window.after(0, lambda: messagebox.showwarning("Partial Success",
                        f"{success_count} of {len(self.selected_videos)} videos downloaded successfully.\nLocation: {save_path}"))
                else:
                    self.window.after(0, lambda: messagebox.showerror("Error",
                        "No videos were downloaded successfully."))
            
            # Reset UI
            self.downloading = False
            self.paused = False
            self.window.after(0, lambda: self.download_button.configure(state="normal"))
            self.window.after(0, lambda: self.pause_button.configure(state="disabled"))
            self.window.after(0, lambda: self.stop_button.configure(state="disabled"))
        
        # Start download in a separate thread
        threading.Thread(target=download_thread, daemon=True).start()
    
    def toggle_check(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            if column == "#1":  # Check column
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

    def get_video_info(self, url: str) -> List[dict]:
        yt_dlp_exe = resource_path("yt-dlp.exe")  # instead of "yt-dlp"

        command = [
            yt_dlp_exe,
            "--no-download",
            "--flat-playlist",  # Don't extract video info, just playlist
            "-J",  # Output json
            url
        ]
        
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode != 0:
                raise Exception(f"Failed to fetch video info: {result.stderr}")
            
            data = json.loads(result.stdout)
            videos = []
            
            # Handle both single video and playlist
            if 'entries' in data:  # Playlist
                for entry in data['entries']:
                    if entry:
                        videos.append({
                            'id': entry.get('id', ''),
                            'title': entry.get('title', 'Unknown Title'),
                            'size': 'TBD',  # Size will be determined during download
                            'type': 'MP4'  # We're forcing MP4 in download
                        })
            else:  # Single video
                videos.append({
                    'id': data.get('id', ''),
                    'title': data.get('title', 'Unknown Title'),
                    'size': 'TBD',
                    'type': 'MP4'
                })
                    
            return videos
            
        except Exception as e:
            self.window.after(0, lambda e=e: messagebox.showerror("Error", str(e)))
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
        
        # Disable UI elements
        self.url_entry.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.fetching = True
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Update status and start timer
        self.status_label.configure(text="Fetching video information... 0s")
        start_time = time.time()
        self.timer_id = self.window.after(1000, lambda: self.update_fetch_timer(start_time))
        
        def fetch_thread():
            try:
                videos = self.get_video_info(url)
                if videos:
                    self.window.after(0, lambda: self.update_video_list(videos))
                    self.window.after(0, lambda: self.status_label.configure(
                        text=f"Found {len(videos)} video{'s' if len(videos) > 1 else ''}. Ready to download."
                    ))
                else:
                    self.window.after(0, lambda: self.status_label.configure(text="No videos found"))
                    self.window.after(0, lambda: messagebox.showwarning("Warning", "No videos found in the URL"))
            except Exception as e:
                self.window.after(0, lambda: self.status_label.configure(text="Error fetching video information"))
                self.window.after(0, lambda e=e: messagebox.showerror("Error", str(e)))  # Corrected

            finally:
                # Stop the timer and cleanup
                self.fetching = False
                if hasattr(self, 'timer_id'):
                    self.window.after_cancel(self.timer_id)
                # Re-enable UI elements
                self.window.after(0, lambda: self.url_entry.configure(state="normal"))
                self.window.after(0, lambda: self.download_button.configure(state="normal"))
        
        threading.Thread(target=fetch_thread, daemon=True).start()

    def update_video_list(self, videos: List[dict]):
        for idx, video in enumerate(videos, 1):
            # Keep video ID in a separate tag to prevent overwriting
            video_tag = f"video_{video['id']}"  # Prefix to make it unique
            row_tags = ['evenrow' if idx % 2 == 0 else 'oddrow', video_tag]
            item = self.tree.insert("", "end", values=(
                "☐",  # Checkbox
                video['title'],
                video['size'],
                video['type'],
                "0%"
            ), tags=row_tags)
            self.videos[video['id']] = {
                'title': video['title'],
                'size': video['size'],
                'type': video['type'],
                'item_id': item  # Store the tree item ID
            }
            self.download_progresses[video['id']] = 0

    def update_video_progress(self, video_id: str, progress: float):
        if not self.downloading or self.paused:  # If stopped or paused
            return
            
        try:
            # Update individual video progress
            if video_id in self.videos:
                item = self.videos[video_id]['item_id']
                # Update progress in tree with colored progress bar
                values = list(self.tree.item(item)["values"])
                if progress < 0:  # Error state
                    values[4] = "Failed - Skipping"
                    self.tree.item(item, values=values, tags=("error",))
                    self.tree.tag_configure("error", foreground="red")
                else:
                    # Create a visual progress bar with stages
                    bar_width = 30  # Width of the progress bar
                    filled = int((progress / 100) * bar_width)
                    # Show different stages of download
                    if progress < 50:  # Video download
                        bar = '▶' * filled + '░' * (bar_width - filled)
                    elif progress < 90:  # Audio download
                        bar = '█' * int(bar_width/2) + '♪' * (filled - int(bar_width/2)) + '░' * (bar_width - filled)
                    else:  # Merging
                        bar = '█' * filled + '░' * (bar_width - filled)
                    values[4] = f"{bar} {progress:.1f}%"
                    
                    # Apply color based on progress
                    if progress == 100:
                        self.tree.tag_configure("completed", foreground="#2FA572")
                        self.tree.item(item, values=values, tags=("completed",))
                    elif progress > 0:
                        self.tree.tag_configure("downloading", foreground="#1a73e8")
                        self.tree.item(item, values=values, tags=("downloading",))
                self.download_progresses[video_id] = progress
            
            # Update overall progress if we have selected videos
            if hasattr(self, 'selected_videos') and self.selected_videos:
                total_progress = sum(self.download_progresses.get(vid, 0) for vid, _ in self.selected_videos)
                avg_progress = total_progress / len(self.selected_videos)
                
                # Implement smooth progress bar animation
                current = self.overall_progress.get() * 100
                if abs(avg_progress - current) > 0.1:  # Only update if change is significant
                    # Calculate step size for smooth animation
                    step = (avg_progress - current) / 10  # Divide difference into 10 steps
                    
                    def update_progress(remaining_steps, target):
                        if remaining_steps > 0 and self.downloading and not self.paused:
                            current_val = self.overall_progress.get() * 100
                            new_val = min(current_val + step, target)
                            self.overall_progress.set(new_val / 100)
                            self.window.after(50, lambda: update_progress(remaining_steps - 1, target))
                    
                    update_progress(10, avg_progress)  # Start the smooth animation
        except Exception as e:
            print(f"Error updating progress: {str(e)}")  # For debugging
        except Exception as e:
            print(f"Error updating progress: {str(e)}")  # For debugging

    def run(self):
        self.window.mainloop()

    def cancel_fetch(self):
        self.fetching = False
        self.window.after(0, lambda: self.url_entry.configure(state="normal"))
        self.window.after(0, lambda: self.download_button.configure(state="normal"))
        self.window.after(0, lambda: self.status_label.configure(text="Fetch cancelled"))
        # Remove loading frame (it's the third row)
        for widget in self.window.grid_slaves(row=2):
            widget.destroy()
    
    def reset_gui(self):
        # Stop any ongoing operations
        self.fetching = False
        self.downloading = False
        self.paused = False
        
        # Clear the video list
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Clear stored data
        self.videos.clear()
        self.download_progresses.clear()
        
        # Reset and hide progress bar
        self.overall_progress.set(0)
        self.overall_progress.grid_remove()
        
        # Reset status and URL
        self.status_label.configure(text="Ready")
        self.url_entry.delete(0, 'end')
        
        # Enable/disable buttons appropriately
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
            os.startfile(path)  # Opens folder in Windows Explorer
        else:
            messagebox.showerror("Error", "Download folder does not exist")
            
    def animate_title(self):
        current_time = time.time()
        elapsed = current_time - self.last_title_update
        
        # Handle fade animation
        if elapsed < 2.0:  # During the 2-second animation
            # Calculate opacity based on fade direction and progress
            if self.fade_direction == 1:  # Fading in
                self.title_opacity = elapsed / 2.0  # Divide by 2.0 to normalize the opacity
            else:  # Fading out
                self.title_opacity = 1.0 - (elapsed / 2.0)
            
            # Apply the opacity through color adjustment
            if self.current_title == "Video":
                color = self._adjust_color("#1a73e8", self.title_opacity)
            else:
                color = self._adjust_color("#EA4335", self.title_opacity)
                
            self.title_type.configure(text_color=color)
            
        elif elapsed >= 1.0:  # Time to switch text
            # Switch the text and reset animation
            self.current_title = "Playlist" if self.current_title == "Video" else "Video"
            self.title_type.configure(text=self.current_title)
            self.last_title_update = current_time
            self.fade_direction *= -1  # Toggle fade direction
            self.title_opacity = 0.0 if self.fade_direction == 1 else 1.0
            
            # Set initial color for new text
            if self.current_title == "Video   ":
                color = "#1a73e8"
            else:
                color = "#EA4335"
            self.title_type.configure(text_color=color)
            
            # Keep the "Downloader" text static
            self.title_downloader.lift()
        
        self.window.after(20, self.animate_title)  # Update more frequently for smoother animation
        
    def _adjust_color(self, hex_color, opacity):
        # Convert hex to RGB
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        
        # Adjust for opacity by blending with background (white)
        r = int(r * opacity + 255 * (1 - opacity))
        g = int(g * opacity + 255 * (1 - opacity))
        b = int(b * opacity + 255 * (1 - opacity))
        
        # Convert back to hex
        return f"#{r:02x}{g:02x}{b:02x}"

    def paste_and_fetch(self):
        url = self.window.clipboard_get().strip()        
        if url:
            self.url_entry.delete(0, 'end')
            self.url_entry.insert(0, url)
            if self.is_valid_url(url):
                self.fetch_video_info()

    def is_valid_url(self, url: str) -> bool:
        return any(pattern in url.lower() for pattern in [
            'youtube.com/watch?',
            'youtu.be/',
            'youtube.com/playlist?',
        ])


if __name__ == "__main__":
    app = YouTubeDownloader()
    app.run()
