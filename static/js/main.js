/* ── KIDA Remote Control — app.js ───────────────────────────────────────────── */

// ── State ──────────────────────────────────────────────────────────────────────
let currentMode   = 'USER';
let currentScheme = 1;
let currentSpeed  = 0.6;
let musicPlaying  = false;
let videoRec      = false;
let direction     = 'STOPPED';
let frameCount    = 0;
let waveAnim      = 0;

const PORT = 5003;

// ── Waveform init ──────────────────────────────────────────────────────────────
function initWave(id, n) {
  const el = document.getElementById(id);
  el.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const b = document.createElement('div');
    b.className = 'wbar';
    el.appendChild(b);
  }
}
initWave('waveform', 24);
initWave('centre-wave', 80);

// ── Animation loop ─────────────────────────────────────────────────────────────
function animateWaves() {
  waveAnim++;
  document.querySelectorAll('#waveform .wbar').forEach((b, i) => {
    b.style.height = (musicPlaying
      ? Math.round((Math.sin(waveAnim * 0.12 + i * 0.32) * 0.5 + 0.5) * 24 + 3)
      : 2) + 'px';
  });
  document.querySelectorAll('#centre-wave .wbar').forEach((b, i) => {
    b.style.height = (musicPlaying
      ? Math.round((Math.sin(waveAnim * 0.1 + i * 0.2) * 0.5 + 0.5) * 26 + 3)
      : 2) + 'px';
  });
  document.getElementById('sb-frame').textContent = ++frameCount;
  requestAnimationFrame(animateWaves);
}
animateWaves();

// ── QR code ────────────────────────────────────────────────────────────────────
(function () {
  const url = `http://${location.hostname}:${PORT}`;
  document.getElementById('qr-url').textContent = url;
  document.getElementById('qr-img').src =
    `https://api.qrserver.com/v1/create-qr-code/?size=90x90&data=${encodeURIComponent(url)}`;
})();

// ── API helpers ────────────────────────────────────────────────────────────────
async function sendCmd(cmd) {
  try {
    await fetch('/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd }),
    });
  } catch (e) {}
}

