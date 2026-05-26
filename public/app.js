// ── SUPABASE ──
const SUPA_URL = 'https://ofptqazlbbalebgqtwbr.supabase.co';
const SUPA_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mcHRxYXpsYmJhbGViZ3F0d2JyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODUwMzUsImV4cCI6MjA5NTM2MTAzNX0.aiiFgRcpmUBkJkfQSCPTWjT73hVjUaSARVohR80vNhM';
const supabase = window.supabase.createClient(SUPA_URL, SUPA_KEY);

const FREE_LIMIT = 3;

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

// ── SCREENS ──
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

// ══════════════════════════════════════
//  AUTH — EMAIL / PASSWORD
// ══════════════════════════════════════
let currentTab = 'login';

function switchTab(tab) {
  currentTab = tab;
  document.getElementById('tabLogin').classList.toggle('active', tab === 'login');
  document.getElementById('tabSignup').classList.toggle('active', tab === 'signup');
  const btn = document.getElementById('authBtn');
  btn.textContent = tab === 'login' ? 'SIGN IN →' : 'CREATE ACCOUNT →';
  clearAuthMsg();
}

function showAuthMsg(msg, type) {
  const el = document.getElementById('authMsg');
  el.textContent = msg;
  el.className = 'auth-msg ' + type;
}

function clearAuthMsg() {
  const el = document.getElementById('authMsg');
  el.className = 'auth-msg';
}

function setLoading(loading) {
  const btn = document.getElementById('authBtn');
  btn.disabled = loading;
  btn.classList.toggle('loading', loading);
  if (!loading) btn.textContent = currentTab === 'login' ? 'SIGN IN →' : 'CREATE ACCOUNT →';
}

async function handleAuth() {
  const email = document.getElementById('authEmail').value.trim();
  const password = document.getElementById('authPassword').value;
  if (!email || !password) { showAuthMsg('Please fill in all fields.', 'error'); return; }

  setLoading(true);
  clearAuthMsg();

  if (currentTab === 'login') {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) { showAuthMsg(error.message, 'error'); setLoading(false); return; }
    await afterLogin(data.user);
  } else {
    const { data, error } = await supabase.auth.signUp({ email, password });
    if (error) { showAuthMsg(error.message, 'error'); setLoading(false); return; }
    if (data.user && !data.session) {
      showAuthMsg('Check your email to confirm your account.', 'success');
      setLoading(false);
    } else {
      await afterLogin(data.user);
    }
  }
  setLoading(false);
}

// ══════════════════════════════════════
//  AUTH — GOOGLE
// ══════════════════════════════════════
async function signInWithGoogle() {
  clearAuthMsg();
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: window.location.origin + '/service.html' },
  });
  if (error) showAuthMsg(error.message, 'error');
}

// ══════════════════════════════════════
//  AUTH — SOLANA (Phantom)
// ══════════════════════════════════════
async function signInWithSolana() {
  clearAuthMsg();
  const provider = window.phantom?.solana || window.solana;

  if (!provider?.isPhantom) {
    showToast('Phantom wallet not found. Install phantom.app');
    showAuthMsg('Install Phantom wallet to use Solana login.', 'info');
    return;
  }

  try {
    showToast('Connecting Phantom...');
    const resp = await provider.connect();
    const pubkey = resp.publicKey.toString();

    // Get nonce from Supabase edge function (or use timestamp as simple nonce)
    const nonce = `pitwall-${Date.now()}`;
    const message = `Sign in to PitWall AI\n\nWallet: ${pubkey}\nNonce: ${nonce}`;
    const encodedMsg = new TextEncoder().encode(message);

    const { signature } = await provider.signMessage(encodedMsg, 'utf8');
    const sigHex = Buffer.from(signature).toString('hex');

    // Sign in via Supabase with wallet address as email proxy
    const walletEmail = `sol_${pubkey.slice(0, 8)}@wallet.pitwall.ai`;
    const walletPass = sigHex.slice(0, 32);

    // Try sign in first, then sign up
    let { data, error } = await supabase.auth.signInWithPassword({ email: walletEmail, password: walletPass });
    if (error?.message?.includes('Invalid login')) {
      const signup = await supabase.auth.signUp({
        email: walletEmail,
        password: walletPass,
        options: { data: { wallet_type: 'solana', wallet_address: pubkey } },
      });
      if (signup.error) { showAuthMsg(signup.error.message, 'error'); return; }
      data = signup.data;
    } else if (error) {
      showAuthMsg(error.message, 'error');
      return;
    }

    showToast('Solana wallet connected ✓');
    await afterLogin(data.user);
  } catch (e) {
    if (e.code === 4001) {
      showAuthMsg('Wallet connection cancelled.', 'info');
    } else {
      showAuthMsg('Solana error: ' + (e.message || 'Unknown error'), 'error');
    }
  }
}

