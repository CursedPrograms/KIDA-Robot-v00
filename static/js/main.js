/* KIDA HUD — browser twin of the robot's ui.py window.
   State comes from /status (ui.py publishes it every frame) and
   /control/stats/; every key/click is POSTed to /command as the same
   string ui.py's command processor takes. Bindings match ui.py. */

const MODES       = ['USER', 'AUTONOMOUS', 'LINE'];
const NATIVE_W    = 320, NATIVE_H = 240;
const HEARTBEAT   = 250;   // ms — the robot stops a remote drive unheard for 800 ms
const $           = id => document.getElementById(id);

let S = {};                // last /status
let connected = false;
let frame = 0;

// ── Build the static bits (LED dots, waveform bars) ─────────────────────────
for (let i = 0; i < 8; i++) $('led-dots').appendChild(Object.assign(document.createElement('i'), { className: 'led' }));
for (let i = 0; i < 22; i++) $('wave').appendChild(document.createElement('i'));

// ── Commands ─────────────────────────────────────────────────────────────────
function send(command) {
  fetch('/command', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command }), keepalive: true,
  }).catch(() => {});
}
const mode     = () => S.mode || 'USER';
const isUser   = () => mode() === 'USER';
const canSpeed = () => mode() === 'USER' || mode() === 'AUTONOMOUS';   // autonomous cruises at the selected speed
const modeCmd = m => `_mode_${m.toLowerCase()}`;

// ── Buttons ──────────────────────────────────────────────────────────────────
document.querySelectorAll('[data-cmd]').forEach(b => b.addEventListener('click', () => {
  if (b.hasAttribute('data-user') && !isUser()) return;     // ui.py: USER-mode only
  if (b.hasAttribute('data-speed') && !canSpeed()) return;
  send(b.dataset.cmd);
}));
document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => send(`_mode_${b.dataset.mode}`)));
$('btn-skip').addEventListener('click', () => { if (S.music_playing) send('skip_music'); });

// D-pad: hold to drive (resent), release stops — same as ui.py with the mouse
let holdDir = null;
document.querySelectorAll('.dp').forEach(b => {
  b.addEventListener('pointerdown', e => {
    if (!isUser()) return;
    b.setPointerCapture(e.pointerId);
    holdDir = b.dataset.dir === 'stop' ? null : b.dataset.dir;
    if (!holdDir) send('stop');
    updateDrive();
  });
  const up = () => { holdDir = null; updateDrive(); };
  b.addEventListener('pointerup', up);
  b.addEventListener('pointercancel', up);
});

// ── Keyboard (ui.py bindings) ────────────────────────────────────────────────
const held = new Set();
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;   // leave browser shortcuts (Ctrl+C etc.) alone
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (k === 'Tab' || k === ' ') e.preventDefault();
  if ('wasdq'.includes(k) && k.length === 1) { held.add(k); updateDrive(); }
  if (e.repeat) return;

  if      (k === 'Tab') send(modeCmd(MODES[(MODES.indexOf(mode()) + 1) % 3] || 'USER'));
  else if (k === 'm')   send('play_music');
  else if (k === ' ')   send('stop_music');
  else if (k === 'u')   send(modeCmd('USER'));
  else if (k === 'o')   send(modeCmd('AUTONOMOUS'));
  else if (k === 'l')   send(modeCmd('LINE'));
  else if (k === 'x' && canSpeed()) send('speed');
  else if (isUser()) {
    if      (k === '1') send('scheme_1');
    else if (k === '2') send('scheme_2');
    else if (k === 'c') send('photo');
    else if (k === 'v') send('video_toggle');
    else if (k === 'f') send('face_save');   // not S — that drives
  }
});
document.addEventListener('keyup', e => { held.delete(e.key.toLowerCase()); updateDrive(); });
window.addEventListener('blur', () => { held.clear(); holdDir = null; updateDrive(); });

