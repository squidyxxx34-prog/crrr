"""
PitWall AI Daemon
Headless Windows app — reads sim telemetry via shared memory,
calls Groq AI for strategy, speaks via Groq TTS.
"""

import sys
import os
import time
import json
import threading
import ctypes
import ctypes.wintypes
import socket
import struct
import asyncio
import logging
import hashlib
import keyboard
import requests
import pygame
import io
from datetime import datetime
from pathlib import Path

# ── CONFIG PATHS ──────────────────────────────────────────
APP_DIR   = Path(os.getenv('APPDATA', '.')) / 'PitWall'
CFG_FILE  = APP_DIR / 'config.json'
LOG_FILE  = APP_DIR / 'pitwall.log'
APP_DIR.mkdir(parents=True, exist_ok=True)

# ── LOGGING ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('pitwall')

# ── CONSTANTS ─────────────────────────────────────────────
GROQ_API   = 'https://api.groq.com/openai/v1'
SUPA_URL   = 'https://ofptqazlbbalebgqtwbr.supabase.co'
SUPA_KEY   = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mcHRxYXpsYmJhbGViZ3F0d2JyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODUwMzUsImV4cCI6MjA5NTM2MTAzNX0.aiiFgRcpmUBkJkfQSCPTWjT73hVjUaSARVohR80vNhM'

PERSONAS = {
    'james': {'voice': 'Fritz-PlayAI', 'lang': 'en-GB', 'style': 'Calm, precise British F1 engineer. Short sentences. Never panics.'},
    'marco': {'voice': 'Celeste-PlayAI','lang': 'it',    'style': 'Passionate Italian engineer. Tactical. Energetic but professional.'},
    'hans':  {'voice': 'Fritz-PlayAI', 'lang': 'de',    'style': 'German engineer. Ultra technical. Data-focused. Efficient.'},
    'nick':  {'voice': 'Chip-PlayAI',  'lang': 'en-AU', 'style': 'Australian engineer. Direct, no nonsense, straight to the point.'},
}

THINK_INTERVAL   = 30   # seconds between auto AI calls
POLL_INTERVAL    = 1    # telemetry poll rate (seconds)
MIN_SPEAK_GAP    = 20   # minimum seconds between spoken messages

# ── CONFIG ────────────────────────────────────────────────
def load_config():
    if CFG_FILE.exists():
        with open(CFG_FILE) as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CFG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

# ── PYGAME AUDIO ─────────────────────────────────────────
pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.mixer.init()

def play_audio(audio_bytes: bytes):
    try:
        sound = pygame.mixer.Sound(io.BytesIO(audio_bytes))
        sound.play()
        while pygame.mixer.get_busy():
            time.sleep(0.05)
    except Exception as e:
        log.error(f'Audio playback error: {e}')

# ── GROQ TTS ─────────────────────────────────────────────
def speak(text: str, voice: str, groq_key: str):
    try:
        r = requests.post(
            f'{GROQ_API}/audio/speech',
            headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
            json={'model': 'playai-tts', 'input': text, 'voice': voice, 'response_format': 'wav'},
            timeout=10,
        )
        if r.status_code == 200:
            play_audio(r.content)
        else:
            log.warning(f'TTS error {r.status_code}: {r.text[:200]}')
    except Exception as e:
        log.error(f'TTS failed: {e}')

# ── GROQ AI ──────────────────────────────────────────────
def call_ai(system: str, prompt: str, groq_key: str) -> str:
    try:
        r = requests.post(
            f'{GROQ_API}/chat/completions',
            headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'max_tokens': 80,
                'temperature': 0.7,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': prompt},
                ],
            },
            timeout=8,
        )
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
        log.warning(f'AI error {r.status_code}: {r.text[:200]}')
        return 'SILENT'
    except Exception as e:
        log.error(f'AI call failed: {e}')
        return 'SILENT'

