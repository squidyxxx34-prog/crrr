"""
PitWall AI Daemon v3
- Zero CMD windows (pynput replaces keyboard)
- LMU / ACC / iRacing shared memory
- Groq AI + TTS
- Supabase logging
"""

import sys, os, time, json, threading, ctypes, io, logging
from datetime import datetime
from pathlib import Path

# ── PATHS ──
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
from pynput import keyboard as pynput_kb

# ── CONSTANTS ──
GROQ_API       = 'https://api.groq.com/openai/v1'
SUPA_URL       = 'https://ofptqazlbbalebgqtwbr.supabase.co'
SUPA_KEY       = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mcHRxYXpsYmJhbGViZ3F0d2JyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODUwMzUsImV4cCI6MjA5NTM2MTAzNX0.aiiFgRcpmUBkJkfQSCPTWjT73hVjUaSARVohR80vNhM'
THINK_INTERVAL = 30
POLL_INTERVAL  = 2
MIN_SPEAK_GAP  = 20

PERSONAS = {
    'james': {'voice': 'Fritz-PlayAI',   'style': 'Calm, precise British F1 engineer. Short sentences. Never panics.'},
    'marco': {'voice': 'Celeste-PlayAI', 'style': 'Passionate Italian engineer. Tactical. Energetic.'},
    'hans':  {'voice': 'Fritz-PlayAI',   'style': 'German engineer. Ultra technical. Data-focused.'},
    'nick':  {'voice': 'Chip-PlayAI',    'style': 'Australian engineer. Direct, no nonsense.'},
}

KERNEL32 = ctypes.windll.kernel32

# ── AUDIO ──
pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.mixer.init()

def play_audio(data):
    try:
        pygame.mixer.Sound(io.BytesIO(data)).play()
        while pygame.mixer.get_busy():
            time.sleep(0.05)
    except Exception as e:
        log.error(f'Audio: {e}')

# ── GROQ ──
# Simplified TTS function using Windows SAPI5
def tts(text, voice, key):
    try:
        import asyncio
        import edge_tts
        import tempfile, os

        # Ryan = British male, perfect for F1 engineer
        VOICE = "en-GB-RyanNeural"

        async def _speak():
            communicate = edge_tts.Communicate(text, VOICE, rate="+5%")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp = f.name
            await communicate.save(tmp)
            return tmp

        tmp = asyncio.run(_speak())
        pygame.mixer.music.load(tmp)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.unload()
        try:
            os.remove(tmp)
        except:
            pass
        log.info(f"TTS: {text[:60]}")
    except Exception as e:
        log.warning(f"TTS: {e}")

def ask_ai(system, prompt, key):
    try:
        r = requests.post(f'{GROQ_API}/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'model': 'llama-3.3-70b-versatile', 'max_tokens': 80, 'temperature': 0.7,
                  'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]},
            timeout=8)
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.error(f'AI: {e}')
    return 'SILENT'

def supa_log(data, token):
    try:
        requests.post(f'{SUPA_URL}/rest/v1/conversations',
            headers={'apikey': SUPA_KEY, 'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json', 'Prefer': 'return=minimal'},
            json=data, timeout=4)
    except: pass

# ── SHARED MEMORY HELPERS ──
def shm_open(name):
    h = KERNEL32.OpenFileMappingW(0x0004, False, name)
    if not h: return None, None
    b = KERNEL32.MapViewOfFile(h, 0x0004, 0, 0, 0)
    if not b: KERNEL32.CloseHandle(h); return None, None
    return h, b

def shm_close(h, b):
    if b: KERNEL32.UnmapViewOfFile(b)
    if h: KERNEL32.CloseHandle(h)

def shm_float(buf, offset):
    return ctypes.c_float.from_address(buf + offset).value

def shm_int(buf, offset):
    return ctypes.c_int.from_address(buf + offset).value

# ── iRACING READER ──
class IRacingReader:
    NAME = '$SuperFileMemory$'
    def __init__(self): self.h = self.b = None
    def connect(self):
        self.h, self.b = shm_open(self.NAME)
        return self.b is not None
    def read(self):
        if not self.b: return None
        try:
            ver = shm_int(self.b, 0)
            if ver < 1: return None
            num_vars   = shm_int(self.b, 8)
            var_offset = shm_int(self.b, 16)
            buf_offset = shm_int(self.b, 36)
            if not (0 < num_vars < 5000): return None
            vals = {}
            for i in range(num_vars):
                base   = 144 + i * 144
                vtype  = shm_int(self.b, base)
                offset = shm_int(self.b, base + 8)
                name   = ctypes.string_at(self.b + base + 16, 32).decode('latin1').rstrip('\x00')
                addr   = self.b + buf_offset + offset
                try:
                    if vtype == 2:   vals[name] = shm_int(addr, 0)
                    elif vtype == 4: vals[name] = shm_float(addr, 0)
                except: pass
            fp  = vals.get('FuelLevelPct', 0.5)
            fl  = vals.get('FuelLevel', 50.0)
            lfw = vals.get('LFwearM', 0.8)
            tc  = 'OK' if lfw > 0.6 else ('WARN' if lfw > 0.3 else 'CRIT')
            return {'sim': 'iRacing', 'position': vals.get('PlayerCarPosition', 1),
                    'totalEntries': vals.get('NumActiveCars', 1),
                    'fuelPercent': round(fp * 100, 1), 'fuelLevel': round(fl, 2),
                    'tyreCondition': tc, 'tyreWear': round(lfw * 100, 1),
                    'gapAhead': round(abs(vals.get('LapDeltaToSessionBestLap', 0)), 2),
                    'lap': vals.get('Lap', 0), 'totalLaps': vals.get('SessionLapsTotal', 0),
                    'weather': 'Rain' if vals.get('WeatherType', 0) == 1 else 'Dry', 'trackName': ''}
        except Exception as e:
            log.debug(f'iRacing: {e}'); return None
    def disconnect(self): shm_close(self.h, self.b); self.h = self.b = None

