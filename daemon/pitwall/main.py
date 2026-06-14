"""
PitWall AI Daemon v4
- edge-tts (British male, en-GB-RyanNeural)
- Groq LLM (llama-3.3-70b) — key from config
- Groq STT (whisper-large-v3-turbo) — push to talk
- LMU / ACC / iRacing real shared memory
- Strips [tags] before speaking
"""

import sys, os, time, json, re, threading, ctypes, io, logging, wave, tempfile, asyncio
from datetime import datetime
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

GROQ_API       = 'https://api.groq.com/openai/v1'
SUPA_URL       = 'https://ofptqazlbbalebgqtwbr.supabase.co'
SUPA_KEY       = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mcHRxYXpsYmJhbGViZ3F0d2JyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODUwMzUsImV4cCI6MjA5NTM2MTAzNX0.aiiFgRcpmUBkJkfQSCPTWjT73hVjUaSARVohR80vNhM'
THINK_INTERVAL = 35
POLL_INTERVAL  = 2
MIN_SPEAK_GAP  = 25
SAMPLE_RATE    = 16000
TTS_VOICE      = 'en-GB-RyanNeural'  # British male

PERSONAS = {
    'james': 'Calm, precise British F1 engineer. Direct. Never panics.',
    'marco': 'Passionate Italian engineer. Tactical. Energetic.',
    'hans':  'German engineer. Ultra technical. Data-focused.',
    'nick':  'Australian engineer. Blunt. No-nonsense.',
}

KERNEL32 = ctypes.windll.kernel32

pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.mixer.init()

# ── TAG STRIP ──
def strip_tags(text):
    return re.sub(r'\[.*?\]', '', text).strip()

# ── TTS (edge-tts, free, British male) ──
def tts(text):
    clean = strip_tags(text)
    if not clean:
        return
    try:
        async def _speak():
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                tmp = f.name
            comm = edge_tts.Communicate(clean, TTS_VOICE, rate='+8%', volume='+0%')
            await comm.save(tmp)
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
        log.info(f'TTS: {clean[:60]}')
    except Exception as e:
        log.warning(f'TTS: {e}')

# ── STT (Groq Whisper, free) ──
def stt(wav_bytes, key):
    try:
        r = requests.post(
            f'{GROQ_API}/audio/transcriptions',
            headers={'Authorization': f'Bearer {key}'},
            files={'file': ('audio.wav', wav_bytes, 'audio/wav')},
            data={'model': 'whisper-large-v3-turbo', 'language': 'en'},
            timeout=10,
        )
        if r.status_code == 200:
            text = r.json().get('text', '').strip()
            log.info(f'STT: {text}')
            return text
        log.warning(f'STT {r.status_code}: {r.text[:80]}')
    except Exception as e:
        log.warning(f'STT: {e}')
    return ''

# ── AI (Groq LLM, free) ──
def ask_ai(system, prompt, key):
    try:
        r = requests.post(
            f'{GROQ_API}/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'max_tokens': 80,
                'temperature': 0.65,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': prompt},
                ],
            },
            timeout=8,
        )
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
        log.warning(f'AI {r.status_code}: {r.text[:80]}')
    except Exception as e:
        log.error(f'AI: {e}')
    return 'SILENT'

# ── SUPABASE ──
def supa_log(data, token):
    try:
        requests.post(f'{SUPA_URL}/rest/v1/conversations',
            headers={'apikey': SUPA_KEY, 'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json', 'Prefer': 'return=minimal'},
            json=data, timeout=4)
    except:
        pass

# ── SHARED MEMORY ──
def shm_open(name):
    h = KERNEL32.OpenFileMappingW(0x0004, False, name)
    if not h: return None, None
    b = KERNEL32.MapViewOfFile(h, 0x0004, 0, 0, 0)
    if not b: KERNEL32.CloseHandle(h); return None, None
    return h, b

def shm_close(h, b):
    if b: KERNEL32.UnmapViewOfFile(b)
    if h: KERNEL32.CloseHandle(h)

