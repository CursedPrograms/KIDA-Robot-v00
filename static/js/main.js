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

// ── Drive maths — same as scripts/drive_mix.py ───────────────────────────────
// Wheel speeds are -1..1 (fraction of the robot's selected speed, + forward).
const ARC_INNER = 0.4;    // inside wheel during an arc turn (W+A etc.)
const DEADZONE  = 0.15;

function keysToWheels(fwd, back, left, right, arc) {
  const t = (fwd ? 1 : 0) - (back ? 1 : 0), s = (right ? 1 : 0) - (left ? 1 : 0);
  if (!t && !s) return null;
  if (!t) return [s, -s];                       // spin on the spot
  if (!s || !arc) return [t, t];                // straight (turn key ignored with ARC off)
  return s < 0 ? [ARC_INNER * t, t] : [t, ARC_INNER * t];
}
const dz = v => Math.abs(v) < DEADZONE ? 0 : (Math.abs(v) - DEADZONE) / (1 - DEADZONE) * Math.sign(v);
function stickToWheels(x, y) {                  // y: + forward
  x = dz(Math.max(-1, Math.min(1, x))); y = dz(Math.max(-1, Math.min(1, y)));
  if (!x && !y) return null;
  const l = y + x, r = y - x, m = Math.max(1, Math.abs(l), Math.abs(r));
  return [l / m, r / m];
}
function tankSticksToWheels(ly, ry) { const l = dz(ly), r = dz(ry); return l || r ? [l, r] : null; }
function wheelsToCommand(l, r) {
  l = Math.round(l * 20) / 20 + 0; r = Math.round(r * 20) / 20 + 0;
  const named = { '1,1': 'forward', '-1,-1': 'backward', '-1,1': 'left', '1,-1': 'right' };
  return named[`${l},${r}`] || `drive:${l.toFixed(2)}:${r.toFixed(2)}`;
}

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
    else if (k === 't') send('arc_toggle');
    else if (k === 'c') send('photo');
    else if (k === 'v') send('video_toggle');
    else if (k === 'f') send('face_save');   // not S — that drives
  }
});
document.addEventListener('keyup', e => { held.delete(e.key.toLowerCase()); updateDrive(); });
window.addEventListener('blur', () => { held.clear(); holdDir = null; updateDrive(); });

// ── Drive intent: sent on change, resent while held, "stop" on release ───────
let lastSent = null, lastBeat = 0;
// Priority matches the robot: keyboard, gamepad, on-screen joystick, d-pad
function driveIntent() {
  if (!isUser()) return null;
  const h = k => held.has(k), arc = S.arc_turn !== false, scheme = S.ctrl_scheme || 1;
  const keyWheels = keysToWheels(h('w'), h('s'), h('a'), h('d'), arc);
  if (scheme === 1 && keyWheels) return wheelsToCommand(...keyWheels);
  if (scheme === 2 && ['q', 'a', 'w', 's'].some(h))
    return `tank:${h('q') ? 1 : h('a') ? -1 : 0}:${h('w') ? 1 : h('s') ? -1 : 0}`;
  const p = padState;
  if (p) {
    const w = (scheme === 2 ? tankSticksToWheels(p.ly, p.ry) : stickToWheels(p.lx, p.ly))
              || keysToWheels(p.up, p.down, p.left, p.right, arc);
    if (w) return wheelsToCommand(...w);
  }
  if (joyXY) return wheelsToCommand(...(stickToWheels(...joyXY) || [0, 0]));
  return holdDir;
}
function updateDrive() {
  pollGamepad();
  const intent = driveIntent(), now = performance.now();
  if (intent !== lastSent) { send(intent || 'stop'); lastSent = intent; lastBeat = now; }
  else if (intent && now - lastBeat >= HEARTBEAT) { send(intent); lastBeat = now; }
}
setInterval(updateDrive, 50);

// ── On-screen joystick: drag to drive, release stops ─────────────────────────
let joyXY = null;
const joy = $('joy'), knob = $('joy-knob');
function joyFromEvent(e) {
  const b = joy.getBoundingClientRect(), rad = b.width / 2, reach = rad - knob.offsetWidth / 2;
  let x = (e.clientX - b.left - rad) / reach, y = (b.top + rad - e.clientY) / reach;
  const m = Math.hypot(x, y);
  if (m > 1) { x /= m; y /= m; }
  return [x, y];
}
function showKnob(xy) {
  const reach = joy.offsetWidth / 2 - knob.offsetWidth / 2, [x, y] = xy || [0, 0];
  knob.style.transform = `translate(calc(-50% + ${x * reach}px), calc(-50% + ${-y * reach}px))`;
}
joy.addEventListener('pointerdown', e => {
  if (!isUser()) return;
  joy.setPointerCapture(e.pointerId);
  joyXY = joyFromEvent(e); joy.classList.add('on'); updateDrive();
});
joy.addEventListener('pointermove', e => { if (joyXY) { joyXY = joyFromEvent(e); updateDrive(); } });
const joyUp = () => { joyXY = null; joy.classList.remove('on'); updateDrive(); };
joy.addEventListener('pointerup', joyUp);
joy.addEventListener('pointercancel', joyUp);

// ── Gamepad (browser Gamepad API, "standard" layout) — same buttons as gamepad.py ─
// Left stick / d-pad drive (both sticks in QA/WS), A speed, B stop, X photo,
// Y arc, LB/RB mode, Back save faces, Start music. Browsers only report a pad
// after a button is pressed while this page is open.
const PAD_BUTTONS = { 0: ['speed'], 1: ['_mode_user', 'stop'], 2: ['photo'], 3: ['arc_toggle'],
                      8: ['face_save'], 9: ['music_toggle'] };
let padState = null, padHeld = new Set();
function pollGamepad() {
  const gp = [...(navigator.getGamepads ? navigator.getGamepads() : [])].find(g => g && g.connected);
  if (!gp) { padState = null; padHeld.clear(); return; }
  const btn = i => !!(gp.buttons[i] && gp.buttons[i].pressed);
  const now = new Set(gp.buttons.map((b, i) => b.pressed ? i : -1).filter(i => i >= 0));
  for (const i of now) {
    if (padHeld.has(i)) continue;                         // only on the press, not while held
    (PAD_BUTTONS[i] || []).forEach(send);
    if (i === 4 || i === 5) {                              // LB / RB: previous / next mode
      const n = (MODES.indexOf(mode()) + (i === 5 ? 1 : -1) + MODES.length) % MODES.length;
      send(modeCmd(MODES[n]));
    }
  }
  padHeld = now;
  padState = { lx: gp.axes[0] || 0, ly: -(gp.axes[1] || 0), rx: gp.axes[2] || 0, ry: -(gp.axes[3] || 0),
               up: btn(12), down: btn(13), left: btn(14), right: btn(15) };
}

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
  $('sch-arc').classList.toggle('active', S.arc_turn !== false);
  joy.classList.toggle('off', !isUser());
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
  const padStick = padState && (S.ctrl_scheme || 1) === 1 && stickToWheels(padState.lx, padState.ly)
                   ? [padState.lx, padState.ly] : null;
  showKnob(joyXY || padStick);
  setText('sb-pad', padState ? 'ON' : '—');
  const sl = $('scanline');
  const showScan = S.face_scan !== false && !(S.faces || []).length && S.deepface_ok !== false;
  sl.style.display = showScan ? 'block' : 'none';
  if (showScan) sl.style.top = `${(Math.sin(frame * 0.08) * 0.5 + 0.5) * 100}%`;
}, 40);
