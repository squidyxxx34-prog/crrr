"""
PitWall AI — Setup
Run this ONCE to configure your account.
After setup, launch PitWallAI.exe for the headless daemon.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from pitwall.setup import main

if __name__ == '__main__':
    print("=" * 45)
    print("  PITWALL AI — FIRST TIME SETUP")
    print("=" * 45)
    cfg = main()
    print("\n  ✅ Setup complete!")
    print("  Now launch PitWallAI.exe to start the daemon.")
    print("\n  Press Enter to exit...")
    input()
