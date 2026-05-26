// ── STATE ──
let state = {
  sim: 'lmu',
  persona: 'british',
  ip: '',
  ws: null,
  pollInterval: null,
  thinkInterval: null,
  speaking: false,
  raceData: {},
  lastSpokenAt: 0,
  lap: 0,
  sessionStart: null,
};

const PERSONAS = {
  british: { name: 'JAMES', voice: 'en-GB', style: 'Calm, precise, British F1 engineer. Short sentences. Never panics.' },
  italian: { name: 'MARCO', voice: 'it-IT', style: 'Passionate Italian engineer. Tactical. Energetic but professional.' },
  german:  { name: 'HANS',  voice: 'de-DE', style: 'German engineer. Ultra technical. Data-focused. Efficient.' },
  aussie:  { name: 'NICK',  voice: 'en-AU', style: 'Australian engineer. Direct, no nonsense, straight to the point.' },
};

const SIM_PORTS = { lmu: 5397, acc: 9996, iracing: 8765 };

// ── UI HELPERS ──
function selectSim(el) {
  document.querySelectorAll('.sim-btn').forEach(b => b.classList.remove('selected'));
  el.classList.add('selected');
  state.sim = el.dataset.sim;
}

function selectPersona(el) {
  document.querySelectorAll('.persona-btn').forEach(b => b.classList.remove('selected'));
  el.classList.add('selected');
  state.persona = el.dataset.persona;
}

function showError(msg) {
  const el = document.getElementById('errorMsg');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 5000);
}

function addMessage(text, type = 'engineer') {
  const area = document.getElementById('messagesArea');
  const now = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const icon = type === 'engineer' ? '🎧' : type === 'pilot' ? '🏎' : '📡';
  const iconClass = type === 'engineer' ? 'engineer' : 'system';
  const senderLabel = type === 'engineer' ? PERSONAS[state.persona].name : type === 'pilot' ? 'YOU' : 'SYSTEM';

  const msg = document.createElement('div');
  msg.className = 'msg';
  msg.innerHTML = `
    <div class="msg-icon ${iconClass}">${icon}</div>
    <div class="msg-content">
      <div class="msg-sender">${senderLabel}</div>
      <div class="msg-text">${text}</div>
      <div class="msg-time">${now}</div>
    </div>`;
  area.appendChild(msg);
  area.scrollTop = area.scrollHeight;
}

function updateTelemetry(data) {
  if (!data) return;
  const pos = document.getElementById('telPos');
  const fuel = document.getElementById('telFuel');
  const tyre = document.getElementById('telTyre');
  const gap = document.getElementById('telGap');

  if (data.position) pos.textContent = `P${data.position}`;
  if (data.fuelPercent !== undefined) {
    const fp = Math.round(data.fuelPercent);
    fuel.textContent = `${fp}%`;
    fuel.className = 'telem-val' + (fp < 15 ? ' danger' : fp < 30 ? ' warn' : '');
  }
  if (data.tyreCondition) {
    tyre.textContent = data.tyreCondition;
    tyre.className = 'telem-val' + (data.tyreCondition === 'CRIT' ? ' danger' : data.tyreCondition === 'WARN' ? ' warn' : ' good');
  }
  if (data.gapAhead !== undefined) {
    gap.textContent = data.gapAhead > 0 ? `+${data.gapAhead.toFixed(1)}` : data.gapAhead === 0 ? 'LEAD' : `${data.gapAhead.toFixed(1)}`;
  }
}

// ── TTS ──
function speak(text) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();

  const utter = new SpeechSynthesisUtterance(text);
  const persona = PERSONAS[state.persona];

  // Try to find matching voice
  const voices = window.speechSynthesis.getVoices();
  const match = voices.find(v => v.lang.startsWith(persona.voice.split('-')[0]));
  if (match) utter.voice = match;

  utter.rate = 1.0;
  utter.pitch = 1.0;
  utter.volume = 1.0;

  state.speaking = true;
  document.getElementById('waveAnim').classList.add('active');
  document.getElementById('speakingText').textContent = text;

  utter.onend = () => {
    state.speaking = false;
    document.getElementById('waveAnim').classList.remove('active');
    document.getElementById('speakingText').textContent = 'Engineer standing by...';
  };

  window.speechSynthesis.speak(utter);
}

// ── SIM CONNECTION ──
async function fetchLMU(ip) {
  // LMU exposes REST API on port 5397
  const base = `http://${ip}:5397/rest`;
  const [session, standings] = await Promise.all([
    fetch(`${base}/watch/sessionInfo`).then(r => r.json()),
    fetch(`${base}/watch/standings`).then(r => r.json()).catch(() => null),
  ]);
  return parseLMU(session, standings);
}

