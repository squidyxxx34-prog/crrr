"""
PitWall AI — Race Engineer Daemon v5 FINAL
- LMU / ACC / iRacing shared memory (robust parsing)
- Groq llama-3.1-8b-instant (ultra-fast reasoning)
- Groq whisper-large-v3-turbo (STT, push-to-talk)
- edge-tts en-GB-RyanNeural (TTS, British male)
- Real strategy: pit window, fuel laps, gap trend
"""

import sys, os, time, json, re, threading, ctypes, io, logging, wave, tempfile, asyncio
from datetime import datetime
from collections import deque
from pathlib import Path

APP_DIR  = Path(os.getenv('APPDATA', '.')) / 'PitWall'
LOG_FILE = APP_DIR / 'pitwall.log'
APP_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8')],
)
log = logging.getLogger('pitwall')

import requests
import pygame
import numpy as np
import sounddevice as sd
from pynput import keyboard as pynput_kb
import edge_tts

# ── CONFIG ──────────────────────────────────────────────────────────────────
GROQ_API       = 'https://api.groq.com/openai/v1'
SUPA_URL       = 'https://ofptqazlbbalebgqtwbr.supabase.co'
SUPA_KEY       = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mcHRxYXpsYmJhbGViZ3F0d2JyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODUwMzUsImV4cCI6MjA5NTM2MTAzNX0.aiiFgRcpmUBkJkfQSCPTWjT73hVjUaSARVohR80vNhM'

THINK_INTERVAL = 40      # seconds between unprompted AI calls
MIN_SPEAK_GAP  = 22      # minimum gap between messages
POLL_INTERVAL  = 2       # telemetry poll rate
SAMPLE_RATE    = 16000
TTS_VOICE      = 'en-GB-RyanNeural'

PERSONAS = {
    'james': 'Calm, precise British F1 chief engineer. Composed under pressure. Uses F1 terminology.',
    'marco': 'Passionate Italian WEC engineer. Tactical. Reads the race brilliantly.',
    'hans':  'German precision engineer. Data-driven. Never wastes words.',
    'nick':  'Straight-talking Australian GT engineer. Blunt. Always honest.',
}

import ctypes.wintypes as wintypes

KERNEL32 = ctypes.windll.kernel32

# CRITICAL: declare explicit argtypes/restype for every Win32 call.
# Without this, ctypes defaults pointer returns to 32-bit int on some
# builds, silently truncating 64-bit pointers -> invalid memory access
# -> hard OS-level crash that bypasses Python's try/except entirely.
KERNEL32.OpenFileMappingW.restype  = wintypes.HANDLE
KERNEL32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]

KERNEL32.MapViewOfFile.restype  = wintypes.LPVOID
KERNEL32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]

KERNEL32.UnmapViewOfFile.restype  = wintypes.BOOL
KERNEL32.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]

KERNEL32.CloseHandle.restype  = wintypes.BOOL
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]

pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.mixer.init()

# ── UTILS ────────────────────────────────────────────────────────────────────
def strip_tags(t): return re.sub(r'\[.*?\]', '', t).strip()

# ── TTS — edge-tts, British male, free ──────────────────────────────────────
def tts(text):
    clean = strip_tags(text)
    if not clean: return
    try:
        async def _go():
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                tmp = f.name
            await edge_tts.Communicate(clean, TTS_VOICE, rate='+8%').save(tmp)
            return tmp
        tmp = asyncio.run(_go())
        pygame.mixer.music.load(tmp)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.unload()
        try: os.remove(tmp)
        except: pass
    except Exception as e:
        log.warning(f'TTS: {e}')

# ── STT — Groq Whisper, free ─────────────────────────────────────────────────
def stt(wav_bytes, key):
    try:
        r = requests.post(f'{GROQ_API}/audio/transcriptions',
            headers={'Authorization': f'Bearer {key}'},
            files={'file': ('audio.wav', wav_bytes, 'audio/wav')},
            data={'model': 'whisper-large-v3-turbo', 'language': 'en'},
            timeout=10)
        if r.status_code == 200:
            return r.json().get('text', '').strip()
    except Exception as e:
        log.warning(f'STT: {e}')
    return ''

