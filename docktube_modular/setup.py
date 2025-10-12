import sys
from cx_Freeze import setup, Executable
import os

PYTHON_INSTALL_DIR = os.path.dirname(os.path.dirname(os.__file__))
os.environ['TCL_LIBRARY'] = os.path.join(PYTHON_INSTALL_DIR, 'tcl', 'tcl8.6')
os.environ['TK_LIBRARY'] = os.path.join(PYTHON_INSTALL_DIR, 'tcl', 'tk8.6')

base = None
if sys.platform == 'win32':
    base = 'Win32GUI'

sys.setrecursionlimit(3000)

executables = [
    Executable(
        'main.py',
        icon="assets/logo.ico",
        base=base,
    )
]

shortcut_table = [
    (
        "DesktopShortcut",
        "DesktopFolder",
        "DockTube – YouTube Downloader",
        "TARGETDIR",
        "[TARGETDIR]main.exe",
        None,
        "Download YouTube videos and playlists easily",
        None,
        None,
        None,
        None,
        "TARGETDIR",
    )
]

msi_data = {"Shortcut": shortcut_table}
bdist_msi_options = {"data": msi_data}

options = {
    "bdist_msi": bdist_msi_options,
    "build_exe": {
        "include_files": [
            os.path.join(PYTHON_INSTALL_DIR, "DLLs", "tk86t.dll"),
            os.path.join(PYTHON_INSTALL_DIR, "DLLs", "tcl86t.dll"),
            "assets/logo.ico",
            "assets/ficon.png",
        ],
        "packages": [
            "tkinter",
            "customtkinter",
            "PIL",
            "yt_dlp",
            "threading",
            "queue",
        ],
        "excludes": [
            "unittest",
            "email",
            "http",
            "xml",
        ],
        "compressed": True,
        "optimize": 2,
    },
}

setup(
    name="DockTube",
    version="1.0",
    description="DockTube – YouTube Downloader",
    author="Md Abdullah Al Mamun",
    author_email="pygemsbd@gmail.com",
    options=options,
    executables=executables,
)