def shm_f(buf, off): return ctypes.c_float.from_address(buf + off).value
def shm_i(buf, off): return ctypes.c_int.from_address(buf + off).value
def shm_u(buf, off): return ctypes.c_uint.from_address(buf + off).value
def shm_d(buf, off): return ctypes.c_double.from_address(buf + off).value
def shm_s(buf, off, n): return ctypes.string_at(buf + off, n).decode('utf-8', errors='ignore').rstrip('\x00')

# ══════════════════════════════════════
#  iRACING
# ══════════════════════════════════════
class IRacingReader:
    NAME = '$SuperFileMemory$'
    def __init__(self): self.h = self.b = None
    def connect(self):
        self.h, self.b = shm_open(self.NAME)
        return self.b is not None
    def read(self):
        if not self.b: return None
        try:
            ver = shm_i(self.b, 0)
            if ver < 1: return None
            num_vars   = shm_i(self.b, 8)
            buf_offset = shm_i(self.b, 36)
            if not (0 < num_vars < 5000): return None
            vals = {}
            for i in range(num_vars):
                base   = 144 + i * 144
                vtype  = shm_i(self.b, base)
                offset = shm_i(self.b, base + 8)
                name   = shm_s(self.b, base + 16, 32)
                addr   = self.b + buf_offset + offset
                try:
                    if vtype == 2:   vals[name] = shm_i(addr, 0)
                    elif vtype == 4: vals[name] = shm_f(addr, 0)
                    elif vtype == 5: vals[name] = shm_d(addr, 0)
                except: pass
            fp  = vals.get('FuelLevelPct', 0.5)
            fl  = vals.get('FuelLevel', 50.0)
            lfw = vals.get('LFwearM', 0.8)
            tc  = 'OK' if lfw > 0.6 else ('WARN' if lfw > 0.3 else 'CRIT')
            return {'sim': 'iRacing',
                    'position': vals.get('PlayerCarPosition', 1),
                    'totalEntries': vals.get('NumActiveCars', 1),
                    'fuelPercent': round(fp * 100, 1),
                    'fuelLevel': round(fl, 2),
                    'tyreCondition': tc,
                    'tyreWear': round(lfw * 100, 1),
                    'gapAhead': round(abs(vals.get('LapDeltaToSessionBestLap', 0)), 2),
                    'lap': vals.get('Lap', 0),
                    'totalLaps': vals.get('SessionLapsTotal', 0),
                    'weather': 'Rain' if vals.get('WeatherType', 0) == 1 else 'Dry',
                    'trackName': ''}
        except Exception as e:
            log.debug(f'iRacing: {e}'); return None
    def disconnect(self): shm_close(self.h, self.b); self.h = self.b = None

# ══════════════════════════════════════
#  ACC
# ══════════════════════════════════════
class ACCReader:
    def __init__(self): self.ph = self.pb = self.gh = self.gb = None
    def connect(self):
        self.ph, self.pb = shm_open('Local\\acpmf_physics')
        self.gh, self.gb = shm_open('Local\\acpmf_graphics')
        return self.pb is not None and self.gb is not None
    def read(self):
        if not self.pb or not self.gb: return None
        try:
            status = shm_i(self.gb, 4)
            if status == 0: return None
            fuel   = shm_f(self.pb, 12)
            tw_fl  = shm_f(self.pb, 656)
            pos    = shm_i(self.gb, 60)
            lap    = shm_i(self.gb, 64)
            total  = shm_i(self.gb, 200)
            gap    = abs(shm_f(self.gb, 276))
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