function parseLMU(session, standings) {
  const s = session || {};
  const playerEntry = standings?.entries?.find(e => e.isPlayer) || {};
  const fuelCap = playerEntry.fuelCapacity || 100;
  const fuelLevel = playerEntry.fuelLeft || fuelCap;
  const fuelPercent = (fuelLevel / fuelCap) * 100;
  const position = playerEntry.position || 1;
  const totalEntries = standings?.entries?.length || 1;
  const gapAhead = playerEntry.timeBehindNext || 0;
  const tyreWear = playerEntry.frontLeftWear || 100;
  const tyreCondition = tyreWear > 70 ? 'OK' : tyreWear > 40 ? 'WARN' : 'CRIT';
  const lap = playerEntry.lapsCompleted || 0;
  const totalLaps = s.maximumLaps || 0;
  const weather = s.darkCloud > 0.5 ? 'Rain likely' : 'Dry';
  const sessionType = s.session || 'Race';

  return {
    position, totalEntries, fuelPercent, fuelLevel: fuelLevel.toFixed(1),
    tyreCondition, tyreWear: tyreWear.toFixed(0),
    gapAhead: gapAhead.toFixed(1), lap, totalLaps,
    weather, sessionType,
    raw: { session: s, player: playerEntry },
  };
}

async function fetchACC(ip) {
  // ACC UDP broadcast — requires local relay; fallback to mock for remote
  // In production, the daemon forwards ACC data via WebSocket
  const ws = new WebSocket(`ws://${ip}:${SIM_PORTS.acc}`);
  return new Promise((resolve, reject) => {
    ws.onmessage = e => resolve(JSON.parse(e.data));
    ws.onerror = reject;
    setTimeout(reject, 3000);
  });
}

async function fetchIRacing(ip) {
  // iRacing requires the local forwarder daemon (exe double-click)
  const ws = new WebSocket(`ws://${ip}:${SIM_PORTS.iracing}`);
  return new Promise((resolve, reject) => {
    ws.onmessage = e => resolve(parseIRacing(JSON.parse(e.data)));
    ws.onerror = reject;
    setTimeout(reject, 3000);
  });
}

function parseIRacing(raw) {
  const fuelPercent = ((raw.FuelLevel || 0) / (raw.FuelLevelPct || 1)) * 100;
  return {
    position: raw.PlayerCarPosition || 1,
    totalEntries: raw.NumActiveCars || 1,
    fuelPercent: raw.FuelLevelPct * 100 || 100,
    fuelLevel: (raw.FuelLevel || 0).toFixed(1),
    tyreCondition: raw.LFwearM < 0.3 ? 'CRIT' : raw.LFwearM < 0.6 ? 'WARN' : 'OK',
    tyreWear: (raw.LFwearM * 100 || 100).toFixed(0),
    gapAhead: raw.LapDeltaToSessionBestLap || 0,
    lap: raw.Lap || 0,
    totalLaps: raw.SessionLapsTotal || 0,
    weather: raw.WeatherType === 1 ? 'Rain' : 'Dry',
    sessionType: 'Race',
  };
}

async function fetchSimData() {
  const ip = state.ip;
  try {
    if (state.sim === 'lmu') return await fetchLMU(ip);
    if (state.sim === 'acc') return await fetchACC(ip);
    if (state.sim === 'iracing') return await fetchIRacing(ip);
  } catch (e) {
    console.warn('Telemetry fetch failed:', e);
    return null;
  }
}

// ── AI BRAIN ──
async function callEngineer(prompt, isQuestion = false) {
  const persona = PERSONAS[state.persona];
  const systemPrompt = `You are a professional sim racing engineer named ${persona.name}. Personality: ${persona.style}
  
Rules:
- Speak in first person directly to the driver
- Maximum 2 sentences per message
- Only speak when there is something USEFUL to say
- If nothing important: respond with exactly "SILENT"
- Focus on: tyre management, fuel strategy, gap management, pit timing, weather
- Never repeat information just given`;

  try {
    const res = await fetch('/api/brain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ system: systemPrompt, prompt, isQuestion }),
    });
    const data = await res.json();
    return data.message || 'SILENT';
  } catch (e) {
    console.error('AI call failed:', e);
    return 'SILENT';
  }
}

