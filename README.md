# PitWall AI 🏎️

**AI Race Engineer — live telemetry coaching in your ear.**

Connect your sim. Open the app on your phone. Hear your engineer during the race.

---

## What it does

- Connects directly to your sim PC via IP (like SimRacing Dashboard)
- Monitors live telemetry: position, fuel, tyre wear, gaps, weather
- AI engineer speaks to you via your phone's text-to-speech
- Reacts automatically to critical events (tyre wear, undercuts, fuel)
- You can ask questions mid-race: *"Should I pit now?"*
- 4 engineer personas: James 🇬🇧, Marco 🇮🇹, Hans 🇩🇪, Nick 🇦🇺

---

## Supported Sims

| Sim | Connection | Daemon needed? |
|-----|-----------|----------------|
| Le Mans Ultimate (LMU) | Native REST API | ❌ No |
| Assetto Corsa Competizione (ACC) | Native UDP | ❌ No |
| iRacing | WebSocket forwarder | ✅ Yes (one exe) |

---

## Architecture

```
[Sim PC]  →  [Your phone]  →  [Vercel API]  →  [Groq AI]
              PWA browser       /api/brain       llama-3.3-70b
```

- **Phone**: Opens the PWA, connects to sim by IP, speaks via Web Speech API
- **Vercel**: Serverless function calls Groq, returns engineer message
- **Groq**: Free tier, fast inference, llama-3.3-70b model

---

## Setup Guide

### Step 1 — Clone and deploy to Vercel

```bash
git clone https://github.com/YOUR_USERNAME/race-engineer-ai
cd race-engineer-ai
```

Install Vercel CLI:
```bash
npm install -g vercel
```

Deploy:
```bash
vercel --prod
```

Your app is now live at `https://your-project.vercel.app`

---

### Step 2 — Get a free Groq API key

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up (free)
3. Create an API key
4. Copy it

---

### Step 3 — Add the API key to Vercel

```bash
vercel env add GROQ_API_KEY production
```

Paste your key when prompted. Then redeploy:

```bash
vercel --prod
```

---

### Step 4 — Configure your sim

#### LMU (Le Mans Ultimate)
Nothing to install. LMU exposes a REST API on port `5397` by default.

Make sure LMU is running when you connect.

Your PC must be on the same WiFi network as your phone, OR you use a tunnel (see below).

#### ACC (Assetto Corsa Competizione)
Nothing to install. ACC broadcasts on port `9996`.

In ACC: `Options → General → Broadcasting → Enable UDP`  
Set UDP port to `9996`.

#### iRacing
iRacing uses shared memory (local only). You need the small forwarder:

1. Make sure Python is installed: [python.org](https://python.org)
2. Open a terminal in the `daemon/` folder
3. Install dependencies:
```bash
pip install -r requirements.txt
```
4. Run the forwarder:
```bash
python iracing_forwarder.py
```
Keep this window open during your session.

> **Tip**: Create a shortcut on your desktop to `iracing_forwarder.py` and double-click before each session.

---

### Step 5 — Find your PC's IP address

**Windows:**
```
Win + R → cmd → ipconfig
```
Look for `IPv4 Address` under your WiFi adapter. Example: `192.168.1.42`

**macOS:**
```
System Settings → Network → WiFi → Details
```

---

### Step 6 — Use the app on your phone

1. Open `https://your-project.vercel.app` in Safari (iPhone) or Chrome (Android)
2. **Add to Home Screen** for PWA mode (optional but recommended)
3. Enter your PC's IP address
4. Select your sim
5. Choose your engineer persona
6. Tap **NEW RACE →**
7. Put your phone near your ear or connect to Bluetooth

---

## Remote access (away from home WiFi)

If your phone is not on the same WiFi as your sim PC, use Cloudflare Tunnel (free):

```bash
# Install cloudflared
# Windows: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# LMU: tunnel port 5397
cloudflared tunnel --url http://localhost:5397

# iRacing forwarder: tunnel port 8765
cloudflared tunnel --url ws://localhost:8765
```

Cloudflare gives you a public URL like `https://abc-def.trycloudflare.com`.  
Enter this URL (without https://) as the IP in the app.

---

## Project structure

```
race-engineer-ai/
├── api/
│   └── brain.js          ← Vercel serverless — AI logic
├── public/
│   ├── index.html         ← PWA UI
│   ├── app.js             ← Sim connection + TTS logic
│   └── manifest.json      ← PWA manifest
├── daemon/
│   ├── iracing_forwarder.py   ← iRacing WebSocket bridge
│   └── requirements.txt
├── vercel.json
└── README.md
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ Yes | From console.groq.com (free) |

---

## Customizing the AI

Edit `api/brain.js` to change the engineer's behavior.

The system prompt controls everything:
- How often it speaks (`SILENT` vs actual message)
- What it prioritises (fuel vs tyres vs gaps)
- Tone and personality

Current model: `llama-3.3-70b-versatile` (Groq free tier)  
Max tokens per response: `80` (keeps messages short and fast)

---

## Roadmap

- [ ] Post-race debriefing PDF
- [ ] Team mode (multi-driver coordination)
- [ ] Setup advisor (describe handling → get setup changes)
- [ ] Session history dashboard
- [ ] Stripe subscription for hosted version

---

## Contributing

PRs welcome. Open an issue first for major changes.

---

## License

MIT

---

**Built for sim racers who want a real engineer in their ear.**