// ── Drive intent: sent on change, resent while held, "stop" on release ───────
let lastSent = null, lastBeat = 0;
function driveIntent() {
  if (!isUser()) return null;
  const h = k => held.has(k);
  if ((S.ctrl_scheme || 1) === 1 && ['w', 's', 'a', 'd'].some(h))
    return h('w') ? 'forward' : h('s') ? 'backward' : h('a') ? 'left' : 'right';
  if (S.ctrl_scheme === 2 && ['q', 'a', 'w', 's'].some(h))
    return `tank:${h('q') ? 1 : h('a') ? -1 : 0}:${h('w') ? 1 : h('s') ? -1 : 0}`;
  return holdDir;
}
function updateDrive() {
  const intent = driveIntent(), now = performance.now();
  if (intent !== lastSent) { send(intent || 'stop'); lastSent = intent; lastBeat = now; }
  else if (intent && now - lastBeat >= HEARTBEAT) { send(intent); lastBeat = now; }
}
setInterval(updateDrive, 50);

// ── Render /status ───────────────────────────────────────────────────────────
const setText = (id, v) => { const el = $(id); if (el.textContent !== String(v)) el.textContent = v; };
const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;

function renderStatus() {
  const m = mode(), dir = S.direction || 'STOPPED', spd = (S.speed ?? 0.4).toFixed(1);
  const scheme = (S.ctrl_scheme || 1) === 1 ? 'WASD' : 'QA/WS';
  const led = S.led || [0, 0, 0], faces = S.faces || [], music = !!S.music_playing;

  // tabs / mode overlay
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', MODES[i] === m));
  const ov = $('mode-ov');
  ov.classList.toggle('on', m === 'AUTONOMOUS' || m === 'LINE');
  ov.textContent = m === 'AUTONOMOUS' ? '— AUTONOMOUS —' : '— LINE FOLLOW —';
  ov.style.color = m === 'AUTONOMOUS' ? 'var(--teal)' : 'var(--blue)';

  // LEDs
  const lit = led.some(c => c > 10);
  document.querySelectorAll('.led').forEach(d => d.style.background = lit ? rgb(led) : '');

  // info strip
  setText('i-dir', dir); $('i-dir').style.color = dir !== 'STOPPED' ? 'var(--amber)' : 'var(--text-sec)';
  setText('i-spd', spd);
  setText('i-sch', scheme);
  if (m === 'FACE') { setText('i-4l', 'FACES'); setText('i-4v', `FACES ${faces.length}`); $('i-4v').style.color = 'var(--purple)'; }
  else              { setText('i-4l', 'LED');   setText('i-4v', `R${led[0]} G${led[1]} B${led[2]}`); $('i-4v').style.color = 'var(--text-sec)'; }

  // right panel
  document.querySelectorAll('.dp').forEach(b => b.classList.toggle('cur', b.dataset.dir !== 'stop' && b.dataset.dir.toUpperCase() === dir));
  document.querySelectorAll('#speeds .hb').forEach((b, i) => b.classList.toggle('active', (S.speed_idx || 0) === i));
  $('sch-1').classList.toggle('active', (S.ctrl_scheme || 1) === 1);
  $('sch-2').classList.toggle('active', S.ctrl_scheme === 2);
  const v = $('btn-video');
  setText('btn-video', S.video_rec ? 'STOP REC' : 'REC');
  v.classList.toggle('active', !!S.video_rec); v.classList.toggle('danger', !!S.video_rec);
  const scan = S.face_scan !== false;
  setText('btn-scan', scan ? 'SCAN OFF' : 'SCAN ON');
  $('btn-scan').classList.toggle('active', scan);

  // camera overlays
  $('rec').classList.toggle('on', !!S.video_rec);
  $('deepface-missing').style.display = scan && !faces.length && S.deepface_ok === false ? 'block' : 'none';
  renderFaces(scan ? faces : []);

  // music
  setText('btn-play', music ? 'PAUSE' : 'PLAY');
  $('btn-play').classList.toggle('active', music);
  setText('track', (S.track || 'No track').slice(0, 22));
  $('track').classList.toggle('on', music);
  $('wave').classList.toggle('on', music);

  // bottom bar
  setText('sb-mode', m); setText('sb-sch', scheme); setText('sb-spd', spd);
  setText('sb-faces', faces.length); $('sb-faces').classList.toggle('hot', faces.length > 0);
  setText('sb-frm', S.frame ?? 0);
}

