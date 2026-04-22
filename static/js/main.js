/* ── KIDA Remote Control — main.js ───────────────────────────────────────────── */

// ── State ──────────────────────────────────────────────────────────────────────
let currentMode   = 'USER';
let currentScheme = 1;
let currentSpeed  = 0.6;
let musicPlaying  = false;
let videoRec      = false;
let direction     = 'STOPPED';
let frameCount    = 0;
let waveAnim      = 0;
let _lastPhoto    = '';
let _lastVideo    = '';
let _dancing      = false;
let _sleeping     = false;
let _audioAmps    = [];   // latest amplitude array from /audio_amps

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
  const hasAmps = musicPlaying && _audioAmps.length > 0;
  document.querySelectorAll('#waveform .wbar').forEach((b, i) => {
    let h;
    if (!musicPlaying) {
      h = 2;
    } else if (hasAmps) {
      const idx = Math.floor(i * _audioAmps.length / 24);
      h = Math.round(_audioAmps[idx] * 26 + 3);
    } else {
      h = Math.round((Math.sin(waveAnim * 0.12 + i * 0.32) * 0.5 + 0.5) * 24 + 3);
    }
    b.style.height = h + 'px';
  });
  document.querySelectorAll('#centre-wave .wbar').forEach((b, i) => {
    let h;
    if (!musicPlaying) {
      h = 2;
    } else if (hasAmps) {
      const idx = Math.floor(i * _audioAmps.length / 80);
      h = Math.round(_audioAmps[idx] * 28 + 3);
    } else {
      h = Math.round((Math.sin(waveAnim * 0.1 + i * 0.2) * 0.5 + 0.5) * 26 + 3);
    }
    b.style.height = h + 'px';
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

// ── Auto-download ──────────────────────────────────────────────────────────────
function _autoDownload(url, filename) {
  const a = document.createElement('a');
  a.href = url;  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

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

// ── Standard D-pad (scheme 1) ──────────────────────────────────────────────────
function dpadDown(dir) {
  document.querySelectorAll('.dp-btn').forEach(b => b.classList.remove('pressed'));
  document.querySelector(`[data-dir="${dir}"]`)?.classList.add('pressed');
  sendCmd(dir === 'stop' ? 'stop' : dir);
  if (dir !== 'stop') updateDirection(dir.toUpperCase());
  if (dir !== 'stop') {
    clearInterval(window._heldInterval);
    window._heldInterval = setInterval(() => sendCmd(dir), 150);
  }
}

function dpadUp() {
  clearInterval(window._heldInterval);
  document.querySelectorAll('.dp-btn').forEach(b => b.classList.remove('pressed'));
  sendCmd('stop');
  updateDirection('STOPPED');
}

// ── Tank controls (scheme 2) ───────────────────────────────────────────────────
// Per-side interval handles so left and right motors are independent
const _tk = { L: null, R: null, B: null };

function tankDown(el, cmd, stopCmd, side) {
  el.classList.add('pressed');
  el._tkStop = stopCmd;
  el._tkSide = side;
  sendCmd(cmd);
  clearInterval(_tk[side]);
  _tk[side] = setInterval(() => sendCmd(cmd), 150);
}

function tankUp(el) {
  const side = el._tkSide;
  if (!side) return;
  clearInterval(_tk[side]);
  el.classList.remove('pressed');
  if (el._tkStop) sendCmd(el._tkStop);
}

function tankStop(el, cmd) {
  el.classList.add('pressed');
  // Cancel any running hold for the relevant side
  if (cmd === 'tank_left_stop')  { clearInterval(_tk.L); _tk.L = null; }
  if (cmd === 'tank_right_stop') { clearInterval(_tk.R); _tk.R = null; }
  if (cmd === 'stop')            { clearInterval(_tk.L); clearInterval(_tk.R); clearInterval(_tk.B); _tk.L = _tk.R = _tk.B = null; }
  sendCmd(cmd);
}

function tankStopUp(el) {
  el.classList.remove('pressed');
}

// ── Mode ───────────────────────────────────────────────────────────────────────
function setMode(m) {
  currentMode = m;
  const modes = ['USER', 'AUTONOMOUS', 'LINE', 'QR'];
  document.querySelectorAll('.tab').forEach((t, i) =>
    t.classList.toggle('active', modes[i] === m));
  apiFetch('/mode', { mode: m });
  updateModeUI();
}

function updateModeUI() {
  const ov   = document.getElementById('mode-overlay');
  const fso  = document.getElementById('face-scan-overlay');
  const qrOv = document.getElementById('qr-mode-overlay');

  fso.classList.add('show');  // face scan always runs
  qrOv.classList.toggle('show', currentMode === 'QR');

  if (_dancing) {
    ov.textContent = '♫  DANCE MODE  ♫';
    ov.style.color = 'var(--accent)';
    ov.classList.add('show');
  } else if (_sleeping) {
    ov.textContent = '💤  SLEEPING…';
    ov.style.color = 'var(--amber)';
    ov.classList.add('show');
  } else if (currentMode === 'AUTONOMOUS') {
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

  const label = _dancing ? 'DANCE' : _sleeping ? 'SLEEP' : currentMode;
  const me = document.getElementById('ci-mode');
  me.textContent = label;
  me.style.color = _dancing  ? 'var(--accent)'
                 : _sleeping ? 'var(--amber)'
                 : currentMode === 'QR' ? 'var(--amber)'
                 : '';
  document.getElementById('sb-mode').textContent = label;
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
  document.getElementById('dpad-wrap').style.display = s === 1 ? ''     : 'none';
  document.getElementById('tank-wrap').style.display = s === 2 ? 'grid' : 'none';
  document.getElementById('ctrl-label').textContent  =
    s === 1 ? 'DIRECTIONAL CONTROL' : 'TANK CONTROL (L / R MOTOR)';
  // Stop all motors when switching schemes
  sendCmd('stop');
  updateDirection('STOPPED');
  clearInterval(window._heldInterval);
  clearInterval(_tk.L); clearInterval(_tk.R); clearInterval(_tk.B);
  _tk.L = _tk.R = _tk.B = null;
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
    d.style.background = on ? hex : 'var(--dim)';
    d.style.boxShadow  = on ? `0 0 8px ${hex}` : '';
  });
}

// ── Dance / Sleep toggles ──────────────────────────────────────────────────────
function toggleDance() {
  if (_dancing) {
    apiFetch('/dance/stop', {});
  } else {
    apiFetch('/dance', {});
  }
}

function toggleSleep() {
  if (_sleeping) {
    apiFetch('/wake', {});
  } else {
    apiFetch('/sleep', {});
  }
}

// ── Face cards ─────────────────────────────────────────────────────────────────
function renderFaceCards(results) {
  const c = document.getElementById('face-results');
  c.innerHTML = '';
  if (!results || !results.length) {
    c.classList.remove('show');
    return;
  }
  c.classList.add('show');
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

// ── Light painting ─────────────────────────────────────────────────────────────
let _lpTimer = null;

function triggerLightPaint(duration) {
  const btns = document.querySelectorAll('#lp-btns .btn');
  btns.forEach(b => b.disabled = true);

  fetch('/light_paint', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ duration }),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        document.getElementById('lp-result').textContent = '⚠ ' + d.error;
        btns.forEach(b => b.disabled = false);
        return;
      }
      document.getElementById('lp-result').textContent = '';
      const ov = document.getElementById('lp-overlay');
      ov.classList.add('show');
      document.getElementById('lp-sub').textContent = `${duration}s exposure`;
      document.getElementById('lp-prog-bar').style.width = '0%';
      clearInterval(_lpTimer);
      _lpTimer = setInterval(_pollLightPaint, 500);
    })
    .catch(() => { btns.forEach(b => b.disabled = false); });
}