# ── SUPABASE ─────────────────────────────────────────────
def supa_get(endpoint: str, token: str) -> dict:
    r = requests.get(
        f'{SUPA_URL}/rest/v1/{endpoint}',
        headers={
            'apikey': SUPA_KEY,
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        timeout=5,
    )
    return r.json() if r.status_code == 200 else {}

def supa_insert(table: str, data: dict, token: str):
    requests.post(
        f'{SUPA_URL}/rest/v1/{table}',
        headers={
            'apikey': SUPA_KEY,
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal',
        },
        json=data,
        timeout=5,
    )

def validate_token(token: str) -> dict:
    r = requests.get(
        f'{SUPA_URL}/auth/v1/user',
        headers={'apikey': SUPA_KEY, 'Authorization': f'Bearer {token}'},
        timeout=5,
    )
    return r.json() if r.status_code == 200 else None

# ══════════════════════════════════════════════════════════
#  SHARED MEMORY READERS
# ══════════════════════════════════════════════════════════

# ── iRACING ──────────────────────────────────────────────
IRACING_MEM_NAME = '$SuperFileMemory$'

class IRacingReader:
    def __init__(self):
        self.hmap = None
        self.buf  = None

    def connect(self) -> bool:
        try:
            self.hmap = ctypes.windll.kernel32.OpenFileMappingW(
                0x0004, False, IRACING_MEM_NAME)
            if not self.hmap:
                return False
            self.buf = ctypes.windll.kernel32.MapViewOfFile(
                self.hmap, 0x0004, 0, 0, 0)
            return bool(self.buf)
        except:
            return False

    def read(self) -> dict | None:
        if not self.buf:
            return None
        try:
            # iRacing header: 144 bytes, then variable data
            header = (ctypes.c_int * 36).from_address(self.buf)
            if header[0] != 1: return None  # not valid
            var_offset = header[4]
            num_vars   = header[3]

            data = {}
            # Read known variable values by scanning var headers
            for i in range(num_vars):
                vh_addr = self.buf + 144 + i * 144
                vh = (ctypes.c_int * 36).from_address(vh_addr)
                name_addr = vh_addr + 16
                name = ctypes.string_at(name_addr, 32).decode('latin1').rstrip('\x00')
                vtype  = vh[0]
                offset = vh[3]
                val_addr = self.buf + var_offset + offset
                try:
                    if vtype == 1:   # bool
                        data[name] = bool(ctypes.c_bool.from_address(val_addr).value)
                    elif vtype == 2: # int
                        data[name] = ctypes.c_int.from_address(val_addr).value
                    elif vtype == 4: # float
                        data[name] = ctypes.c_float.from_address(val_addr).value
                    elif vtype == 5: # double
                        data[name] = ctypes.c_double.from_address(val_addr).value
                except:
                    pass

            return self._normalize_iracing(data)
        except Exception as e:
            log.debug(f'iRacing read error: {e}')
            return None

    def _normalize_iracing(self, d: dict) -> dict:
        fuel_pct  = d.get('FuelLevelPct', 0)
        fuel_cap  = d.get('FuelLevel', 0) / fuel_pct if fuel_pct > 0 else 0
        lf_wear   = d.get('LFwearM', 1.0)
        tyre_cond = 'OK' if lf_wear > 0.6 else ('WARN' if lf_wear > 0.3 else 'CRIT')
        return {
            'sim':          'iRacing',
            'position':     d.get('PlayerCarPosition', 1),
            'totalEntries': d.get('NumActiveCars', 1),
            'fuelPercent':  fuel_pct * 100,
            'fuelLevel':    round(d.get('FuelLevel', 0), 2),
            'tyreCondition':tyre_cond,
            'tyreWear':     round(lf_wear * 100, 1),
            'gapAhead':     round(d.get('LapDeltaToSessionBestLap', 0), 2),
            'lap':          d.get('Lap', 0),
            'totalLaps':    d.get('SessionLapsTotal', 0),
            'weather':      'Rain' if d.get('WeatherType', 0) == 1 else 'Dry',
            'trackName':    '',
            'sessionType':  d.get('SessionType', 'Race'),
        }

    def disconnect(self):
        if self.buf:
            ctypes.windll.kernel32.UnmapViewOfFile(self.buf)
        if self.hmap:
            ctypes.windll.kernel32.CloseHandle(self.hmap)

# ── ACC ───────────────────────────────────────────────────
ACC_MEM_PHYSICS   = 'Local\\acpmf_physics'
ACC_MEM_GRAPHICS  = 'Local\\acpmf_graphics'
ACC_MEM_STATIC    = 'Local\\acpmf_static'

class ACCReader:
    PHYSICS_SIZE  = 708
    GRAPHICS_SIZE = 1256

    def connect(self) -> bool:
        try:
            self.hphys = ctypes.windll.kernel32.OpenFileMappingW(0x0004, False, ACC_MEM_PHYSICS)
            self.hgfx  = ctypes.windll.kernel32.OpenFileMappingW(0x0004, False, ACC_MEM_GRAPHICS)
            if not self.hphys or not self.hgfx: return False
            self.bphys = ctypes.windll.kernel32.MapViewOfFile(self.hphys, 0x0004, 0, 0, 0)
            self.bgfx  = ctypes.windll.kernel32.MapViewOfFile(self.hgfx,  0x0004, 0, 0, 0)
            return bool(self.bphys and self.bgfx)
        except:
            return False

    def read(self) -> dict | None:
        try:
            # Physics: fuel at offset 3*4=12 (3 floats in)
            fuel = ctypes.c_float.from_address(self.bphys + 12).value
            # Tyre wear: offsets 656-671 (4 floats)
            tw_fl = ctypes.c_float.from_address(self.bphys + 656).value
            # Graphics: position at offset 60 (int)
            pos  = ctypes.c_int.from_address(self.bgfx + 60).value
            # Total cars
            total = ctypes.c_int.from_address(self.bgfx + 64).value or 1
            # Lap
            lap  = ctypes.c_int.from_address(self.bgfx + 20).value
            # Gap
            gap  = ctypes.c_float.from_address(self.bgfx + 200).value

            tyre_cond = 'OK' if tw_fl > 70 else ('WARN' if tw_fl > 40 else 'CRIT')
            fuel_pct  = min(100.0, (fuel / 120.0) * 100)

            return {
                'sim':          'ACC',
                'position':     max(1, pos),
                'totalEntries': max(1, total),
                'fuelPercent':  round(fuel_pct, 1),
                'fuelLevel':    round(fuel, 2),
                'tyreCondition':tyre_cond,
                'tyreWear':     round(tw_fl, 1),
                'gapAhead':     round(abs(gap), 2),
                'lap':          lap,
                'totalLaps':    0,
                'weather':      'Dry',
                'trackName':    '',
                'sessionType':  'Race',
            }
        except Exception as e:
            log.debug(f'ACC read error: {e}')
            return None

    def disconnect(self):
        for attr in ['bphys', 'bgfx']:
            if hasattr(self, attr) and getattr(self, attr):
                ctypes.windll.kernel32.UnmapViewOfFile(getattr(self, attr))
        for attr in ['hphys', 'hgfx']:
            if hasattr(self, attr) and getattr(self, attr):
                ctypes.windll.kernel32.CloseHandle(getattr(self, attr))

# ── LMU / rFactor2 ───────────────────────────────────────
LMU_MEM_NAMES = ['$LMU_SMM$', '$rFactor2SMMP_Buffer1$', '$rFactor2SMMP_Buffer$', 'Local\\$rFactor2SMMP_Buffer1$', 'Local\\$LMU_SMM$']

class LMUReader:
    def connect(self) -> bool:
        try:
            for name in LMU_MEM_NAMES:
                self.hmap = ctypes.windll.kernel32.OpenFileMappingW(0x0004, False, name)
                if self.hmap:
                    self.buf = ctypes.windll.kernel32.MapViewOfFile(self.hmap, 0x0004, 0, 0, 0)
                    if self.buf:
                        log.info(f'LMU connected via: {name}')
                        return True
            return False
        except:
            return False

    def read(self) -> dict | None:
        try:
            # rFactor2/LMU Telemetry buffer - fuel at offset 212 (float, after header)
            # Based on rF2SharedMemoryMapPlugin layout
            # Telemetry struct starts at offset 0
            # mFuel is at byte offset 212 in rF2VehicleTelemetry
            fuel = ctypes.c_float.from_address(self.buf + 212).value

            # Scoring buffer at large offset
            # Try to read basic values safely
            pos   = ctypes.c_int.from_address(self.buf + 0x400).value
            total = ctypes.c_int.from_address(self.buf + 0x404).value
            lap   = ctypes.c_int.from_address(self.buf + 0x408).value

            if pos <= 0 or pos > 200: pos = 1
            if total <= 0 or total > 200: total = 1
            if lap < 0: lap = 0

            # Tyre wear (front left) 
            tw = ctypes.c_float.from_address(self.buf + 0x500).value
            if tw <= 0 or tw > 1.0:
                tw_pct = 90.0  # default if invalid
            else:
                tw_pct = tw * 100.0

            tyre_cond = 'OK' if tw_pct > 70 else ('WARN' if tw_pct > 40 else 'CRIT')
            fuel_pct  = min(100.0, max(0.0, (fuel / 120.0) * 100))

            # Validate fuel makes sense
            if fuel < 0 or fuel > 200:
                fuel = 50.0
                fuel_pct = 50.0

            return {
                'sim':          'LMU',
                'position':     max(1, pos),
                'totalEntries': max(1, total),
                'fuelPercent':  round(fuel_pct, 1),
                'fuelLevel':    round(fuel, 2),
                'tyreCondition':tyre_cond,
                'tyreWear':     round(tw_pct, 1),
                'gapAhead':     0.0,
                'lap':          lap,
                'totalLaps':    0,
                'weather':      'Dry',
                'trackName':    '',
                'sessionType':  'Race',
            }
        except Exception as e:
            log.debug(f'LMU read error: {e}')
            return None

    def disconnect(self):
        if hasattr(self, 'buf') and self.buf:
            ctypes.windll.kernel32.UnmapViewOfFile(self.buf)
        if hasattr(self, 'hmap') and self.hmap:
            ctypes.windll.kernel32.CloseHandle(self.hmap)

# ══════════════════════════════════════════════════════════
#  DAEMON CORE
# ══════════════════════════════════════════════════════════
class PitWallDaemon:
    def __init__(self, cfg: dict):
        self.cfg          = cfg
        self.groq_key     = cfg['groq_key']
        self.token        = cfg['supabase_token']
        self.persona_key  = cfg.get('persona', 'james')
        self.persona      = PERSONAS[self.persona_key]
        self.push_key     = cfg.get('push_key', 'f8')
        self.user_id      = cfg.get('user_id', '')

        self.telem        = {}
        self.last_spoken  = 0
        self.last_think   = 0
        self.is_speaking  = False
        self.sim_reader   = None
        self.sim_name     = None
        self.running      = True

    def build_system_prompt(self) -> str:
        return (
            f"You are a professional sim racing engineer named {self.persona_key.capitalize()}. "
            f"{self.persona['style']} "
            "Rules: max 2 sentences, speak directly to driver. "
            "If nothing important to say, reply exactly: SILENT"
        )

    def build_context(self) -> str:
        d = self.telem
        if not d: return ''
        laps_left = (d['totalLaps'] - d['lap']) if d['totalLaps'] > 0 else '?'
        return (
            f"Sim: {d.get('sim','?')} | Track: {d.get('trackName','?')} | "
            f"Session: {d.get('sessionType','Race')} | "
            f"Position: P{d['position']}/{d['totalEntries']} | "
            f"Fuel: {d['fuelPercent']:.0f}% ({d['fuelLevel']}L) | "
            f"Tyres: {d['tyreCondition']} ({d['tyreWear']}% wear) | "
            f"Gap ahead: {d['gapAhead']}s | "
            f"Lap: {d['lap']}/{d['totalLaps']} ({laps_left} left) | "
            f"Weather: {d['weather']}"
        )

    def speak_msg(self, text: str):
        if self.is_speaking: return
        def _speak():
            self.is_speaking = True
            log.info(f'[ENGINEER] {text}')
            speak(text, self.persona['voice'], self.groq_key)
            self.last_spoken = time.time()
            self.is_speaking = False
            # Store in Supabase
            self.log_message(text, 'engineer')
        threading.Thread(target=_speak, daemon=True).start()

    def log_message(self, text: str, role: str):
        try:
            track = self.telem.get('trackName', 'unknown') or 'unknown'
            supa_insert('conversations', {
                'user_id':   self.user_id,
                'role':      role,
                'content':   text,
                'track':     track,
                'sim':       self.telem.get('sim', ''),
                'created_at': datetime.utcnow().isoformat(),
            }, self.token)
        except Exception as e:
            log.debug(f'Log error: {e}')

    def auto_think(self):
        now = time.time()
        if now - self.last_think < THINK_INTERVAL: return
        if now - self.last_spoken < MIN_SPEAK_GAP: return
        if self.is_speaking: return
        if not self.telem: return
        self.last_think = now

        ctx = self.build_context()
        prompt = f"{ctx}\n\nShould you say something useful to the driver right now? If yes say it. If not reply SILENT."
        msg = call_ai(self.build_system_prompt(), prompt, self.groq_key)
        if msg and msg != 'SILENT':
            self.speak_msg(msg)

    def check_critical_events(self):
        d = self.telem
        if not d: return
        now = time.time()
        if now - self.last_spoken < MIN_SPEAK_GAP: return

        # Critical tyre
        if d['tyreCondition'] == 'CRIT':
            ctx = self.build_context()
            msg = call_ai(self.build_system_prompt(),
                f"{ctx}\nTyres are CRITICAL. What do you tell the driver immediately?",
                self.groq_key)
            if msg and msg != 'SILENT':
                self.speak_msg(msg)
                return

        # Critical fuel
        if d['fuelPercent'] < 8:
            ctx = self.build_context()
            msg = call_ai(self.build_system_prompt(),
                f"{ctx}\nFuel is critically low at {d['fuelPercent']:.0f}%. Urgent advice?",
                self.groq_key)
            if msg and msg != 'SILENT':
                self.speak_msg(msg)

    def on_push_to_talk(self):
        if self.is_speaking: return
        if not self.telem: return
        ctx = self.build_context()
        prompt = f"{ctx}\n\nDriver pressed talk button. Give your best strategic advice right now."
        log.info('[PTT] Driver pressed push-to-talk')
        self.log_message('[PTT activated]', 'driver')
        msg = call_ai(self.build_system_prompt(), prompt, self.groq_key)
        if msg and msg != 'SILENT':
            self.speak_msg(msg)

    def detect_sim(self) -> bool:
        readers = [
            ('iRacing', IRacingReader()),
            ('ACC',     ACCReader()),
            ('LMU',     LMUReader()),
        ]
        for name, reader in readers:
            if reader.connect():
                test = reader.read()
                if test:
                    self.sim_reader = reader
                    self.sim_name   = name
                    log.info(f'✅ Detected sim: {name}')
                    return True
                reader.disconnect()

        # Try to list available shared memory for debug
        try:
            import subprocess
            result = subprocess.run(['powershell', '-Command',
                'Get-Process | Where-Object {$_.Name -match "iRacing|LMU|AC2|acs"} | Select-Object Name'],
                capture_output=True, text=True, timeout=3)
            log.info(f'Running sim processes: {result.stdout.strip() or "none found"}')
        except: pass
        log.warning('⚠️  No supported sim detected (iRacing / ACC / LMU). Retrying...')
        return False

    def run(self):
        log.info('PitWall AI Daemon starting...')
        log.info(f'Persona: {self.persona_key} | Push-to-talk: {self.push_key}')

        # Register push-to-talk
        keyboard.add_hotkey(self.push_key, self.on_push_to_talk)
        log.info(f'Push-to-talk registered: {self.push_key}')

        # Wait for sim
        log.info('Waiting for sim to start...')
        while self.running:
            if self.detect_sim():
                break
            time.sleep(5)

        log.info(f'Connected to {self.sim_name}. Monitoring...')

        # Greeting
        greeting = f"PitWall online. Connected to {self.sim_name}. I'm watching."
        self.speak_msg(greeting)

        critical_check_counter = 0

        while self.running:
            try:
                data = self.sim_reader.read()
                if data:
                    self.telem = data
                else:
                    # Sim disconnected
                    log.warning(f'{self.sim_name} disconnected. Waiting...')
                    self.sim_reader.disconnect()
                    self.sim_reader = None
                    self.sim_name   = None
                    while self.running:
                        if self.detect_sim(): break
                        time.sleep(5)

                # Auto think every THINK_INTERVAL
                self.auto_think()

                # Critical events every 5 polls
                critical_check_counter += 1
                if critical_check_counter >= 5:
                    critical_check_counter = 0
                    self.check_critical_events()

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f'Loop error: {e}')
                time.sleep(2)

        log.info('PitWall daemon stopped.')
        if self.sim_reader:
            self.sim_reader.disconnect()
        pygame.mixer.quit()