# ── ACC READER ──
class ACCReader:
    def __init__(self): self.ph = self.pb = self.gh = self.gb = None
    def connect(self):
        self.ph, self.pb = shm_open('Local\\acpmf_physics')
        self.gh, self.gb = shm_open('Local\\acpmf_graphics')
        return self.pb is not None and self.gb is not None
    def read(self):
        if not self.pb or not self.gb: return None
        try:
            status = shm_int(self.gb, 4)
            if status == 0: return None
            fuel   = shm_float(self.pb, 12)
            tw_fl  = shm_float(self.pb, 656)
            pos    = shm_int(self.gb, 60)
            lap    = shm_int(self.gb, 64)
            total  = shm_int(self.gb, 200)
            gap    = abs(shm_float(self.gb, 276))
            if pos <= 0 or pos > 200: pos = 1
            fp  = min(100.0, max(0.0, (fuel / 120.0) * 100))
            twp = max(0.0, min(100.0, tw_fl))
            tc  = 'OK' if twp > 70 else ('WARN' if twp > 40 else 'CRIT')
            return {'sim': 'ACC', 'position': pos, 'totalEntries': 20,
                    'fuelPercent': round(fp, 1), 'fuelLevel': round(fuel, 2),
                    'tyreCondition': tc, 'tyreWear': round(twp, 1),
                    'gapAhead': round(gap, 2), 'lap': lap, 'totalLaps': total,
                    'weather': 'Dry', 'trackName': ''}
        except Exception as e:
            log.debug(f'ACC: {e}'); return None
    def disconnect(self):
        shm_close(self.ph, self.pb); shm_close(self.gh, self.gb)
        self.ph = self.pb = self.gh = self.gb = None

# ── LMU READER ──
class LMUReader:
    NAMES = [
        '$LMU_SMM_Telemetry$',
        '$rFactor2SMMP_Telemetry$',
        '$rFactor2SMMP_Buffer1$',
        '$rFactor2SMMP_Buffer$',
    ]
    def __init__(self): self.h = self.b = None
    def connect(self):
        for name in self.NAMES:
            h, b = shm_open(name)
            if b:
                self.h, self.b = h, b
                log.info(f'LMU shm: {name}')
                return True
        return False
    def read(self):
        if not self.b:
            return None
        try:
            # LMU buffer is valid — return default data
            # In real use, we'd parse offsets here, but for now just confirm connection
            return {
                'sim': 'LMU',
                'position': 1,
                'totalEntries': 20,
                'fuelPercent': 75.0,
                'fuelLevel': 90.0,
                'tyreCondition': 'OK',
                'tyreWear': 85.0,
                'gapAhead': 0.0,
                'lap': 0,
                'totalLaps': 0,
                'weather': 'Dry',
                'trackName': '',
            }
        except Exception as e:
            log.error(f'LMU read: {e}')
            return None
    def disconnect(self): shm_close(self.h, self.b); self.h = self.b = None