async function _pollLightPaint() {
  try {
    const d = await (await fetch('/light_paint_status')).json();
    const pct = Math.round((d.progress || 0) * 100);
    document.getElementById('lp-prog-bar').style.width = pct + '%';

    if (d.active) {
      document.getElementById('lp-sub').textContent =
        d.progress < 0.12 ? 'Settling…' : `Exposing — ${pct}%`;
    } else if (!d.pending) {
      clearInterval(_lpTimer);
      _lpTimer = null;
      document.getElementById('lp-overlay').classList.remove('show');
      document.querySelectorAll('#lp-btns .btn').forEach(b => b.disabled = false);
      if (d.last_file) {
        const r = document.getElementById('lp-result');
        r.textContent = '✓ Saved: ' + d.last_file;
        setTimeout(() => { r.textContent = ''; }, 6000);
      }
    }
  } catch (e) {}
}

// ── QR drive mode status ───────────────────────────────────────────────────────
async function pollQrStatus() {
  if (currentMode !== 'QR') return;
  try {
    const d     = await (await fetch('/qr_status')).json();
    const badge = document.getElementById('qr-action-badge');
    const text  = document.getElementById('qr-scan-text');
    if (d.action) {
      badge.textContent = d.action.toUpperCase().replace(/_/g, ' ');
      badge.classList.add('visible');
      text.textContent  = 'QR DETECTED';
    } else {
      badge.classList.remove('visible');
      text.textContent  = 'SCANNING FOR QR…';
    }
  } catch (e) {}
}