function renderFaces(faces) {
  const box = $('faces');
  box.innerHTML = '';
  for (const f of faces) {
    const r = f.region || {};
    if (!r.w || !r.h) continue;
    const el = document.createElement('div');
    el.className = 'fbox';
    el.style.cssText = `left:${r.x / NATIVE_W * 100}%;top:${r.y / NATIVE_H * 100}%;` +
                       `width:${r.w / NATIVE_W * 100}%;height:${r.h / NATIVE_H * 100}%;` +
                       `--fc:${f.gender === 'Woman' ? 'var(--purple)' : 'var(--teal)'}`;
    const tag = document.createElement('b');
    tag.textContent = `${(f.gender || '?')[0]}  ${f.age || 0}y  ${(f.conf || 0).toFixed(0)}%`;
    el.appendChild(tag);
    box.appendChild(el);
  }
}

// ── Render /control/stats/ ───────────────────────────────────────────────────
function renderStats(s) {
  const cpu = s.cpu || 0, temp = s.temp || 0, ru = s.ram_used || 0, rt = s.ram_total || 1;
  setText('v-thr', s.threads || 0);
  setText('v-temp', `${temp.toFixed(0)}C`); $('v-temp').classList.toggle('warn', temp > 65);
  setText('v-cpu', `${cpu.toFixed(0)}%`);
  setText('s-cpu', `${cpu.toFixed(0)}%`);   $('b-cpu').style.width  = `${Math.min(cpu, 100)}%`;
  setText('s-temp', `${temp.toFixed(0)}°C`); $('b-temp').style.width = `${Math.min(temp / 85 * 100, 100)}%`;
  setText('s-ram', `${ru}/${rt}M`);          $('b-ram').style.width  = `${Math.min(ru / rt * 100, 100)}%`;
  setText('n-lat', s.latency || 'N/A');
  setText('n-thr', s.threads || 0);
  setText('n-dr', `${s.disk_read || 0} MB`);
  setText('n-dw', `${s.disk_write || 0} MB`);
  setText('n-boot', s.boot_time || '--:--');
  if (s.ip && s.ip !== 'N/A') setText('ip', s.ip);
}

// ── Polling ──────────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    S = await (await fetch('/status', { cache: 'no-store' })).json();
    connected = true;
    renderStatus();
  } catch (e) { connected = false; }
  $('nolink').classList.toggle('on', !connected);
  $('ping').classList.toggle('off', !connected);
  setTimeout(pollStatus, 250);
}
async function pollStats() {
  try { renderStats((await (await fetch('/control/stats/', { cache: 'no-store' })).json()).stats || {}); }
  catch (e) {}
  setTimeout(pollStats, 2000);
}
pollStatus();
pollStats();

// Camera stream: reconnect if the MJPEG drops
$('cam-img').addEventListener('error', () => setTimeout(() => { $('cam-img').src = `/video_feed?t=${Date.now()}`; }, 1500));

// ── Animation (25 fps like ui.py): waveform + face scan line ─────────────────
const waveBars = [...document.querySelectorAll('#wave i')];
setInterval(() => {
  frame++;
  const playing = !!S.music_playing;
  waveBars.forEach((b, i) => {
    b.style.height = playing ? `${Math.round((Math.sin(frame * 0.12 + i * 0.3) * 0.5 + 0.5) * 30 * 0.85 + 3)}px` : '3px';
  });
  const sl = $('scanline');
  const showScan = S.face_scan !== false && !(S.faces || []).length && S.deepface_ok !== false;
  sl.style.display = showScan ? 'block' : 'none';
  if (showScan) sl.style.top = `${(Math.sin(frame * 0.08) * 0.5 + 0.5) * 100}%`;
}, 40);
