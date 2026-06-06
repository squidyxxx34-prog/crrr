# PitWall AI — Desktop Daemon

Race engineer for your PC. Reads sim telemetry via shared memory, calls Groq AI, speaks strategy via TTS.

## Supported Sims
- iRacing (shared memory: `$SuperFileMemory$`)
- ACC (shared memory: `Local\acpmf_physics` + `Local\acpmf_graphics`)
- LMU / rFactor2 (shared memory: `$rFactor2SMMP_Buffer$`)

## Quick Start

### Option A — Run from source
```bash
pip install -r requirements.txt
python pitwall_launcher.py
```

### Option B — Build EXE (Windows)
```bash
build.bat
# Output: dist\PitWallAI.exe
```

## First Launch
The setup wizard asks for:
1. **Supabase login** — same account as simracingcoach.vercel.app
2. **Groq API key** — free at console.groq.com
3. **Engineer persona** — james / marco / hans / nick
4. **Push-to-talk key** — default F8

Config saved to `%APPDATA%\PitWall\config.json`
Logs saved to `%APPDATA%\PitWall\pitwall.log`

## Usage
- Double-click `PitWallAI.exe` — runs headless (no window)
- Press your **push-to-talk key** anytime for immediate advice
- Engineer speaks automatically every 30s + on critical events
- All conversations logged to Supabase by circuit

## Supabase Table Required
Run in Supabase SQL Editor:
```sql
create table conversations (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users,
  role text,
  content text,
  track text,
  sim text,
  created_at timestamptz default now()
);
alter table conversations enable row level security;
create policy "own convos" on conversations
  for all using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
```