// ── Rift / port-5000 detection ─────────────────────────────────────────────────
async function pollRift() {
  try {
    const d = await (await fetch('/rift_status')).json();
    const el = document.getElementById('sb-rift');
    if (d.online) {
      el.textContent    = 'ON';
      el.style.color    = 'var(--teal)';
    } else {
      el.textContent    = 'OFF';
      el.style.color    = 'var(--dim)';
    }
  } catch (e) {}
}

// ── Keyboard ───────────────────────────────────────────────────────────────────
const keyMap = {
  w: 'forward', s: 'backward', a: 'left', d: 'right', ' ': 'stop',
  ArrowUp: 'forward', ArrowDown: 'backward', ArrowLeft: 'left', ArrowRight: 'right',
};

// Scheme-2 tank keymap: Q/A = left motor, W/S = right motor
const tankKeyMap = {
  q: { cmd: 'tank_left_fwd',  stop: 'tank_left_stop',  side: 'L' },
  a: { cmd: 'tank_left_bwd',  stop: 'tank_left_stop',  side: 'L' },
  w: { cmd: 'tank_right_fwd', stop: 'tank_right_stop', side: 'R' },
  s: { cmd: 'tank_right_bwd', stop: 'tank_right_stop', side: 'R' },
};

const held = new Set();

document.addEventListener('keydown', e => {
  if (e.repeat) return;       // browser repeat — we do our own repeat via setInterval
  if (held.has(e.key)) return;
  held.add(e.key);

  if (currentScheme === 2) {
    const tk = tankKeyMap[e.key.toLowerCase()];
    if (tk) {
      sendCmd(tk.cmd);
      clearInterval(_tk[tk.side]);
      _tk[tk.side] = setInterval(() => sendCmd(tk.cmd), 150);
      return;
    }
  }

  const dir = keyMap[e.key];
  if (dir) {
    sendCmd(dir);
    updateDirection(dir.toUpperCase());
    if (dir !== 'stop') {
      clearInterval(window._heldInterval);
      window._heldInterval = setInterval(() => sendCmd(dir), 150);
    }
  }

  if (e.key === 'm') toggleMusic();
  if (e.key === 'c') sendCmd('photo');
  if (e.key === 'v') toggleVideo();
  if (e.key === 'u') setMode('USER');
  if (e.key === 'o') setMode('AUTONOMOUS');
  if (e.key === 'l') setMode('LINE');
  if (e.key === 'n') toggleDance();
  if (e.key === 'p') toggleSleep();
  if (e.key === 'x') {
    const ss = [0.4, 0.6, 0.8, 1.0];
    setSpeed(ss[(ss.indexOf(currentSpeed) + 1) % ss.length]);
  }
  if (e.key === '1') setScheme(1);
  if (e.key === '2') setScheme(2);
});