# ── AI — Groq llama-3.1-8b-instant (fastest), free ───────────────────────────
def ask_ai(system, prompt, key, smart=False):
    model = 'llama-3.3-70b-versatile' if smart else 'llama-3.1-8b-instant'
    try:
        r = requests.post(f'{GROQ_API}/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'model': model, 'max_tokens': 90, 'temperature': 0.6,
                  'messages': [{'role': 'system', 'content': system},
                                {'role': 'user',   'content': prompt}]},
            timeout=6)
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.warning(f'AI: {e}')
    return 'SILENT'

# ── SUPABASE ─────────────────────────────────────────────────────────────────
def supa_log(data, token):
    try:
        requests.post(f'{SUPA_URL}/rest/v1/conversations',
            headers={'apikey': SUPA_KEY, 'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json', 'Prefer': 'return=minimal'},
            json=data, timeout=4)
    except: pass

# ── SHARED MEMORY (crash-safe: bounded copy + struct parsing) ────────────────
import struct

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             ctypes.c_ulong),
        ("Protect",           ctypes.c_ulong),
        ("Type",              ctypes.c_ulong),
    ]

KERNEL32.VirtualQuery.restype  = ctypes.c_size_t
KERNEL32.VirtualQuery.argtypes = [wintypes.LPCVOID, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]

