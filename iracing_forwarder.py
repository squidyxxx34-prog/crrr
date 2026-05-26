"""
PitWall AI — iRacing Forwarder
Double-click to run. Exposes iRacing telemetry via WebSocket on port 8765.
Required only for iRacing. LMU and ACC work natively.

Install: pip install pyirsdk websockets
Run: python iracing_forwarder.py
"""

import asyncio
import json
import time
import sys

try:
    import irsdk
except ImportError:
    print("ERROR: pyirsdk not installed.")
    print("Run: pip install pyirsdk")
    input("Press Enter to exit...")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed.")
    print("Run: pip install websockets")
    input("Press Enter to exit...")
    sys.exit(1)

PORT = 8765
FIELDS = [
    'PlayerCarPosition', 'NumActiveCars', 'FuelLevel', 'FuelLevelPct',
    'LFtempCL', 'RFtempCL', 'LRtempCL', 'RRtempCL',
    'LFwearM', 'RFwearM', 'LRwearM', 'RRwearM',
    'Lap', 'SessionLapsTotal', 'SessionTimeRemain',
    'WeatherType', 'TrackTemp', 'AirTemp',
    'LapDeltaToSessionBestLap', 'LapLastLapTime', 'LapBestLapTime',
]

ir = irsdk.IRSDK()
connected = False


def get_data():
    global connected
    if not ir.is_initialized or not ir.is_connected:
        if not connected:
            ir.startup()
            connected = ir.is_initialized and ir.is_connected
        return None

    connected = True
    data = {}
    for field in FIELDS:
        try:
            data[field] = ir[field]
        except Exception:
            data[field] = None
    return data


async def stream(websocket):
    print(f"Client connected: {websocket.remote_address}")
    try:
        while True:
            data = get_data()
            if data:
                await websocket.send(json.dumps(data))
            else:
                await websocket.send(json.dumps({"status": "waiting_for_iracing"}))
            await asyncio.sleep(2)
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")


async def main():
    print("=" * 50)
    print("  PitWall AI — iRacing Forwarder")
    print("=" * 50)
    print(f"\n  WebSocket running on port {PORT}")
    print(f"  Enter this IP in the PitWall app: [YOUR_LOCAL_IP]:{PORT}")
    print("\n  Waiting for iRacing to start...")
    print("  (Keep this window open during your session)\n")

    async with websockets.serve(stream, "0.0.0.0", PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForwarder stopped.")