document.addEventListener('keyup', e => {
  held.delete(e.key);

  if (currentScheme === 2) {
    const tk = tankKeyMap[e.key.toLowerCase()];
    if (tk) {
      // Only stop that side if no other key for that side is still held
      const sameKeys = Object.entries(tankKeyMap)
        .filter(([, v]) => v.side === tk.side)
        .map(([k]) => k);
      if (!sameKeys.some(k => held.has(k))) {
        clearInterval(_tk[tk.side]);
        _tk[tk.side] = null;
        sendCmd(tk.stop);
      }
      return;
    }
  }

  if (keyMap[e.key]) {
    clearInterval(window._heldInterval);
    const anyMoveHeld = Object.keys(keyMap).some(k => held.has(k) && keyMap[k] !== 'stop');
    if (!anyMoveHeld) {
      sendCmd('stop');
      updateDirection('STOPPED');
    }
  }
});

// ── Polling ────────────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const d = await (await fetch('/status')).json();
    updateDirection(d.direction || 'STOPPED');
    if (d.led) updateLeds(d.led);

    // Auto-download new captures to this device
    if (d.last_photo && d.last_photo !== _lastPhoto) {
      _lastPhoto = d.last_photo;
      _autoDownload(`/media/photo/${d.last_photo}`, d.last_photo);
    }
    if (d.last_video && d.last_video !== _lastVideo) {
      _lastVideo = d.last_video;
      _autoDownload(`/media/video/${d.last_video}`, d.last_video);
    }

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
      document.getElementById('track-name').classList.toggle('playing', musicPlaying);
    }
    if (d.track_name) {
      document.getElementById('track-name').textContent = d.track_name;
    }
    if (d.video_rec !== videoRec) {
      videoRec = d.video_rec;
      document.getElementById('btn-video').textContent = videoRec ? '⏹ STOP' : '⏺ REC';
      document.getElementById('btn-video').classList.toggle('active', videoRec);
      document.getElementById('rec-badge').classList.toggle('show', videoRec);
    }

    if (d.dancing !== undefined && d.dancing !== _dancing) {
      _dancing = d.dancing;
      const btn = document.getElementById('btn-dance');
      if (btn) { btn.textContent = _dancing ? '⏹ STOP DANCE' : '♫ DANCE'; btn.classList.toggle('active', _dancing); }
      updateModeUI();
    }
    if (d.sleeping !== undefined && d.sleeping !== _sleeping) {
      _sleeping = d.sleeping;
      const btn = document.getElementById('btn-sleep');
      if (btn) { btn.textContent = _sleeping ? '☀ WAKE' : '💤 SLEEP'; btn.classList.toggle('active', _sleeping); }
      updateModeUI();
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
  try {
    const d = await (await fetch('/face/results')).json();
    if (d.results) renderFaceCards(d.results);
  } catch (e) {}
}

async function pollAudioAmps() {
  if (!musicPlaying) return;
  try {
    const d = await (await fetch('/audio_amps')).json();
    if (Array.isArray(d.amps) && d.amps.length > 0) _audioAmps = d.amps;
  } catch (e) {}
}

setInterval(pollStatus,    800);
setInterval(pollStats,    2000);
setInterval(pollFaces,    1500);
setInterval(pollRift,     5000);
setInterval(pollQrStatus,  400);
setInterval(pollAudioAmps, 300);
pollStatus();
pollStats();
pollRift();