async function apiFetch(path, body) {
  try {
    await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {}
}

// ── D-pad ──────────────────────────────────────────────────────────────────────
function dpadDown(dir) {
  document.querySelectorAll('.dp-btn').forEach(b => b.classList.remove('pressed'));
  document.querySelector(`[data-dir="${dir}"]`)?.classList.add('pressed');
  sendCmd(dir === 'stop' ? 'stop' : dir);
  updateDirection(dir.toUpperCase());
  if (dir !== 'stop') {
    clearInterval(window._heldInterval);
    window._heldInterval = setInterval(() => sendCmd(dir), 150);
  }
}

function dpadUp() {
  clearInterval(window._heldInterval);
  document.querySelectorAll('.dp-btn').forEach(b => b.classList.remove('pressed'));
}

// ── Mode ───────────────────────────────────────────────────────────────────────
function setMode(m) {
  currentMode = m;
  const modes = ['USER', 'AUTONOMOUS', 'LINE', 'FACE'];
  document.querySelectorAll('.tab').forEach((t, i) =>
    t.classList.toggle('active', modes[i] === m));
  apiFetch('/mode', { mode: m });
  updateModeUI();
}

function updateModeUI() {
  const ov  = document.getElementById('mode-overlay');
  const fso = document.getElementById('face-scan-overlay');
  const fr  = document.getElementById('face-results');

  fso.classList.toggle('show', currentMode === 'FACE');
  fr.classList.toggle('show',  currentMode === 'FACE');

  if (currentMode === 'AUTONOMOUS') {
    ov.textContent = '— AUTONOMOUS —';
    ov.style.color = 'var(--teal)';
    ov.classList.add('show');
  } else if (currentMode === 'LINE') {
    ov.textContent = '— LINE FOLLOW —';
    ov.style.color = 'var(--blue)';
    ov.classList.add('show');
  } else {
    ov.classList.remove('show');
  }

  const me = document.getElementById('ci-mode');
  me.textContent  = currentMode;
  me.style.color  = currentMode === 'FACE' ? 'var(--purple)' : '';
  document.getElementById('sb-mode').textContent = currentMode;
}

// ── Speed ──────────────────────────────────────────────────────────────────────
function setSpeed(s) {
  currentSpeed = s;
  document.querySelectorAll('#speed-btns .btn').forEach(b =>
    b.classList.toggle('active', parseFloat(b.dataset.spd) === s));
  document.getElementById('ci-spd').textContent   = s.toFixed(1);
  document.getElementById('sb-speed').textContent = s.toFixed(1);
  apiFetch('/speed', { speed: s });
}

// ── Control scheme ─────────────────────────────────────────────────────────────
function setScheme(s) {
  currentScheme = s;
  document.getElementById('sch-wasd').classList.toggle('active', s === 1);
  document.getElementById('sch-tank').classList.toggle('active', s === 2);
}

// ── Music ──────────────────────────────────────────────────────────────────────
function toggleMusic() {
  musicPlaying = !musicPlaying;
  const btn = document.getElementById('btn-play');
  btn.textContent = musicPlaying ? 'PAUSE' : 'PLAY';
  btn.classList.toggle('active', musicPlaying);
  sendCmd(musicPlaying ? 'play_music' : 'stop_music');
  document.getElementById('waveform').classList.toggle('playing', musicPlaying);
  document.getElementById('centre-wave').classList.toggle('playing', musicPlaying);
  document.getElementById('track-name').classList.toggle('playing', musicPlaying);
}

// ── Video ──────────────────────────────────────────────────────────────────────
function toggleVideo() {
  videoRec = !videoRec;
  document.getElementById('btn-video').textContent = videoRec ? '⏹ STOP' : '⏺ REC';
  document.getElementById('btn-video').classList.toggle('active', videoRec);
  document.getElementById('rec-badge').classList.toggle('show', videoRec);
  sendCmd(videoRec ? 'video_start' : 'video_stop');
}

// ── Direction ──────────────────────────────────────────────────────────────────
function updateDirection(dir) {
  direction = dir;
  const el = document.getElementById('ci-dir');
  el.textContent = dir;
  el.classList.toggle('moving', dir !== 'STOPPED');
  document.querySelectorAll('.dp-btn').forEach(b =>
    b.classList.toggle('active-dir', b.dataset.dir?.toUpperCase() === dir && dir !== 'STOPPED'));
}

// ── LEDs ───────────────────────────────────────────────────────────────────────
function updateLeds(color) {
  const [r, g, b] = color;
  const on  = r > 10 || g > 10 || b > 10;
  const hex = on ? `rgb(${r},${g},${b})` : '';
  document.querySelectorAll('.led-dot').forEach(d => {
    d.style.background  = on ? hex : 'var(--dim)';
    d.style.boxShadow   = on ? `0 0 8px ${hex}` : '';
  });
}

// ── Face cards ─────────────────────────────────────────────────────────────────
function renderFaceCards(results) {
  const c = document.getElementById('face-results');
  c.innerHTML = '';
  if (!results || !results.length) {
    const e = document.createElement('div');
    e.style.cssText = 'color:var(--dim);font-size:11px;padding:4px 0;';
    e.textContent = 'No faces detected';
    c.appendChild(e);
    return;
  }
  results.forEach((f, i) => {
    const w    = f.gender === 'Woman';
    const card = document.createElement('div');
    card.className = `face-card ${w ? 'woman' : 'man'}`;
    card.innerHTML = `
      <span class="fc-icon">${w ? '👩' : '👨'}</span>
      <div class="fc-info">
        <span class="fc-gender">#${i + 1} ${f.gender || '?'}</span>
        <span class="fc-age">Age ~${f.age || '?'} yrs</span>
      </div>
      <span class="fc-conf">${f.conf ? f.conf.toFixed(0) + '%' : ''}</span>`;
    c.appendChild(card);
  });
}

// ── Keyboard ───────────────────────────────────────────────────────────────────
const keyMap = {
  w: 'forward', s: 'backward', a: 'left', d: 'right', ' ': 'stop',
  ArrowUp: 'forward', ArrowDown: 'backward', ArrowLeft: 'left', ArrowRight: 'right',
};
const held = new Set();

document.addEventListener('keydown', e => {
  if (held.has(e.key)) return;
  held.add(e.key);
  const dir = keyMap[e.key];
  if (dir) { sendCmd(dir); updateDirection(dir.toUpperCase()); }
  if (e.key === 'm') toggleMusic();
  if (e.key === 'c') sendCmd('photo');
  if (e.key === 'v') toggleVideo();
  if (e.key === 'f') setMode(currentMode === 'FACE' ? 'USER' : 'FACE');
  if (e.key === 'u') setMode('USER');
  if (e.key === 'o') setMode('AUTONOMOUS');
  if (e.key === 'l') setMode('LINE');
  if (e.key === 'x') {
    const ss = [0.4, 0.6, 0.8, 1.0];
    setSpeed(ss[(ss.indexOf(currentSpeed) + 1) % ss.length]);
  }
  if (e.key === '1') setScheme(1);
  if (e.key === '2') setScheme(2);
});
document.addEventListener('keyup', e => held.delete(e.key));

// ── Polling ────────────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const d = await (await fetch('/status')).json();
    updateDirection(d.direction || 'STOPPED');
    if (d.led) updateLeds(d.led);

    const fc = d.face_count || 0;
    const fe = document.getElementById('ci-faces');
    fe.textContent = fc;
    fe.classList.toggle('purple', fc > 0);
    document.getElementById('sb-faces').textContent = fc;

    if (d.music_playing !== musicPlaying) {
      musicPlaying = d.music_playing;
      document.getElementById('btn-play').textContent = musicPlaying ? 'PAUSE' : 'PLAY';
      document.getElementById('btn-play').classList.toggle('active', musicPlaying);
      document.getElementById('waveform').classList.toggle('playing', musicPlaying);
      document.getElementById('centre-wave').classList.toggle('playing', musicPlaying);
    }
    if (d.video_rec !== videoRec) {
      videoRec = d.video_rec;
      document.getElementById('btn-video').textContent = videoRec ? '⏹ STOP' : '⏺ REC';
      document.getElementById('btn-video').classList.toggle('active', videoRec);
      document.getElementById('rec-badge').classList.toggle('show', videoRec);
    }
  } catch (e) {}
}