async function thinkAndAct() {
  if (state.speaking) return;
  const now = Date.now();
  if (now - state.lastSpokenAt < 25000) return; // min 25s between auto messages

  const data = state.raceData;
  if (!data || !data.position) return;

  const lapsLeft = data.totalLaps > 0 ? data.totalLaps - data.lap : '?';
  const prompt = `Race situation:
- Position: P${data.position}/${data.totalEntries}
- Fuel: ${data.fuelPercent?.toFixed(0)}% (${data.fuelLevel}L)
- Tyre condition: ${data.tyreCondition} (wear ${data.tyreWear}%)
- Gap ahead: ${data.gapAhead}s
- Lap: ${data.lap}/${data.totalLaps} (${lapsLeft} laps left)
- Weather: ${data.weather}

Should you say something useful to the driver right now? If yes, say it. If not, respond SILENT.`;

  const message = await callEngineer(prompt);
  if (message && message !== 'SILENT') {
    addMessage(message);
    speak(message);
    state.lastSpokenAt = Date.now();
  }
}

async function askQuestion() {
  const input = document.getElementById('questionInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';

  addMessage(q, 'pilot');

  const data = state.raceData;
  const prompt = `Current race data:
- Position: P${data.position}/${data.totalEntries}
- Fuel: ${data.fuelPercent?.toFixed(0)}% (${data.fuelLevel}L)
- Tyre condition: ${data.tyreCondition} (wear ${data.tyreWear}%)
- Gap ahead: ${data.gapAhead}s
- Lap: ${data.lap}/${data.totalLaps}
- Weather: ${data.weather}

Driver asks: "${q}"
Answer directly and concisely. This is a question so DO NOT respond SILENT.`;

  const answer = await callEngineer(prompt, true);
  if (answer && answer !== 'SILENT') {
    addMessage(answer);
    speak(answer);
    state.lastSpokenAt = Date.now();
  }
}

// ── RACE LIFECYCLE ──
async function startRace() {
  const ip = document.getElementById('ipInput').value.trim();
  if (!ip) { showError('Please enter the IP address of your sim PC.'); return; }

  state.ip = ip;
  state.sessionStart = new Date();

  document.getElementById('connecting').classList.add('active');
  document.getElementById('connectBtn').disabled = true;

  // Test connection
  const testData = await fetchSimData();
  document.getElementById('connecting').classList.remove('active');

  if (!testData) {
    document.getElementById('connectBtn').disabled = false;
    showError('Cannot connect. Check IP and make sure your sim is running.');
    return;
  }

  // Switch to race screen
  document.getElementById('setup').classList.remove('active');
  document.getElementById('race').classList.add('active');

  const persona = PERSONAS[state.persona];
  document.getElementById('engineerBadge').textContent = persona.name;
  document.getElementById('startTime').textContent = state.sessionStart.toLocaleTimeString();

  state.raceData = testData;
  updateTelemetry(testData);

  // Poll telemetry every 5s
  state.pollInterval = setInterval(async () => {
    const data = await fetchSimData();
    if (data) {
      state.raceData = data;
      updateTelemetry(data);
    }
  }, 5000);

  // AI thinks every 30s
  state.thinkInterval = setInterval(thinkAndAct, 30000);

  // Initial greeting
  setTimeout(() => {
    const greeting = `${persona.name} here, I'm in. P${testData.position}, fuel at ${testData.fuelPercent?.toFixed(0)}%. Let's do this.`;
    addMessage(greeting);
    speak(greeting);
    state.lastSpokenAt = Date.now();
  }, 1000);

  // Allow asking via Enter key
  document.getElementById('questionInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') askQuestion();
  });
}

function endRace() {
  clearInterval(state.pollInterval);
  clearInterval(state.thinkInterval);
  window.speechSynthesis?.cancel();

  document.getElementById('race').classList.remove('active');
  document.getElementById('setup').classList.add('active');
  document.getElementById('connectBtn').disabled = false;

  state.raceData = {};
  state.speaking = false;
  state.lastSpokenAt = 0;

  document.getElementById('messagesArea').innerHTML = `
    <div class="msg">
      <div class="msg-icon system">📡</div>
      <div class="msg-content">
        <div class="msg-sender">System</div>
        <div class="msg-text">Engineer connected. Race session active. Monitoring telemetry.</div>
        <div class="msg-time" id="startTime">—</div>
      </div>
    </div>`;
}

// Preload voices
window.speechSynthesis?.getVoices();
window.speechSynthesis?.addEventListener('voiceschanged', () => window.speechSynthesis.getVoices());