# ══════════════════════════════════════
#  LMU (rFactor2 shared memory plugin)
# ══════════════════════════════════════
class LMUReader:
    # rF2/LMU shared memory buffer names
    TELEM_NAMES  = ['$rFactor2SMMP_Telemetry$', '$LMU_SMM_Telemetry$', '$rFactor2SMMP_Buffer1$']
    SCORE_NAMES  = ['$rFactor2SMMP_Scoring$',   '$LMU_SMM_Scoring$']

    # rF2Telemetry header offsets
    HDR_VERSION_BEGIN = 0   # uint32
    HDR_VERSION_END   = 4   # uint32
    HDR_BYTES_HINT    = 8   # int32
    HDR_NUM_VEHICLES  = 12  # int32
    HDR_VEHICLES      = 16  # rF2VehicleTelemetry[]

    # rF2VehicleTelemetry offsets (from vehicle base)
    VT_ID           = 0    # int32
    VT_DELTA_TIME   = 8    # double
    VT_ELAPSED_TIME = 16   # double
    VT_LAP_NUMBER   = 24   # int32
    VT_TRACK_NAME   = 96   # char[64]
    VT_GEAR         = 352  # int32
    VT_ENGINE_RPM   = 356  # float
    VT_FUEL         = 432  # float  ← key field

    # rF2Scoring header
    SC_NUM_VEHICLES  = 12  # int32
    SC_VEHICLES      = 16  # rF2VehicleScoring[]

    # rF2VehicleScoring offsets
    VS_VEHICLE_NAME = 0    # char[64]
    VS_TOTAL_LAPS   = 72   # int16
    VS_LAP_DIST     = 76   # float
    VS_FINISH_STATUS= 90   # int8
    VS_PLACE        = 108  # uint8
    VS_TIME_BEHIND  = 116  # double

    def __init__(self):
        self.th = self.tb = None
        self.sh = self.sb = None
        self._prev_fuel = None
        self._fuel_per_lap = None
        self._lap_fuel_start = None
        self._lap_num_prev = None

    def connect(self):
        for name in self.TELEM_NAMES:
            h, b = shm_open(name)
            if b:
                self.th, self.tb = h, b
                log.info(f'LMU telem: {name}')
                break
        for name in self.SCORE_NAMES:
            h, b = shm_open(name)
            if b:
                self.sh, self.sb = h, b
                log.info(f'LMU score: {name}')
                break
        return self.tb is not None

    def _read_telem(self):
        if not self.tb: return {}
        try:
            num_v = shm_i(self.tb, self.HDR_NUM_VEHICLES)
            if num_v <= 0 or num_v > 128: return {}
            vbase = self.tb + self.HDR_VEHICLES
            fuel  = shm_f(self.tb, self.HDR_VEHICLES + self.VT_FUEL)
            lap   = shm_i(self.tb, self.HDR_VEHICLES + self.VT_LAP_NUMBER)
            rpm   = shm_f(self.tb, self.HDR_VEHICLES + self.VT_ENGINE_RPM)
            gear  = shm_i(self.tb, self.HDR_VEHICLES + self.VT_GEAR)
            track = shm_s(self.tb, self.HDR_VEHICLES + self.VT_TRACK_NAME, 64)
            return {'fuel': fuel, 'lap': lap, 'rpm': rpm, 'gear': gear, 'track': track, 'num_v': num_v}
        except Exception as e:
            log.debug(f'LMU telem read: {e}')
            return {}

    def _read_score(self):
        if not self.sb: return {}
        try:
            num_v = shm_i(self.sb, self.SC_NUM_VEHICLES)
            if num_v <= 0 or num_v > 128: return {}
            # Player vehicle is typically first (index 0)
            sbase = self.SC_VEHICLES
            place      = ctypes.c_uint8.from_address(self.sb + sbase + self.VS_PLACE).value
            total_laps = ctypes.c_int16.from_address(self.sb + sbase + self.VS_TOTAL_LAPS).value
            time_behind= shm_d(self.sb, sbase + self.VS_TIME_BEHIND)
            return {'place': place, 'total_v': num_v, 'total_laps': total_laps,
                    'gap': abs(time_behind)}
        except Exception as e:
            log.debug(f'LMU score read: {e}')
            return {}

    def read(self):
        if not self.tb: return None
        try:
            t = self._read_telem()
            s = self._read_score()
            if not t: return None

            fuel = t.get('fuel', 50.0)
            lap  = t.get('lap', 0)
            rpm  = t.get('rpm', 0)

            # Validate fuel
            if not (0 <= fuel <= 300): fuel = 50.0
            fuel_pct = min(100.0, max(0.0, (fuel / 120.0) * 100))

            # Track fuel consumption per lap
            if lap != self._lap_num_prev:
                if self._lap_fuel_start is not None and self._lap_num_prev is not None:
                    self._fuel_per_lap = round(self._lap_fuel_start - fuel, 3)
                    log.info(f'Fuel/lap: {self._fuel_per_lap}L')
                self._lap_fuel_start = fuel
                self._lap_num_prev = lap

            # Tyre (no offset confirmed yet — use default)
            tc = 'OK'

            place      = s.get('place', 1) or 1
            total_v    = s.get('total_v', 20) or 20
            total_laps = s.get('total_laps', 0)
            gap        = s.get('gap', 0.0)
            track      = t.get('track', '')

            return {
                'sim':          'LMU',
                'position':     max(1, min(place, 200)),
                'totalEntries': max(1, total_v),
                'fuelPercent':  round(fuel_pct, 1),
                'fuelLevel':    round(fuel, 2),
                'fuelPerLap':   self._fuel_per_lap,
                'tyreCondition':tc,
                'tyreWear':     90.0,
                'gapAhead':     round(gap, 2),
                'lap':          max(0, lap),
                'totalLaps':    max(0, total_laps),
                'rpm':          int(rpm),
                'track':        track,
                'weather':      'Dry',
            }
        except Exception as e:
            log.error(f'LMU read: {e}')
            return None

    def disconnect(self):
        shm_close(self.th, self.tb)
        shm_close(self.sh, self.sb)
        self.th = self.tb = self.sh = self.sb = None

