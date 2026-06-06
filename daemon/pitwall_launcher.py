"""
PitWall AI — Entry Point
Run setup if no config, then launch headless daemon.
"""

import sys
import os
from pathlib import Path

APP_DIR  = Path(os.getenv('APPDATA', '.')) / 'PitWall'
CFG_FILE = APP_DIR / 'config.json'

def main():
    # Setup wizard if no config
    from pitwall.setup import main as run_setup
    cfg = run_setup()

    # Launch daemon
    from pitwall.main import PitWallDaemon
    daemon = PitWallDaemon(cfg)
    daemon.run()

if __name__ == '__main__':
    main()
