"""
PitWall AI — Headless Daemon
Requires setup to have been run first (PitWallAI-Setup.exe)
"""
import sys
import os
import json
from pathlib import Path

APP_DIR  = Path(os.getenv('APPDATA', '.')) / 'PitWall'
CFG_FILE = APP_DIR / 'config.json'

sys.path.insert(0, os.path.dirname(__file__))

if __name__ == '__main__':
    if not CFG_FILE.exists():
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "No config found.\nPlease run PitWallAI-Setup.exe first.",
            "PitWall AI",
            0x10  # MB_ICONERROR
        )
        sys.exit(1)

    with open(CFG_FILE) as f:
        cfg = json.load(f)

    from pitwall.main import PitWallDaemon
    daemon = PitWallDaemon(cfg)
    daemon.run()