// ══════════════════════════════════════
//  AUTH — ETHEREUM (MetaMask)
// ══════════════════════════════════════
async function signInWithEthereum() {
  clearAuthMsg();

  if (!window.ethereum) {
    showToast('MetaMask not found. Install metamask.io');
    showAuthMsg('Install MetaMask to use Ethereum login.', 'info');
    return;
  }

  try {
    showToast('Connecting MetaMask...');
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    const address = accounts[0];

    const nonce = `pitwall-${Date.now()}`;
    const message = `Sign in to PitWall AI\n\nWallet: ${address}\nNonce: ${nonce}`;

    const signature = await window.ethereum.request({
      method: 'personal_sign',
      params: [message, address],
    });

    const walletEmail = `eth_${address.slice(2, 10)}@wallet.pitwall.ai`;
    const walletPass = signature.slice(2, 34);

    let { data, error } = await supabase.auth.signInWithPassword({ email: walletEmail, password: walletPass });
    if (error?.message?.includes('Invalid login')) {
      const signup = await supabase.auth.signUp({
        email: walletEmail,
        password: walletPass,
        options: { data: { wallet_type: 'ethereum', wallet_address: address } },
      });
      if (signup.error) { showAuthMsg(signup.error.message, 'error'); return; }
      data = signup.data;
    } else if (error) {
      showAuthMsg(error.message, 'error');
      return;
    }

    showToast('Ethereum wallet connected ✓');
    await afterLogin(data.user);
  } catch (e) {
    if (e.code === 4001) {
      showAuthMsg('Wallet connection cancelled.', 'info');
    } else {
      showAuthMsg('Ethereum error: ' + (e.message || 'Unknown error'), 'error');
    }
  }
}

// ══════════════════════════════════════
//  PLAN & SESSION MANAGEMENT
// ══════════════════════════════════════
async function afterLogin(user) {
  if (!user) return;
  state.user = user;
  await loadUserPlan(user);
  checkAccess();
}

async function loadUserPlan(user) {
  const { data } = await supabase
    .from('profiles')
    .select('plan, sessions_this_month, sessions_reset_at')
    .eq('id', user.id)
    .single();

  if (!data) {
    await supabase.from('profiles').insert({
      id: user.id,
      plan: 'free',
      sessions_this_month: 0,
      sessions_reset_at: new Date().toISOString(),
    });
    state.plan = 'free';
    state.sessionsThisMonth = 0;
  } else {
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
  if (state.plan === 'free' && state.sessionsThisMonth >= FREE_LIMIT) {
    showScreen('gate');
  } else {
    showSetup();
  }
}

function showSetup() {
  showScreen('setup');
  const u = state.user;
  // Show wallet address or email
  const meta = u?.user_metadata;
  const label = meta?.wallet_address
    ? `${meta.wallet_type?.toUpperCase()} ${meta.wallet_address.slice(0, 6)}...${meta.wallet_address.slice(-4)}`
    : (u?.email || '');
  document.getElementById('userEmail').textContent = label;

  const pill = document.getElementById('planPill');
  pill.textContent = state.plan.toUpperCase();
  pill.className = 'plan-pill ' + state.plan;

  if (state.plan === 'free') {
    const left = Math.max(0, FREE_LIMIT - state.sessionsThisMonth);
    document.getElementById('sessionsLeft').textContent =
      left > 0 ? `${left} free session${left !== 1 ? 's' : ''} remaining this month` : '';
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
  if (state.plan !== 'free' || !state.user) return;
  state.sessionsThisMonth++;
  await supabase.from('profiles')
    .update({ sessions_this_month: state.sessionsThisMonth })
    .eq('id', state.user.id);
}

// ══════════════════════════════════════
//  TOAST
// ══════════════════════════════════════
function showToast(msg) {
  const el = document.getElementById('walletToast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3000);
}

// ══════════════════════════════════════
//  SETUP UI
// ══════════════════════════════════════
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
  const label = type === 'engineer' ? PERSONAS[state.persona].name : type === 'pilot' ? 'YOU' : 'SYSTEM';
  const msg = document.createElement('div');
  msg.className = 'msg';
  msg.innerHTML = `<div class="msg-icon ${iconClass}">${icon}</div><div class="msg-content"><div class="msg-sender">${label}</div><div class="msg-text">${text}</div><div class="msg-time">${now}</div></div>`;
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
    gap.textContent = data.gapAhead === 0 ? 'LEAD' : `${data.gapAhead > 0 ? '+' : ''}${data.gapAhead.toFixed(1)}`;
  }
}

// ══════════════════════════════════════
//  TTS
// ══════════════════════════════════════
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

// ══════════════════════════════════════
//  SIM CONNECTION
// ══════════════════════════════════════
async function fetchLMU(ip) {
  const base = `http://${ip}:5397/rest`;
  const [session, standings] = await Promise.all([
    fetch(`${base}/watch/sessionInfo`).then(r => r.json()),
    fetch(`${base}/watch/standings`).then(r => r.json()).catch(() => null),
  ]);
  const s = session || {};
  const p = standings?.entries?.find(e => e.isPlayer) || {};
  const fuelCap = p.fuelCapacity || 100;
  const fuelLevel = p.fuelLeft || fuelCap;
  const tyreWear = p.frontLeftWear || 100;
  return {
    position: p.position || 1,
    totalEntries: standings?.entries?.length || 1,
    fuelPercent: (fuelLevel / fuelCap) * 100,
    fuelLevel: fuelLevel.toFixed(1),
    tyreCondition: tyreWear > 70 ? 'OK' : tyreWear > 40 ? 'WARN' : 'CRIT',
    tyreWear: tyreWear.toFixed(0),
    gapAhead: parseFloat((p.timeBehindNext || 0).toFixed(1)),
    lap: p.lapsCompleted || 0,
    totalLaps: s.maximumLaps || 0,
    weather: s.darkCloud > 0.5 ? 'Rain likely' : 'Dry',
  };
}

async function fetchSimData() {
  try {
    if (state.sim === 'lmu') return await fetchLMU(state.ip);
    return null;
  } catch (e) {
    return null;
  }
}

// ══════════════════════════════════════
//  AI BRAIN
// ══════════════════════════════════════
async function callEngineer(prompt, isQuestion = false) {
  const persona = PERSONAS[state.persona];
  const system = `You are a professional sim racing engineer named ${persona.name}. ${persona.style}
Rules: max 2 sentences, speak directly to driver. If nothing useful: reply exactly "SILENT".`;
  try {
    const res = await fetch('/api/brain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ system, prompt, isQuestion }),
    });
    const data = await res.json();
    return data.message || 'SILENT';
  } catch { return 'SILENT'; }
}

