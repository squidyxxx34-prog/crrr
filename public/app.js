// ── SUPABASE ──
const SUPA_URL = 'https://ofptqazlbbalebgqtwbr.supabase.co';
const SUPA_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mcHRxYXpsYmJhbGViZ3F0d2JyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODUwMzUsImV4cCI6MjA5NTM2MTAzNX0.aiiFgRcpmUBkJkfQSCPTWjT73hVjUaSARVohR80vNhM';
const supabase = window.supabase.createClient(SUPA_URL, SUPA_KEY);

const FREE_SESSION_LIMIT = 3;

// ── STATE ──
let state = {
  sim: 'lmu', persona: 'british', ip: '',
  pollInterval: null, thinkInterval: null,
  speaking: false, raceData: {}, lastSpokenAt: 0,
  user: null, plan: 'free', sessionsThisMonth: 0,
};

const PERSONAS = {
  british: { name: 'JAMES', voice: 'en-GB', style: 'Calm, precise, British F1 engineer. Short sentences. Never panics.' },
  italian: { name: 'MARCO', voice: 'it-IT', style: 'Passionate Italian engineer. Tactical. Energetic but professional.' },
  german:  { name: 'HANS',  voice: 'de-DE', style: 'German engineer. Ultra technical. Data-focused. Efficient.' },
  aussie:  { name: 'NICK',  voice: 'en-AU', style: 'Australian engineer. Direct, no nonsense, straight to the point.' },
};

const SIM_PORTS = { lmu: 5397, acc: 9996, iracing: 8765 };

// ── SCREEN ROUTING ──
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

// ── AUTH ──
let currentTab = 'login';

function switchTab(tab) {
  currentTab = tab;
  document.getElementById('tabLogin').classList.toggle('active', tab === 'login');
  document.getElementById('tabSignup').classList.toggle('active', tab === 'signup');
  document.getElementById('authBtn').textContent = tab === 'login' ? 'SIGN IN →' : 'CREATE ACCOUNT →';
  document.getElementById('authMsg').className = 'auth-msg';
}

function showAuthMsg(msg, type) {
  const el = document.getElementById('authMsg');
  el.textContent = msg;
  el.className = 'auth-msg ' + type;
}

async function handleAuth() {
  const email = document.getElementById('authEmail').value.trim();
  const password = document.getElementById('authPassword').value;
  const btn = document.getElementById('authBtn');

  if (!email || !password) { showAuthMsg('Please fill in all fields.', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '...';

  if (currentTab === 'login') {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) { showAuthMsg(error.message, 'error'); btn.disabled = false; btn.textContent = 'SIGN IN →'; return; }
    await afterLogin(data.user);
  } else {
    const { data, error } = await supabase.auth.signUp({ email, password });
    if (error) { showAuthMsg(error.message, 'error'); btn.disabled = false; btn.textContent = 'CREATE ACCOUNT →'; return; }
    if (data.user && !data.session) {
      showAuthMsg('Check your email to confirm your account.', 'success');
      btn.disabled = false; btn.textContent = 'CREATE ACCOUNT →';
    } else {
      await afterLogin(data.user);
    }
  }
}

async function afterLogin(user) {
  state.user = user;
  await loadUserPlan(user);
  checkAccess();
}

async function loadUserPlan(user) {
  // Check profiles table for plan + session count
  const { data } = await supabase
    .from('profiles')
    .select('plan, sessions_this_month, sessions_reset_at')
    .eq('id', user.id)
    .single();

  if (!data) {
    // New user — create profile
    await supabase.from('profiles').insert({
      id: user.id,
      plan: 'free',
      sessions_this_month: 0,
      sessions_reset_at: new Date().toISOString(),
    });
    state.plan = 'free';
    state.sessionsThisMonth = 0;
  } else {
    // Check if month rolled over
    const resetAt = new Date(data.sessions_reset_at);
    const now = new Date();
    if (now.getMonth() !== resetAt.getMonth() || now.getFullYear() !== resetAt.getFullYear()) {
      await supabase.from('profiles').update({
        sessions_this_month: 0,
        sessions_reset_at: now.toISOString(),
      }).eq('id', user.id);
      state.sessionsThisMonth = 0;
    } else {
      state.sessionsThisMonth = data.sessions_this_month || 0;
    }
    state.plan = data.plan || 'free';
  }
}

function checkAccess() {
  if (state.plan === 'free' && state.sessionsThisMonth >= FREE_SESSION_LIMIT) {
    showScreen('gate');
    return;
  }
  showSetup();
}

function showSetup() {
  showScreen('setup');
  // Update UI
  const u = state.user;
  document.getElementById('userEmail').textContent = u?.email || '';
  const pill = document.getElementById('planPill');
  pill.textContent = state.plan.toUpperCase();
  pill.className = 'plan-pill ' + state.plan;

  if (state.plan === 'free') {
    const left = FREE_SESSION_LIMIT - state.sessionsThisMonth;
    document.getElementById('sessionsLeft').textContent =
      left > 0 ? `${left} free session${left > 1 ? 's' : ''} remaining this month` : '';
  } else {
    document.getElementById('sessionsLeft').textContent = '';
  }
}

async function signOut() {
  await supabase.auth.signOut();
  state.user = null; state.plan = 'free'; state.sessionsThisMonth = 0;
  showScreen('auth');
}

async function incrementSession() {
  if (state.plan !== 'free') return;
  state.sessionsThisMonth++;
  await supabase.from('profiles')
    .update({ sessions_this_month: state.sessionsThisMonth })
    .eq('id', state.user.id);
}

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
  msg.innerHTML = `<div class="msg-icon ${iconClass}">${icon}</div><div class="msg-content"><div class="msg-sender">${senderLabel}</div><div class="msg-text">${text}</div><div class="msg-time">${now}</div></div>`;
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
  const voices = window.speechSynthesis.getVoices();
  const persona = PERSONAS[state.persona];
  const match = voices.find(v => v.lang.startsWith(persona.voice.split('-')[0]));
  if (match) utter.voice = match;
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
  return { position, totalEntries, fuelPercent, fuelLevel: fuelLevel.toFixed(1), tyreCondition, tyreWear: tyreWear.toFixed(0), gapAhead: parseFloat(gapAhead.toFixed(1)), lap, totalLaps, weather };
}