async function pollStats() {
  try {
    const s = (await (await fetch('/control/stats/')).json()).stats || {};
    const cpu  = (s.cpu  || 0).toFixed(0);
    const temp = (s.temp || 0).toFixed(0);
    const ru   = s.ram_used  || 0;
    const rt   = s.ram_total || 1;

    document.getElementById('val-cpu').textContent   = cpu  + '%';
    document.getElementById('val-temp').textContent  = temp + '°C';
    document.getElementById('val-thr').textContent   = s.threads || '–';
    document.getElementById('stat-cpu').textContent  = cpu  + '%';
    document.getElementById('stat-temp').textContent = temp + '°C';
    document.getElementById('stat-ram').textContent  = `${ru}/${rt}M`;
    document.getElementById('bar-cpu').style.width   = cpu + '%';
    document.getElementById('bar-temp').style.width  = (parseFloat(temp) / 85 * 100).toFixed(0) + '%';
    document.getElementById('bar-ram').style.width   = (ru / rt * 100).toFixed(0) + '%';
    document.getElementById('net-lat').textContent   = s.latency   || '–';
    document.getElementById('net-thr').textContent   = s.threads   || '–';
    document.getElementById('net-dr').textContent    = (s.disk_read  || 0) + ' MB';
    document.getElementById('net-dw').textContent    = (s.disk_write || 0) + ' MB';
    document.getElementById('net-boot').textContent  = s.boot_time  || '–';

    document.getElementById('chip-temp').classList.toggle('warn', parseFloat(temp) > 65);
  } catch (e) {}
}

async function pollFaces() {
  if (currentMode !== 'FACE') return;
  try {
    const d = await (await fetch('/face/results')).json();
    if (d.results) renderFaceCards(d.results);
  } catch (e) {}
}

setInterval(pollStatus, 800);
setInterval(pollStats,  2000);
setInterval(pollFaces,  1500);
pollStatus();
pollStats();