async function thinkAndAct() {
  if (state.speaking || Date.now() - state.lastSpokenAt < 25000) return;
  const d = state.raceData;
  if (!d?.position) return;
  const lapsLeft = d.totalLaps > 0 ? d.totalLaps - d.lap : '?';
  const prompt = `Race: P${d.position}/${d.totalEntries}, fuel ${d.fuelPercent?.toFixed(0)}% (${d.fuelLevel}L), tyres ${d.tyreCondition} (${d.tyreWear}% wear), gap ${d.gapAhead}s, lap ${d.lap}/${d.totalLaps} (${lapsLeft} left), ${d.weather}. Say something useful or SILENT.`;
  const msg = await callEngineer(prompt);
  if (msg && msg !== 'SILENT') { addMessage(msg); speak(msg); state.lastSpokenAt = Date.now(); }
}

async function askQuestion() {
  const input = document.getElementById('questionInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';
  addMessage(q, 'pilot');
  const d = state.raceData;
  const prompt = `Race: P${d.position}/${d.totalEntries}, fuel ${d.fuelPercent?.toFixed(0)}%, tyres ${d.tyreCondition}, gap ${d.gapAhead}s, lap ${d.lap}/${d.totalLaps}, ${d.weather}. Driver asks: "${q}". Answer directly.`;
  const ans = await callEngineer(prompt, true);
  if (ans && ans !== 'SILENT') { addMessage(ans); speak(ans); state.lastSpokenAt = Date.now(); }
}

// ══════════════════════════════════════
//  RACE LIFECYCLE
// ══════════════════════════════════════
async function startRace() {
  const ip = document.getElementById('ipInput').value.trim();
  if (!ip) { showError('Enter the IP address of your sim PC.'); return; }
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
    const g = `${persona.name} online. P${testData.position}, fuel ${testData.fuelPercent?.toFixed(0)}%. Let's go.`;
    addMessage(g); speak(g); state.lastSpokenAt = Date.now();
  }, 800);

  document.getElementById('questionInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') askQuestion();
  });
}

function endRace() {
  clearInterval(state.pollInterval);
  clearInterval(state.thinkInterval);
  window.speechSynthesis?.cancel();
  state.raceData = {}; state.speaking = false; state.lastSpokenAt = 0;
  document.getElementById('messagesArea').innerHTML = `<div class="msg"><div class="msg-icon system">📡</div><div class="msg-content"><div class="msg-sender">System</div><div class="msg-text">Engineer connected. Race session active.</div><div class="msg-time" id="startTime">—</div></div></div>`;
  showSetup();
}

// ══════════════════════════════════════
//  INIT
// ══════════════════════════════════════
(async () => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user) await afterLogin(session.user);
})();

document.getElementById('authPassword').addEventListener('keydown', e => {
  if (e.key === 'Enter') handleAuth();
});

window.speechSynthesis?.getVoices();
window.speechSynthesis?.addEventListener('voiceschanged', () => window.speechSynthesis.getVoices());