async function fetchSimData() {
  try {
    if (state.sim === 'lmu') return await fetchLMU(state.ip);
    // ACC + iRacing via WebSocket (daemon)
    return null;
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
- Speak directly to the driver, max 2 sentences
- Only speak when USEFUL. If nothing important: respond exactly "SILENT"
- Focus on: tyre management, fuel strategy, gap management, pit timing, weather`;
  try {
    const res = await fetch('/api/brain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ system: systemPrompt, prompt, isQuestion }),
    });
    const data = await res.json();
    return data.message || 'SILENT';
  } catch (e) {
    return 'SILENT';
  }
}

async function thinkAndAct() {
  if (state.speaking) return;
  if (Date.now() - state.lastSpokenAt < 25000) return;
  const data = state.raceData;
  if (!data?.position) return;
  const lapsLeft = data.totalLaps > 0 ? data.totalLaps - data.lap : '?';
  const prompt = `Race: P${data.position}/${data.totalEntries}, fuel ${data.fuelPercent?.toFixed(0)}% (${data.fuelLevel}L), tyres ${data.tyreCondition} (${data.tyreWear}% wear), gap ${data.gapAhead}s, lap ${data.lap}/${data.totalLaps} (${lapsLeft} left), weather ${data.weather}. Say something useful or SILENT.`;
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
  const prompt = `Race: P${data.position}/${data.totalEntries}, fuel ${data.fuelPercent?.toFixed(0)}%, tyres ${data.tyreCondition}, gap ${data.gapAhead}s, lap ${data.lap}/${data.totalLaps}, weather ${data.weather}. Driver asks: "${q}". Answer directly.`;
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

  document.getElementById('connecting').classList.add('active');
  document.getElementById('connectBtn').disabled = true;

  const testData = await fetchSimData();
  document.getElementById('connecting').classList.remove('active');

  if (!testData) {
    document.getElementById('connectBtn').disabled = false;
    showError('Cannot connect. Check IP and make sure your sim is running.');
    return;
  }

  // Log session in Supabase
  await incrementSession();

  showScreen('race');
  const persona = PERSONAS[state.persona];
  document.getElementById('engineerBadge').textContent = persona.name;
  document.getElementById('startTime').textContent = new Date().toLocaleTimeString();
  state.raceData = testData;
  updateTelemetry(testData);

  state.pollInterval = setInterval(async () => {
    const data = await fetchSimData();
    if (data) { state.raceData = data; updateTelemetry(data); }
  }, 5000);

  state.thinkInterval = setInterval(thinkAndAct, 30000);

  setTimeout(() => {
    const greeting = `${persona.name} here. P${testData.position}, fuel ${testData.fuelPercent?.toFixed(0)}%. Let's go.`;
    addMessage(greeting);
    speak(greeting);
    state.lastSpokenAt = Date.now();
  }, 1000);

  document.getElementById('questionInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') askQuestion();
  });
}

function endRace() {
  clearInterval(state.pollInterval);
  clearInterval(state.thinkInterval);
  window.speechSynthesis?.cancel();
  state.raceData = {}; state.speaking = false; state.lastSpokenAt = 0;
  document.getElementById('messagesArea').innerHTML = `<div class="msg"><div class="msg-icon system">📡</div><div class="msg-content"><div class="msg-sender">System</div><div class="msg-text">Engineer connected. Race session active. Monitoring telemetry.</div><div class="msg-time" id="startTime">—</div></div></div>`;
  showSetup();
}

// ── INIT ──
(async () => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user) {
    await afterLogin(session.user);
  }
  // else: auth screen already visible
})();

// Enter key on auth
document.getElementById('authPassword').addEventListener('keydown', e => {
  if (e.key === 'Enter') handleAuth();
});

window.speechSynthesis?.getVoices();
window.speechSynthesis?.addEventListener('voiceschanged', () => window.speechSynthesis.getVoices());