# ══════════════════════════════════════
#  DAEMON
# ══════════════════════════════════════
class PitWallDaemon:
    def __init__(self, cfg):
        self.groq_key    = cfg['groq_key']
        self.token       = cfg['supabase_token']
        self.persona     = PERSONAS.get(cfg.get('persona', 'james'), PERSONAS['james'])
        self.push_key    = cfg.get('push_key', 'f8')
        self.user_id     = cfg.get('user_id', '')
        self.telem       = {}
        self.last_spoken = 0
        self.last_think  = 0
        self.is_speaking = False
        self.reader      = None
        self.running     = True
        self._ptt_pressed = False

    def sys_prompt(self):
        return (
            f"You are a professional sim racing engineer. {self.persona['style']} "
            "Max 2 sentences. Speak directly to the driver. "
            "Add ONE vocal direction tag before your message to match the emotion: "
            "[neutral] for normal updates, [serious] for warnings, [urgent] for critical alerts. "
            "Example: [neutral] Fuel at 45%, we have plenty of laps left. "
            "If nothing important to say: reply exactly SILENT"
        )

    def ctx(self):
        d = self.telem
        if not d: return ''
        ll = (d['totalLaps'] - d['lap']) if d.get('totalLaps', 0) > 0 else '?'
        return (f"Sim:{d.get('sim','?')} P{d['position']}/{d['totalEntries']} "
                f"Fuel:{d['fuelPercent']:.0f}%({d['fuelLevel']}L) "
                f"Tyres:{d['tyreCondition']}({d['tyreWear']}%) "
                f"Gap:{d['gapAhead']}s Lap:{d['lap']}/{d['totalLaps']}({ll} left) "
                f"Weather:{d['weather']}")

    def speak(self, text):
        if self.is_speaking: return
        def _go():
            self.is_speaking = True
            log.info(f'[ENG] {text}')
            tts(text, self.persona['voice'], self.groq_key)
            self.last_spoken = time.time()
            self.is_speaking = False
            supa_log({'user_id': self.user_id, 'role': 'engineer', 'content': text,
                      'track': self.telem.get('trackName', ''), 'sim': self.telem.get('sim', ''),
                      'created_at': datetime.utcnow().isoformat()}, self.token)
        threading.Thread(target=_go, daemon=True).start()

    def think(self):
        now = time.time()
        if now - self.last_think < THINK_INTERVAL: return
        if now - self.last_spoken < MIN_SPEAK_GAP: return
        if self.is_speaking or not self.telem: return
        self.last_think = now
        msg = ask_ai(self.sys_prompt(), f"{self.ctx()}\nSay something useful or SILENT.", self.groq_key)
        if msg and msg != 'SILENT': self.speak(msg)

    def check_critical(self):
        d = self.telem
        if not d or time.time() - self.last_spoken < MIN_SPEAK_GAP: return
        if d['tyreCondition'] == 'CRIT':
            msg = ask_ai(self.sys_prompt(), f"{self.ctx()}\nTyres CRITICAL. Urgent advice.", self.groq_key)
            if msg and msg != 'SILENT': self.speak(msg); return
        if d['fuelPercent'] < 8:
            msg = ask_ai(self.sys_prompt(), f"{self.ctx()}\nFuel critically low. Urgent advice.", self.groq_key)
            if msg and msg != 'SILENT': self.speak(msg)

    def on_ptt(self):
        if self.is_speaking or not self.telem: return
        log.info('[PTT]')
        msg = ask_ai(self.sys_prompt(),
            f"{self.ctx()}\nDriver pressed talk. Give best strategic advice now.", self.groq_key)
        if msg and msg != 'SILENT': self.speak(msg)

    def setup_ptt(self):
        # Map push-to-talk key using pynput (no CMD window)
        key_map = {
            'f1': pynput_kb.Key.f1, 'f2': pynput_kb.Key.f2,
            'f3': pynput_kb.Key.f3, 'f4': pynput_kb.Key.f4,
            'f5': pynput_kb.Key.f5, 'f6': pynput_kb.Key.f6,
            'f7': pynput_kb.Key.f7, 'f8': pynput_kb.Key.f8,
            'f9': pynput_kb.Key.f9, 'f10': pynput_kb.Key.f10,
            'f11': pynput_kb.Key.f11, 'f12': pynput_kb.Key.f12,
            'insert': pynput_kb.Key.insert, 'home': pynput_kb.Key.home,
            'space': pynput_kb.Key.space,
        }
        target = key_map.get(self.push_key.lower())

        def on_press(key):
            if key == target and not self._ptt_pressed:
                self._ptt_pressed = True
                threading.Thread(target=self.on_ptt, daemon=True).start()

        def on_release(key):
            if key == target:
                self._ptt_pressed = False

        listener = pynput_kb.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        log.info(f'PTT key: {self.push_key}')

    def detect(self):
        for name, cls in [('iRacing', IRacingReader), ('ACC', ACCReader), ('LMU', LMUReader)]:
            try:
                r = cls()
                if r.connect():
                    d = r.read()
                    if d:
                        self.reader = r
                        log.info(f'Detected: {name}')
                        return True
                    r.disconnect()
            except Exception as e:
                log.debug(f'{name} probe: {e}')
        log.warning('No sim found. Retrying in 5s...')
        return False

    def run(self):
        log.info('PitWall AI v3 starting...')
        self.setup_ptt()

        while self.running:
            if self.detect(): break
            time.sleep(5)

        sim_name = self.reader.__class__.__name__.replace('Reader', '')
        self.speak(f"PitWall online. {sim_name} connected. I'm watching.")

        tick = 0
        while self.running:
            try:
                d = self.reader.read()
                if d:
                    self.telem = d
                else:
                    log.warning('Sim lost. Searching...')
                    self.reader.disconnect()
                    self.reader = None
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
                log.error(f'Loop: {e}')
                time.sleep(2)

        if self.reader: self.reader.disconnect()
        pygame.mixer.quit()
        log.info('PitWall stopped.')
