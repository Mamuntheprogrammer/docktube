import sys
from cx_Freeze import setup, Executable
import os
import msilib

# ----------------------------
# TCL/TK Library Configuration
# ----------------------------
PYTHON_INSTALL_DIR = os.path.dirname(os.path.dirname(os.__file__))
os.environ['TCL_LIBRARY'] = os.path.join(PYTHON_INSTALL_DIR, 'tcl', 'tcl8.6')
os.environ['TK_LIBRARY'] = os.path.join(PYTHON_INSTALL_DIR, 'tcl', 'tk8.6')

# ----------------------------
# Base Configuration (for GUI)
# ----------------------------
base = None
if sys.platform == 'win32':
    base = 'Win32GUI'

# ----------------------------
# Prevent recursion issues
# ----------------------------
sys.setrecursionlimit(3000)

# ----------------------------
# Executable Target Definition
# ----------------------------
executables = [
    Executable(
        'doctube_main.py',      # main script file
        icon="logo.ico",         # app icon
        base=base,
    )
]

# ----------------------------
# MSI Shortcut Configuration
# ----------------------------
shortcut_table = [
    (
        "DesktopShortcut",       # Shortcut name
        "DesktopFolder",         # Directory
        "DockTube – YouTube Downloader",  # Display Name
        "TARGETDIR",             # Component
        "[TARGETDIR]docktube_main.exe",   # Target Executable
        None,                    # Arguments
        "Download YouTube videos and playlists easily",  # Description
        None,                    # Hotkey
        None,                    # Icon
        None,                    # IconIndex
        None,                    # ShowCmd
        "TARGETDIR"              # Working Directory
    )
]

msi_data = {"Shortcut": shortcut_table}
bdist_msi_options = {"data": msi_data}

# ----------------------------
# Build Configuration
# ----------------------------
options = {
    "bdist_msi": bdist_msi_options,
    "build_exe": {
        "include_files": [
            os.path.join(PYTHON_INSTALL_DIR, "DLLs", "tk86t.dll"),
            os.path.join(PYTHON_INSTALL_DIR, "DLLs", "tcl86t.dll"),
            "logo.ico",  # App icon
        ],
        "packages": [
            "os",
            "sys",
            "subprocess",
            "customtkinter",
            "tkinter",
            "PIL",
            "yt_dlp",
            "threading",
            "queue",
            "re",
            "time",
            "json",
            "typing",
        ],
        "includes": [],
        "excludes": [],
    },
}

# ----------------------------
# Setup Definition
# ----------------------------
setup(
    name="DockTube",
    version="1.0",
    description="DockTube – YouTube Downloader",
    author="Md Abdullah Al Mamun",
    author_email="pygemsbd@gmail.com",
    options=options,
    executables=executables,
)
