"""
PitWall AI — Setup Wizard
First-time configuration. Saves config to %APPDATA%\PitWall\config.json
"""

import json
import sys
import os
import requests
from pathlib import Path

APP_DIR  = Path(os.getenv('APPDATA', '.')) / 'PitWall'
CFG_FILE = APP_DIR / 'config.json'
APP_DIR.mkdir(parents=True, exist_ok=True)

SUPA_URL = 'https://ofptqazlbbalebgqtwbr.supabase.co'
SUPA_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mcHRxYXpsYmJhbGViZ3F0d2JyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODUwMzUsImV4cCI6MjA5NTM2MTAzNX0.aiiFgRcpmUBkJkfQSCPTWjT73hVjUaSARVohR80vNhM'
GROQ_API = 'https://api.groq.com/openai/v1'

PERSONAS = ['james', 'marco', 'hans', 'nick']
KEYS     = ['f1','f2','f3','f4','f5','f6','f7','f8','f9','f10','space','ctrl+space','insert','home']

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def banner():
    print("""
╔══════════════════════════════════════╗
║       PITWALL AI — SETUP             ║
║       Race Engineer Configuration    ║
╚══════════════════════════════════════╝
""")

def ask(prompt, default=None, choices=None):
    while True:
        suffix = f' [{default}]' if default else ''
        if choices:
            suffix += f' ({"/".join(choices)})'
        val = input(f'{prompt}{suffix}: ').strip()
        if not val and default:
            return default
        if choices and val not in choices:
            print(f'  → Choose from: {", ".join(choices)}')
            continue
        if val:
            return val

def sign_in_supabase(email, password):
    r = requests.post(
        f'{SUPA_URL}/auth/v1/token?grant_type=password',
        headers={'apikey': SUPA_KEY, 'Content-Type': 'application/json'},
        json={'email': email, 'password': password},
        timeout=8,
    )
    if r.status_code == 200:
        d = r.json()
        return d.get('access_token'), d.get('user', {}).get('id')
    return None, None

def validate_groq(key):
    r = requests.get(
        f'{GROQ_API}/models',
        headers={'Authorization': f'Bearer {key}'},
        timeout=5,
    )
    return r.status_code == 200

def main():
    clear()
    banner()

    existing = {}
    if CFG_FILE.exists():
        with open(CFG_FILE) as f:
            existing = json.load(f)
        print(f'  Existing config found for: {existing.get("email", "?")}')
        choice = ask('  Use existing config? Launch daemon now', default='y', choices=['y', 'n'])
        if choice == 'y':
            return existing

    print('  Step 1/4 — Supabase Login')
    print('  Use the same account as simracingcoach.vercel.app\n')

    token = None
    user_id = None
    for attempt in range(3):
        email    = ask('  Email')
        password = ask('  Password')
        print('  Signing in...')
        token, user_id = sign_in_supabase(email, password)
        if token:
            print(f'  ✅ Signed in as {email}\n')
            break
        print(f'  ❌ Invalid credentials. Try again. ({attempt+1}/3)\n')

    if not token:
        print('  Login failed. Exiting.')
        sys.exit(1)

    print('  Step 2/4 — Groq API Key')
    print('  Get your free key at: console.groq.com\n')
    groq_key = None
    for attempt in range(3):
        key = ask('  Groq API key')
        print('  Validating...')
        if validate_groq(key):
            groq_key = key
            print('  ✅ Groq key valid\n')
            break
        print(f'  ❌ Invalid Groq key. ({attempt+1}/3)\n')

    if not groq_key:
        print('  Groq key invalid. Exiting.')
        sys.exit(1)

    print('  Step 3/4 — Engineer Persona')
    print('  james = 🇬🇧 Calm F1 style')
    print('  marco = 🇮🇹 Passionate tactical')
    print('  hans  = 🇩🇪 Technical data-driven')
    print('  nick  = 🇦🇺 Direct no-nonsense\n')
    persona = ask('  Choose persona', default='james', choices=PERSONAS)

    print('\n  Step 4/4 — Push-to-Talk Key')
    print('  Press this key anytime to get immediate engineer advice.')
    print(f'  Available: {", ".join(KEYS)}\n')
    push_key = ask('  Key binding', default='f8', choices=KEYS)

    cfg = {
        'email':          email,
        'supabase_token': token,
        'user_id':        user_id,
        'groq_key':       groq_key,
        'persona':        persona,
        'push_key':       push_key,
    }

    with open(CFG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

    print(f'\n  ✅ Config saved to {CFG_FILE}')
    print('  PitWall AI is ready.\n')
    return cfg

if __name__ == '__main__':
    main()