def shm_region_size(buf):
    """Query the real committed size of the mapped view. Returns 0 if unknown."""
    try:
        mbi = MEMORY_BASIC_INFORMATION()
        ok = KERNEL32.VirtualQuery(ctypes.c_void_p(buf), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if ok:
            return mbi.RegionSize
    except Exception:
        pass
    return 0

def shm_open(name):
    """Open a named file mapping and return (handle, ptr, safe_size) or (None, None, 0)."""
    h = KERNEL32.OpenFileMappingW(0x0004, False, name)
    if not h:
        return None, None, 0
    b = KERNEL32.MapViewOfFile(h, 0x0004, 0, 0, 0)
    if not b:
        KERNEL32.CloseHandle(h)
        return None, None, 0
    size = shm_region_size(b)
    return h, b, size

def shm_close(h, b):
    if b: KERNEL32.UnmapViewOfFile(b)
    if h: KERNEL32.CloseHandle(h)

def shm_snapshot(buf, region_size, want_size):
    """
    Take a bounded, crash-safe copy of the mapped region into a local Python
    bytes object. Never reads past the OS-reported region size.
    Returns b'' if nothing safe can be copied.
    """
    if not buf or region_size <= 0:
        return b''
    n = min(want_size, region_size)
    if n <= 0:
        return b''
    try:
        local = ctypes.create_string_buffer(n)
        ctypes.memmove(local, ctypes.c_void_p(buf), n)
        return local.raw
    except Exception as e:
        log.debug(f'shm_snapshot failed: {e}')
        return b''

# ── Safe struct-based field readers (operate on LOCAL bytes, never crash) ───
def bf(data, off):
    try: return struct.unpack_from('<f', data, off)[0]
    except struct.error: return 0.0
def bi(data, off):
    try: return struct.unpack_from('<i', data, off)[0]
    except struct.error: return 0
def bI(data, off):
    try: return struct.unpack_from('<I', data, off)[0]
    except struct.error: return 0
def bd(data, off):
    try: return struct.unpack_from('<d', data, off)[0]
    except struct.error: return 0.0
def bu8(data, off):
    try: return struct.unpack_from('<B', data, off)[0]
    except struct.error: return 0
def bi16(data, off):
    try: return struct.unpack_from('<h', data, off)[0]
    except struct.error: return 0
def bs(data, off, n):
    try:
        chunk = data[off:off+n]
        return chunk.split(b'\x00')[0].decode('utf-8', errors='ignore')
    except Exception:
        return ''

# ── LMU READER (crash-safe) ───────────────────────────────────────────────────
class LMUReader:
    TELEM = ['$rFactor2SMMP_Telemetry$', '$LMU_SMM_Telemetry$', '$rFactor2SMMP_Buffer1$']
    SCORE = ['$rFactor2SMMP_Scoring$',   '$LMU_SMM_Scoring$']
    SNAP_SIZE = 4096  # bytes copied per read, bounded to region size automatically

    def __init__(self):
        self.th = self.tb = self.tsize = None
        self.sh = self.sb = self.ssize = None
        self._fpl = None
        self._lap_fuel = None
        self._prev_lap = None

    def connect(self):
        for n in self.TELEM:
            h, b, sz = shm_open(n)
            if b:
                self.th, self.tb, self.tsize = h, b, sz
                log.info(f'LMU telem: {n} ({sz} bytes)')
                break
        for n in self.SCORE:
            h, b, sz = shm_open(n)
            if b:
                self.sh, self.sb, self.ssize = h, b, sz
                log.info(f'LMU score: {n} ({sz} bytes)')
                break
        return self.tb is not None

    def read(self):
        if not self.tb: return None
        try:
            raw = shm_snapshot(self.tb, self.tsize, self.SNAP_SIZE)
            if len(raw) < 64:
                return None  # not enough data to be meaningful

            num_v = bi(raw, 12)
            vbase = 16 if (0 < num_v <= 128) else 0

            lap  = bi(raw, vbase + 24)
            fuel = bf(raw, vbase + 432)
            rpm  = bf(raw, vbase + 356)
            gear = bi(raw, vbase + 352)
            track = bs(raw, vbase + 96, 64) if len(raw) >= vbase + 160 else ''

            # Fuel fallback scan (all on the LOCAL safe buffer)
            if not (0.1 < fuel < 300.0):
                for off in [212, 228, 244, 260, 276, 340, 432, 448, 464]:
                    v = bf(raw, vbase + off)
                    if 0.1 < v < 300.0:
                        fuel = v
                        break
            if not (0.1 < fuel < 300.0):
                fuel = 50.0

            # ── TEMP DEBUG: log every plausible fuel-like offset every ~20s ──
            # Compare these values to your in-game fuel gauge (in litres) and
            # tell me which offset matches — then we lock it in permanently.
            now_ts = time.time()
            if not hasattr(self, '_last_fuel_debug') or now_ts - getattr(self, '_last_fuel_debug', 0) > 20:
                self._last_fuel_debug = now_ts
                candidates = {}
                for off in range(180, 500, 4):
                    v = bf(raw, vbase + off)
                    if 0.05 < v < 250.0:
                        candidates[off] = round(v, 2)
                log.info(f'FUEL SCAN (compare to HUD): {candidates}')

            fuel_pct = min(100.0, max(0.0, (fuel / 120.0) * 100))

            if lap != self._prev_lap:
                if self._lap_fuel is not None and self._prev_lap is not None and lap > 0:
                    consumption = self._lap_fuel - fuel
                    if 0.1 < consumption < 15.0:
                        self._fpl = round(consumption, 2)
                        log.info(f'Fuel/lap: {self._fpl}L')
                self._lap_fuel = fuel
                self._prev_lap = lap

            # ── Scoring (separate bounded snapshot) ──────────────────────
            place = total_v = total_laps = 0
            gap = 0.0
            if self.sb:
                sraw = shm_snapshot(self.sb, self.ssize, self.SNAP_SIZE)
                if len(sraw) >= 32:
                    snum  = bi(sraw, 12)
                    sbase = 16 if (0 < snum <= 128) else 0
                    place      = bu8(sraw, sbase + 108)
                    total_laps = bi16(sraw, sbase + 72)
                    gap        = abs(bd(sraw, sbase + 116))
                    total_v    = max(1, snum if 0 < snum <= 128 else 1)

            if not (1 <= place <= 200):      place = 1
            if not (1 <= total_v <= 200):    total_v = 20
            if not (0 <= total_laps <= 999): total_laps = 0
            if gap > 999 or gap < 0: gap = 0.0

            return {
                'sim':          'LMU',
                'position':     place,
                'totalEntries': total_v,
                'fuelLevel':    round(fuel, 2),
                'fuelPercent':  round(fuel_pct, 1),
                'fuelPerLap':   self._fpl,
                'tyreCondition':'OK',
                'tyreWear':     90.0,
                'gapAhead':     round(gap, 2),
                'lap':          max(0, lap),
                'totalLaps':    total_laps,
                'rpm':          int(rpm),
                'gear':         gear,
                'track':        track,
                'weather':      'Dry',
            }
        except Exception as e:
            log.error(f'LMU read: {e}')
            return None

    def disconnect(self):
        shm_close(self.th, self.tb); shm_close(self.sh, self.sb)
        self.th = self.tb = self.sh = self.sb = None

# ── ACC READER (crash-safe) ───────────────────────────────────────────────────
class ACCReader:
    SNAP_SIZE = 4096

    def __init__(self):
        self.ph = self.pb = self.psize = None
        self.gh = self.gb = self.gsize = None
        self._fpl = None; self._lap_fuel = None; self._prev_lap = None

    def connect(self):
        self.ph, self.pb, self.psize = shm_open('Local\\acpmf_physics')
        self.gh, self.gb, self.gsize = shm_open('Local\\acpmf_graphics')
        return self.pb is not None and self.gb is not None

    def read(self):
        if not self.pb or not self.gb: return None
        try:
            praw = shm_snapshot(self.pb, self.psize, self.SNAP_SIZE)
            graw = shm_snapshot(self.gb, self.gsize, self.SNAP_SIZE)
            if len(praw) < 20 or len(graw) < 300:
                return None

            status = bi(graw, 4)
            if status == 0: return None

            fuel  = bf(praw, 12)
            tw_fl = bf(praw, 656) if len(praw) >= 660 else 0.9
            pos   = bi(graw, 60)
            lap   = bi(graw, 64)
            total = bi(graw, 200)
            gap   = abs(bf(graw, 276))

            if pos <= 0 or pos > 200: pos = 1
            fp  = min(100.0, max(0.0, (fuel / 120.0) * 100))
            twp = max(0.0, min(100.0, tw_fl * 100 if tw_fl <= 1.0 else tw_fl))
            tc  = 'OK' if twp > 70 else ('WARN' if twp > 40 else 'CRIT')

            if lap != self._prev_lap:
                if self._lap_fuel is not None:
                    c = self._lap_fuel - fuel
                    if 0.1 < c < 15: self._fpl = round(c, 2)
                self._lap_fuel = fuel; self._prev_lap = lap

            return {'sim': 'ACC', 'position': pos, 'totalEntries': 20,
                    'fuelLevel': round(fuel, 2), 'fuelPercent': round(fp, 1),
                    'fuelPerLap': self._fpl,
                    'tyreCondition': tc, 'tyreWear': round(twp, 1),
                    'gapAhead': round(gap, 2), 'lap': lap, 'totalLaps': total,
                    'rpm': 0, 'gear': 0, 'track': '', 'weather': 'Dry'}
        except Exception as e:
            log.debug(f'ACC: {e}'); return None

    def disconnect(self):
        shm_close(self.ph, self.pb); shm_close(self.gh, self.gb)
        self.ph = self.pb = self.gh = self.gb = None

# ── iRACING READER (crash-safe) ───────────────────────────────────────────────
class IRacingReader:
    SNAP_SIZE = 200000  # iRacing var headers can span a large region

    def __init__(self):
        self.h = self.b = self.size = None

    def connect(self):
        self.h, self.b, self.size = shm_open('$SuperFileMemory$')
        return self.b is not None

    def read(self):
        if not self.b: return None
        try:
            raw = shm_snapshot(self.b, self.size, self.SNAP_SIZE)
            if len(raw) < 200:
                return None
            if bi(raw, 0) < 1: return None

            num_vars   = bi(raw, 8)
            buf_offset = bi(raw, 36)
            if not (0 < num_vars < 2000): return None

            vals = {}
            for i in range(num_vars):
                base = 144 + i * 144
                if base + 48 > len(raw): break
                vtype = bi(raw, base)
                off   = bi(raw, base + 8)
                name  = bs(raw, base + 16, 32)
                addr  = buf_offset + off
                if addr + 8 > len(raw): continue
                try:
                    if vtype == 2:   vals[name] = bi(raw, addr)
                    elif vtype == 4: vals[name] = bf(raw, addr)
                    elif vtype == 5: vals[name] = bd(raw, addr)
                except: pass

            fp  = vals.get('FuelLevelPct', 0.5)
            fl  = vals.get('FuelLevel', 50.0)
            lfw = vals.get('LFwearM', 0.8)
            tc  = 'OK' if lfw > 0.6 else ('WARN' if lfw > 0.3 else 'CRIT')
            return {'sim': 'iRacing', 'position': vals.get('PlayerCarPosition', 1),
                    'totalEntries': vals.get('NumActiveCars', 1),
                    'fuelLevel': round(fl, 2), 'fuelPercent': round(fp * 100, 1),
                    'fuelPerLap': None,
                    'tyreCondition': tc, 'tyreWear': round(lfw * 100, 1),
                    'gapAhead': round(abs(vals.get('LapDeltaToSessionBestLap', 0)), 2),
                    'lap': vals.get('Lap', 0), 'totalLaps': vals.get('SessionLapsTotal', 0),
                    'rpm': int(vals.get('RPM', 0)), 'gear': vals.get('Gear', 0),
                    'track': '', 'weather': 'Rain' if vals.get('WeatherType', 0) == 1 else 'Dry'}
        except Exception as e:
            log.debug(f'iRacing: {e}'); return None

    def disconnect(self):
        shm_close(self.h, self.b); self.h = self.b = None

# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY ENGINE
# ══════════════════════════════════════════════════════════════════════════════
class StrategyEngine:
    def __init__(self):
        self.gap_history  = deque(maxlen=5)   # last 5 gap readings
        self.pos_history  = deque(maxlen=10)  # position over time

    def update(self, d):
        if d.get('gapAhead') is not None:
            self.gap_history.append(d['gapAhead'])
        if d.get('position'):
            self.pos_history.append(d['position'])

    def laps_to_empty(self, d):
        fpl = d.get('fuelPerLap')
        fuel = d.get('fuelLevel', 0)
        if fpl and fpl > 0:
            return round(fuel / fpl, 1)
        return None

    def pit_window(self, d):
        """Return lap to pit (3L safety margin) or None"""
        fpl = d.get('fuelPerLap')
        fuel = d.get('fuelLevel', 0)
        lap = d.get('lap', 0)
        if fpl and fpl > 0:
            laps_left_fuel = (fuel - 3.0) / fpl
            pit_lap = lap + int(laps_left_fuel)
            return pit_lap
        return None

    def gap_trend(self):
        if len(self.gap_history) < 3:
            return 'stable'
        recent = list(self.gap_history)
        delta = recent[-1] - recent[0]
        if delta < -0.3: return 'closing'
        if delta > +0.3: return 'dropping back'
        return 'stable'

    def position_trend(self):
        if len(self.pos_history) < 4:
            return None
        recent = list(self.pos_history)
        if recent[-1] < recent[0]: return 'gaining'
        if recent[-1] > recent[0]: return 'losing'
        return None

    def build_context(self, d):
        lte   = self.laps_to_empty(d)
        pw    = self.pit_window(d)
        gt    = self.gap_trend()
        pt    = self.position_trend()

        laps_left = ''
        if d.get('totalLaps', 0) > 0:
            remaining = d['totalLaps'] - d['lap']
            laps_left = f'{remaining} laps remaining'
        else:
            laps_left = 'lap count unknown'

        fpl_str = f"{d['fuelPerLap']}L/lap" if d.get('fuelPerLap') else 'consumption being measured'
        lte_str = f"{lte} laps of fuel remaining" if lte else 'fuel range unknown'
        pw_str  = f"pit window: lap {pw}" if pw else 'pit window calculating'

        lines = [
            f"SIM: {d.get('sim','?')} | TRACK: {d.get('track','unknown') or 'unknown'}",
            f"POSITION: P{d['position']}/{d['totalEntries']} | LAP: {d['lap']}/{d['totalLaps']} ({laps_left})",
            f"FUEL: {d['fuelLevel']}L ({d['fuelPercent']}%) | {fpl_str} | {lte_str} | {pw_str}",
            f"TYRES: {d['tyreCondition']} ({d['tyreWear']}%) | GAP AHEAD: {d['gapAhead']}s ({gt})",
            f"WEATHER: {d['weather']}",
        ]
        if pt: lines.append(f"POSITION TREND: {pt} positions")
        return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  DAEMON
# ══════════════════════════════════════════════════════════════════════════════
class PitWallDaemon:
    def __init__(self, cfg):
        self.groq_key    = cfg['groq_key']
        self.token       = cfg.get('supabase_token', '')
        self.style       = PERSONAS.get(cfg.get('persona', 'james'), PERSONAS['james'])
        self.push_key    = cfg.get('push_key', 'f8')
        self.user_id     = cfg.get('user_id', '')
        self.telem       = {}
        self.last_spoken = 0
        self.last_think  = 0
        self.is_speaking = False
        self.reader      = None
        self.running     = True
        self.strategy    = StrategyEngine()
        self._ptt_pressed   = False
        self._ptt_frames    = []
        self._ptt_recording = False

    def sys_prompt(self):
        return (
            f"You are an elite FIA-licensed race engineer with 20 years in F1 and WEC. {self.style} "
            "You receive LIVE telemetry. Speak in 1-2 sharp sentences like a real pit wall engineer on radio. "
            "Use F1 terminology: delta, undercut, overcut, tyre cliff, fuel saving, push, box box, manage. "
            "React to the data — if fuel is low, warn about pit window. If gap is closing, tell driver to push or defend. "
            "NEVER make up data. NEVER use tags like [neutral] or [serious]. "
            "If no critical update, reply exactly: SILENT"
        )

    def speak(self, raw):
        if self.is_speaking: return
        text = strip_tags(raw)
        if not text or text.upper() == 'SILENT': return
        def _go():
            self.is_speaking = True
            log.info(f'[ENG] {text}')
            tts(text)
            self.last_spoken = time.time()
            self.is_speaking = False
            if self.token:
                supa_log({'user_id': self.user_id, 'role': 'engineer', 'content': text,
                          'track': self.telem.get('track',''), 'sim': self.telem.get('sim',''),
                          'created_at': datetime.utcnow().isoformat()}, self.token)
        threading.Thread(target=_go, daemon=True).start()

    def think(self):
        now = time.time()
        if now - self.last_think < THINK_INTERVAL: return
        if now - self.last_spoken < MIN_SPEAK_GAP: return
        if self.is_speaking or not self.telem: return
        self.last_think = now
        ctx = self.strategy.build_context(self.telem)
        msg = ask_ai(self.sys_prompt(),
            f"LIVE TELEMETRY:\n{ctx}\n\nGive a brief strategic update or say SILENT.",
            self.groq_key)
        self.speak(msg)

    def check_critical(self):
        d = self.telem
        if not d or time.time() - self.last_spoken < 15: return
        ctx = self.strategy.build_context(d)

        # Fuel critical
        lte = self.strategy.laps_to_empty(d)
        if lte is not None and lte < 3:
            msg = ask_ai(self.sys_prompt(),
                f"LIVE TELEMETRY:\n{ctx}\n\nFUEL CRITICAL: only {lte} laps of fuel. Urgent pit call now.",
                self.groq_key)
            self.speak(msg); return

        # Tyre critical
        if d['tyreCondition'] == 'CRIT':
            msg = ask_ai(self.sys_prompt(),
                f"LIVE TELEMETRY:\n{ctx}\n\nTYRES CRITICAL. Box now or manage to pit window?",
                self.groq_key)
            self.speak(msg); return

        # Gap closing fast — attack opportunity
        gt = self.strategy.gap_trend()
        if gt == 'closing' and d['gapAhead'] < 0.8:
            msg = ask_ai(self.sys_prompt(),
                f"LIVE TELEMETRY:\n{ctx}\n\nGap closing fast at {d['gapAhead']}s. Attack or wait?",
                self.groq_key)
            self.speak(msg)

    # ── PTT + STT ──────────────────────────────────────────────────────────
    def _record(self):
        frames = []
        def cb(indata, *_):
            if self._ptt_recording: frames.append(indata.copy())
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', callback=cb):
                while self._ptt_recording: time.sleep(0.05)
        except Exception as e:
            log.warning(f'Record: {e}')
        self._ptt_frames = frames

    def _process_ptt(self):
        if not self._ptt_frames: return
        try:
            audio = np.concatenate(self._ptt_frames, axis=0)
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1); wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE); wf.writeframes(audio.tobytes())
            question = stt(buf.getvalue(), self.groq_key)
            if not question: return
            log.info(f'[DRIVER] {question}')
            ctx = self.strategy.build_context(self.telem) if self.telem else 'No telemetry yet.'
            msg = ask_ai(self.sys_prompt(),
                f"LIVE TELEMETRY:\n{ctx}\n\nDriver says: \"{question}\"\nRespond directly.",
                self.groq_key, smart=True)
            self.speak(msg)
        except Exception as e:
            log.error(f'PTT: {e}')

    def setup_ptt(self):
        key_map = {f'f{i}': getattr(pynput_kb.Key, f'f{i}') for i in range(1, 13)}
        key_map.update({'insert': pynput_kb.Key.insert, 'home': pynput_kb.Key.home,
                        'space': pynput_kb.Key.space})
        target = key_map.get(self.push_key.lower(), pynput_kb.Key.f8)

        def on_press(k):
            if k == target and not self._ptt_pressed:
                self._ptt_pressed = True
                self._ptt_recording = True
                self._ptt_frames = []
                log.info('[PTT] Listening...')
                threading.Thread(target=self._record, daemon=True).start()

        def on_release(k):
            if k == target and self._ptt_pressed:
                self._ptt_pressed = False
                self._ptt_recording = False
                log.info('[PTT] Processing...')
                threading.Thread(target=self._process_ptt, daemon=True).start()

        lst = pynput_kb.Listener(on_press=on_press, on_release=on_release)
        lst.daemon = True; lst.start()
        log.info(f'PTT ready: hold {self.push_key} to talk')

    def detect(self):
        for name, cls in [('iRacing', IRacingReader), ('ACC', ACCReader), ('LMU', LMUReader)]:
            try:
                r = cls()
                if r.connect():
                    d = r.read()
                    if d:
                        self.reader = r
                        self.telem  = d
                        self.strategy.update(d)
                        log.info(f'Sim: {name}')
                        return True
                    r.disconnect()
            except Exception as e:
                log.debug(f'{name}: {e}')
        log.warning('No sim found. Retrying...')
        return False

    def run(self):
        log.info('PitWall AI v5 starting...')
        self.setup_ptt()
        while self.running:
            if self.detect(): break
            time.sleep(5)

        self.speak(f"PitWall online. {self.telem.get('sim','Sim')} connected. Ready to engineer.")

        tick = 0
        while self.running:
            try:
                d = self.reader.read()
                if d:
                    self.telem = d
                    self.strategy.update(d)
                else:
                    log.warning('Sim lost. Searching...')
                    self.reader.disconnect(); self.reader = None
                    while self.running:
                        if self.detect(): break
                        time.sleep(5)

                self.think()
                tick += 1
                if tick % 5 == 0: self.check_critical()
                time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f'Loop: {e}'); time.sleep(2)

        if self.reader: self.reader.disconnect()
        pygame.mixer.quit()
        log.info('PitWall stopped.')