# ══════════════════════════════════════
#  DAEMON
# ══════════════════════════════════════
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
        self._ptt_pressed = False
        self._ptt_frames  = []
        self._ptt_recording = False

    def sys_prompt(self):
        return (
            f"You are a professional sim racing engineer on the pit wall. {self.style} "
            "Give SHORT, DIRECT advice — max 2 sentences. "
            "You receive REAL telemetry from the car. Comment only on what's relevant. "
            "Never make up data. Never use tags like [neutral]. "
            "If nothing meaningful to say, reply exactly: SILENT"
        )

    def ctx(self):
        d = self.telem
        if not d: return 'No data yet.'
        laps_left = (d['totalLaps'] - d['lap']) if d.get('totalLaps', 0) > 0 else '?'
        fpl = f"{d['fuelPerLap']}L/lap" if d.get('fuelPerLap') else 'unknown consumption'
        return (
            f"Sim: {d.get('sim','?')} | Track: {d.get('track','unknown')} | "
            f"Position: P{d['position']}/{d['totalEntries']} | "
            f"Lap: {d['lap']}/{d['totalLaps']} ({laps_left} laps left) | "
            f"Fuel: {d['fuelLevel']}L ({d['fuelPercent']}%, {fpl}) | "
            f"Tyres: {d['tyreCondition']} ({d['tyreWear']}%) | "
            f"Gap ahead: {d['gapAhead']}s | Weather: {d['weather']}"
        )

    def speak(self, raw_text):
        if self.is_speaking: return
        def _go():
            self.is_speaking = True
            text = strip_tags(raw_text)
            log.info(f'[ENG] {text}')
            tts(text)
            self.last_spoken = time.time()
            self.is_speaking = False
            if self.token:
                supa_log({'user_id': self.user_id, 'role': 'engineer', 'content': text,
                          'track': self.telem.get('track', ''), 'sim': self.telem.get('sim', ''),
                          'created_at': datetime.utcnow().isoformat()}, self.token)
        threading.Thread(target=_go, daemon=True).start()

    def think(self):
        now = time.time()
        if now - self.last_think < THINK_INTERVAL: return
        if now - self.last_spoken < MIN_SPEAK_GAP: return
        if self.is_speaking or not self.telem: return
        self.last_think = now
        msg = ask_ai(self.sys_prompt(),
            f"Telemetry: {self.ctx()}\nGive a brief, relevant strategic update or say SILENT.",
            self.groq_key)
        if msg and msg.upper() != 'SILENT':
            self.speak(msg)

    def check_critical(self):
        d = self.telem
        if not d or time.time() - self.last_spoken < 15: return
        if d['tyreCondition'] == 'CRIT':
            msg = ask_ai(self.sys_prompt(),
                f"Telemetry: {self.ctx()}\nTYRES CRITICAL. Urgent pit call or advice.", self.groq_key)
            if msg and msg.upper() != 'SILENT': self.speak(msg); return
        if d['fuelPercent'] < 8:
            msg = ask_ai(self.sys_prompt(),
                f"Telemetry: {self.ctx()}\nFUEL CRITICAL — under 8%. Urgent advice.", self.groq_key)
            if msg and msg.upper() != 'SILENT': self.speak(msg)

    # ── PTT + STT ──
    def _record_thread(self):
        frames = []
        def callback(indata, frame_count, time_info, status):
            if self._ptt_recording:
                frames.append(indata.copy())
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', callback=callback):
                while self._ptt_recording:
                    time.sleep(0.05)
        except Exception as e:
            log.warning(f'Record: {e}')
        self._ptt_frames = frames

    def _process_ptt(self):
        if not self._ptt_frames:
            return
        try:
            audio = np.concatenate(self._ptt_frames, axis=0)
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio.tobytes())
            question = stt(buf.getvalue(), self.groq_key)
            if question:
                log.info(f'[DRIVER] {question}')
                msg = ask_ai(self.sys_prompt(),
                    f"Telemetry: {self.ctx()}\nDriver asks: {question}\nAnswer directly.",
                    self.groq_key)
                if msg and msg.upper() != 'SILENT':
                    self.speak(msg)
        except Exception as e:
            log.error(f'PTT process: {e}')

    def setup_ptt(self):
        key_map = {
            'f1': pynput_kb.Key.f1,  'f2': pynput_kb.Key.f2,
            'f3': pynput_kb.Key.f3,  'f4': pynput_kb.Key.f4,
            'f5': pynput_kb.Key.f5,  'f6': pynput_kb.Key.f6,
            'f7': pynput_kb.Key.f7,  'f8': pynput_kb.Key.f8,
            'f9': pynput_kb.Key.f9,  'f10': pynput_kb.Key.f10,
            'f11': pynput_kb.Key.f11,'f12': pynput_kb.Key.f12,
            'insert': pynput_kb.Key.insert, 'home': pynput_kb.Key.home,
        }
        target = key_map.get(self.push_key.lower(), pynput_kb.Key.f8)

        def on_press(key):
            if key == target and not self._ptt_pressed:
                self._ptt_pressed = True
                self._ptt_recording = True
                self._ptt_frames = []
                log.info('[PTT] Recording...')
                threading.Thread(target=self._record_thread, daemon=True).start()

        def on_release(key):
            if key == target and self._ptt_pressed:
                self._ptt_pressed = False
                self._ptt_recording = False
                log.info('[PTT] Processing...')
                threading.Thread(target=self._process_ptt, daemon=True).start()

        lst = pynput_kb.Listener(on_press=on_press, on_release=on_release)
        lst.daemon = True
        lst.start()
        log.info(f'PTT: {self.push_key} (hold to speak)')

    def detect(self):
        for name, cls in [('iRacing', IRacingReader), ('ACC', ACCReader), ('LMU', LMUReader)]:
            try:
                r = cls()
                if r.connect():
                    d = r.read()
                    if d:
                        self.reader = r
                        log.info(f'Sim: {name}')
                        return True
                    r.disconnect()
            except Exception as e:
                log.debug(f'{name}: {e}')
        log.warning('No sim. Retrying in 5s...')
        return False

    def run(self):
        log.info('PitWall AI v4 starting...')
        self.setup_ptt()
        while self.running:
            if self.detect(): break
            time.sleep(5)

        self.speak(f"PitWall online. {self.telem.get('sim','Sim')} connected. I'm watching.")

        tick = 0
        while self.running:
            try:
                d = self.reader.read()
                if d:
                    self.telem = d
                else:
                    log.warning('Sim lost...')
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
        log.info('Stopped.')
