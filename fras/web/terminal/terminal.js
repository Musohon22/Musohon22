// Terminal kiosk UI (spec H.2, TRM-00 … TRM-17). Talks only to the local edge agent on 127.0.0.1
// (/api/status, /api/attempt, /api/card, /api/help), so the gate keeps working without internet.
// Served by the cloud server (/terminal) it runs in DEMO mode: nothing is recorded and no gate opens.

const root = document.getElementById('root');
const T = {
  uz: { idle: 'Kameraga qarang', guide: { come_closer: 'Yaqinroq keling', single_person: 'Iltimos, bittadan', too_dark: "Yorug'roq joyga turing",
    blurry: "Qimirlamang", off_center: "Yuzingizni ramka markaziga keltiring", default: "Yuzingizni ramkaga keltiring" },
  scanning: 'Tekshirilmoqda…', in: 'Kirish', out: 'Chiqish', card: 'Karta / PIN', help: 'Yordam', offline: 'Oflayn — qaydlar saqlanmoqda',
  cardTitle: 'Karta raqami yoki PIN', cardNo: 'Karta raqamini kiriting', pin: 'PIN kiriting', cancel: 'Bekor', ok: 'OK', clear: 'Tozalash',
  notActivated: 'Terminal faollashtirilmagan', notActivatedSub: "Administrator: qurilmani ro'yxatdan o'tkazing va `fras_edge activate --code …` buyrug'ini bajaring.",
  cameraOff: 'Kamera ishlamayapti', cameraOffSub: 'Karta/PIN orqali qayd qiling yoki qo\'riqchini chaqiring.',
  demo: "DEMO rejim: bu sahifa serverdan ochilgan. Qayd yozilmaydi va darvoza ochilmaydi. Haqiqiy terminal edge-agent orqali ishlaydi (http://127.0.0.1:8100).",
  dev: 'DEV biometrika — haqiqiy tanish emas', serviceSub: "Texnik xizmat. Iltimos, boshqa terminaldan foydalaning." },
  ru: { idle: 'Посмотрите в камеру', guide: { come_closer: 'Подойдите ближе', single_person: 'По одному, пожалуйста', too_dark: 'Встаньте в более светлое место',
    blurry: 'Не двигайтесь', off_center: 'Поместите лицо в центр рамки', default: 'Поместите лицо в рамку' },
  scanning: 'Проверка…', in: 'Вход', out: 'Выход', card: 'Карта / PIN', help: 'Помощь', offline: 'Офлайн — отметки сохраняются',
  cardTitle: 'Номер карты или PIN', cardNo: 'Введите номер карты', pin: 'Введите PIN', cancel: 'Отмена', ok: 'OK', clear: 'Сброс',
  notActivated: 'Терминал не активирован', notActivatedSub: 'Администратор: зарегистрируйте устройство и выполните `fras_edge activate --code …`.',
  cameraOff: 'Камера не работает', cameraOffSub: 'Используйте карту/PIN или вызовите охрану.',
  demo: 'ДЕМО: страница открыта с сервера. Отметки не записываются, турникет не открывается.', dev: 'DEV биометрия — не настоящее распознавание',
  serviceSub: 'Техобслуживание. Воспользуйтесь другим терминалом.' },
};
const STYLE = { 'TRM-05': ['ok', '✓'], 'TRM-06': ['ok', '👋'], 'TRM-07': ['info', '↻'], 'TRM-08': ['warn', '?'], 'TRM-09': ['bad', '⛔'],
  'TRM-10': ['bad', '✕'], 'TRM-11': ['warn', '↺'], 'TRM-13': ['info', '🛎'], 'TRM-14': ['bad', '⚠'], 'TRM-16': ['bad', '⚠'] };

const S = { lang: 'uz', status: null, demo: false, direction: 'in', busy: false, overlay: null, session: crypto.randomUUID?.() || String(Date.now()),
  lastMotion: 0, prevLuma: null, cooldownUntil: 0, stream: null };
const tr = () => T[S.lang] || T.uz;
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (v == null || v === false) continue; if (k === 'class') el.className = v; else if (k.startsWith('on')) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v === true ? '' : v); }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
};

// ---------------------------------------------------------------- local API (with demo fallback)
async function call(path, body) {
  if (S.demo) return demoResponse(path, body);
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok && r.status !== 422) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
let demoN = 0;
function demoResponse(path, body) {
  const now = new Date().toTimeString().slice(0, 5);
  if (path === '/api/status') return { activated: true, online: true, outbox: 0, site: 'Demo zavod', gate: 'Demo darvoza', direction: 'both', camera_ok: true, provider_dev: true, config: {} };
  if (path === '/api/help') return { state: 'TRM-13', code: 'T-213', message: T[S.lang].help, duration_ms: 4000 };
  if (path === '/api/card') {
    if (!body.pin) return { state: 'TRM-12', message: '', need_pin: true, duration_ms: 20000 };
    return { state: S.direction === 'in' ? 'TRM-05' : 'TRM-06', message: `${S.direction === 'in' ? 'Xush kelibsiz' : 'Xayr'}, Demo Xodim`, time: now, duration_ms: 2000, open_gate: true };
  }
  const seq = ['TRM-05', 'TRM-11', 'TRM-08', 'TRM-07'];
  const st = seq[demoN++ % seq.length];
  const msg = { 'TRM-05': 'Xush kelibsiz, Demo Xodim', 'TRM-11': 'Iltimos, yana bir bor kameraga qarang', 'TRM-08': 'Siz tanilmadingiz. Qayta urining yoki karta ishlating', 'TRM-07': `Siz allaqachon qayd etilgansiz ${now}` }[st];
  return { state: st, message: msg, time: now, duration_ms: st === 'TRM-08' ? 4000 : 2000 };
}

// ---------------------------------------------------------------- layout
const els = {};
function build() {
  root.innerHTML = '';
  els.site = h('span', { class: 'site' }); els.gate = h('span', { class: 'k-pill' }); els.net = h('span', { class: 'k-pill', hidden: true });
  els.dev = h('span', { class: 'k-pill dev', hidden: true }, tr().dev); els.clock = h('span', { class: 'clock' });
  els.lang = h('button', { class: 'k-pill', style: 'border:0;cursor:pointer', onclick: () => { S.lang = S.lang === 'uz' ? 'ru' : 'uz'; build(); refreshStatus(); } }, S.lang === 'uz' ? 'RU' : 'UZ');
  const top = h('div', { class: 'k-top' }, els.site, els.gate, h('span', { class: 'spacer' }), els.net, els.dev, els.lang, els.clock);
  els.video = h('video', { class: 'k-video', autoplay: true, muted: true, playsinline: true });
  els.frame = h('div', { class: 'k-frame' });
  els.hint = h('div', { class: 'k-hint', role: 'status', 'aria-live': 'polite' }, tr().idle);
  els.stage = h('div', { class: 'k-stage' }, els.video, els.frame, els.hint);
  els.dirIn = h('button', { class: 'k-btn', onclick: () => setDirection('in') }, '→ ', tr().in);
  els.dirOut = h('button', { class: 'k-btn', onclick: () => setDirection('out') }, '← ', tr().out);
  els.dirs = h('span', { style: 'display:contents' }, els.dirIn, els.dirOut);
  const bottom = h('div', { class: 'k-bottom' }, els.dirs, h('button', { class: 'k-btn', onclick: openPad }, '💳 ', tr().card),
    h('button', { class: 'k-btn', onclick: callHelp }, '🛎 ', tr().help));
  root.append(S.demo ? h('div', { class: 'k-banner' }, tr().demo) : '', top, els.stage, bottom);
  if (S.demo) root.style.gridTemplateRows = 'auto auto 1fr auto';
  if (S.stream) els.video.srcObject = S.stream;
  setDirection(S.direction);
}

function setDirection(d) { S.direction = d; els.dirIn.classList.toggle('sel', d === 'in'); els.dirOut.classList.toggle('sel', d === 'out'); }

function applyStatus(st) {
  S.status = st;
  els.site.textContent = st.site || 'FRAS';
  els.gate.textContent = st.gate || '—';
  els.net.hidden = st.online !== false; els.net.className = 'k-pill off'; els.net.textContent = `${tr().offline} (${st.outbox ?? 0})`;
  els.dev.hidden = !st.provider_dev;
  const both = !st.direction || st.direction === 'both';
  els.dirs.style.display = both ? 'contents' : 'none';
  if (!both && !S.overlay) S.direction = st.direction;
  if (st.config?.kiosk_language && !S.langSet) { S.lang = st.config.kiosk_language === 'ru' ? 'ru' : 'uz'; S.langSet = true; build(); }
  if (!st.activated) return full(tr().notActivated, tr().notActivatedSub, 'TRM-00');
  if (st.config?.maintenance) return full('🛠', tr().serviceSub, 'TRM-17');
  if (st.outbox_fill_pct >= 100) return full('⚠', S.lang === 'ru' ? 'Память терминала заполнена. Обратитесь к охране.' : "Terminal xotirasi to'lgan. Qo'riqchiga murojaat qiling.", 'TRM-16');
  if (S.fullState) { S.fullState.remove(); S.fullState = null; }
}

function full(big, sub, code) {
  if (S.fullState?.dataset.code === code) return;
  S.fullState?.remove();
  S.fullState = h('div', { class: 'k-full', 'data-code': code, style: 'background:var(--bg);z-index:7' }, h('div', {}, h('div', { class: 'big' }, big), h('div', { class: 'sub' }, sub), h('div', { class: 'sub' }, code)));
  els.stage.append(S.fullState);
}

async function refreshStatus() {
  try { applyStatus(await call('/api/status')); }
  catch { els.net.hidden = false; els.net.textContent = 'Agent bilan aloqa yo\'q'; }
}

// ---------------------------------------------------------------- result overlay
function showResult(r) {
  clearOverlay();
  if (r.state === 'TRM-02') { els.hint.textContent = tr().guide[r.hint] || tr().guide.default; els.frame.className = 'k-frame warn'; return; }
  if (r.state === 'TRM-12') { openPad(r.pin_error ? (r.locked ? 'PIN bloklandi. 15 daqiqadan so\'ng urining.' : "PIN noto'g'ri") : ''); return; }
  const [cls, icon] = STYLE[r.state] || ['info', 'ℹ'];
  els.frame.className = `k-frame ${cls === 'ok' ? 'ok' : cls === 'bad' ? 'bad' : 'warn'}`;
  const ov = h('div', { class: `k-result ${cls}`, role: 'alert' }, h('div', {},
    h('div', { class: 'icon', 'aria-hidden': 'true' }, icon), h('div', { class: 'msg' }, r.message || ''),
    r.open_gate && r.time ? h('div', { class: 'sub' }, r.time) : null,
    r.offline ? h('div', { class: 'sub' }, tr().offline) : null), r.code ? h('div', { class: 'code' }, r.code) : null);
  if (r.state === 'TRM-08' || r.state === 'TRM-14') ov.firstChild.append(h('div', { style: 'margin-top:24px' }, h('button', { class: 'k-btn primary', onclick: () => openPad() }, '💳 ', tr().card)));
  els.stage.append(ov); S.overlay = ov;
  const ms = r.duration_ms || 2000;
  S.cooldownUntil = Date.now() + Math.max(ms, 1500) + 800;
  if (ms > 0) S.overlayTimer = setTimeout(clearOverlay, ms);
}
function clearOverlay() {
  clearTimeout(S.overlayTimer); S.overlay?.remove(); S.overlay = null;
  els.frame.className = 'k-frame'; els.hint.textContent = tr().idle;
}

// ---------------------------------------------------------------- camera + capture
const canvas = document.createElement('canvas');
const small = document.createElement('canvas'); small.width = 32; small.height = 24;

async function startCamera() {
  try {
    S.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false });
    els.video.srcObject = S.stream; S.cameraOk = true;
    requestAnimationFrame(loop);
  } catch {
    S.cameraOk = false;
    showResult({ state: 'TRM-14', code: 'T-114', message: `${tr().cameraOff}. ${tr().cameraOffSub}`, duration_ms: 0 });
  }
}

function grab(quality = 0.85) {
  const v = els.video;
  const w = 640, hh = Math.round((v.videoHeight / v.videoWidth) * 640) || 480;
  canvas.width = w; canvas.height = hh;
  canvas.getContext('2d').drawImage(v, 0, 0, w, hh);
  return canvas.toDataURL('image/jpeg', quality);
}

// Coarse presence trigger: luminance change in the centre of the frame. The edge agent does
// the real detection/quality/liveness; this only decides when to send frames.
function motion() {
  const v = els.video; if (!v.videoWidth) return 0;
  const ctx = small.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(v, v.videoWidth * 0.25, v.videoHeight * 0.15, v.videoWidth * 0.5, v.videoHeight * 0.7, 0, 0, 32, 24);
  const d = ctx.getImageData(0, 0, 32, 24).data;
  const luma = new Float32Array(32 * 24);
  for (let i = 0; i < luma.length; i++) luma[i] = d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11;
  let diff = 0;
  if (S.prevLuma) for (let i = 0; i < luma.length; i++) diff += Math.abs(luma[i] - S.prevLuma[i]);
  S.prevLuma = luma;
  return diff / luma.length;
}

let lastCheck = 0;
function loop(ts) {
  requestAnimationFrame(loop);
  if (ts - lastCheck < 200) return;
  lastCheck = ts;
  const m = motion();
  if (m > 6) S.lastMotion = Date.now();
  const recentlyMoved = Date.now() - S.lastMotion < 1500;
  if (recentlyMoved && !S.busy && !S.overlay && !S.pad && !S.fullState && Date.now() > S.cooldownUntil) attempt();
}

async function attempt() {
  S.busy = true; els.frame.className = 'k-frame scan'; els.hint.textContent = tr().scanning;
  try {
    const frames = [];
    for (let i = 0; i < 3; i++) { frames.push(grab()); if (i < 2) await new Promise((r) => setTimeout(r, 160)); }
    const r = await call('/api/attempt', { frames, direction: S.direction, session: S.session });
    if (r.state === 'TRM-02' || r.state === 'TRM-11') S.cooldownUntil = Date.now() + 700;
    showResult(r);
  } catch {
    showResult({ state: 'TRM-14', code: 'T-114', message: tr().cameraOffSub, duration_ms: 4000 });
  } finally { S.busy = false; }
}

// ---------------------------------------------------------------- card / PIN (TRM-12)
function openPad(error = '') {
  closePad(); clearOverlay();
  let stage = S.padCard ? 'pin' : 'card';
  let value = '';
  const disp = h('div', { class: 'disp', 'aria-live': 'polite' });
  const title = h('h2');
  const err = h('div', { class: 'err', role: 'alert' }, error);
  const render = () => { title.textContent = stage === 'card' ? tr().cardNo : tr().pin; disp.textContent = stage === 'pin' ? '•'.repeat(value.length) : value; };
  const key = (k) => { err.textContent = ''; if (value.length < 20) value += k; render(); bump(); };
  const submit = async () => {
    if (!value) return;
    if (stage === 'card') { S.padCard = value; }
    try {
      const r = await call('/api/card', stage === 'card' ? { card_no: value, direction: S.direction } : { card_no: S.padCard, pin: value, direction: S.direction });
      if (r.state === 'TRM-12' && !r.pin_error) { stage = 'pin'; value = ''; render(); bump(); return; }
      if (r.state === 'TRM-12') { value = ''; err.textContent = r.locked ? "PIN bloklandi. 15 daqiqadan so'ng urining." : "PIN noto'g'ri"; render(); bump(); return; }
      closePad(); showResult(r);
    } catch { err.textContent = "Agent bilan aloqa yo'q"; }
  };
  const keys = h('div', { class: 'k-keys' }, ...'123456789'.split('').map((d) => h('button', { onclick: () => key(d) }, d)),
    h('button', { class: 'alt', onclick: () => { value = ''; render(); } }, tr().clear), h('button', { onclick: () => key('0') }, '0'),
    h('button', { class: 'alt', style: 'background:var(--info)', onclick: submit }, tr().ok));
  S.pad = h('div', { class: 'k-pad', role: 'dialog', 'aria-label': tr().cardTitle }, h('div', { class: 'box' }, title, disp, err, keys,
    h('button', { class: 'k-btn', onclick: closePad }, tr().cancel)));
  els.stage.append(S.pad); render();
  // Hardware card readers emulate a keyboard: digits followed by Enter.
  S.padKeys = (e) => { if (stage === 'card' ? /^[\w-]$/.test(e.key) : /^\d$/.test(e.key)) key(e.key); else if (e.key === 'Enter') submit(); else if (e.key === 'Escape') closePad(); else if (e.key === 'Backspace') { value = value.slice(0, -1); render(); } };
  window.addEventListener('keydown', S.padKeys);
  const bump = () => { clearTimeout(S.padTimer); S.padTimer = setTimeout(closePad, 20000); };
  bump();
}
function closePad() {
  clearTimeout(S.padTimer); S.pad?.remove(); S.pad = null; S.padCard = null;
  if (S.padKeys) window.removeEventListener('keydown', S.padKeys); S.padKeys = null;
}

async function callHelp() {
  try { showResult(await call('/api/help', { direction: S.direction })); } catch { showResult({ state: 'TRM-13', message: 'Qo\'riqchini chaqiring', duration_ms: 4000 }); }
}

// ---------------------------------------------------------------- boot
function tick() { if (els.clock) els.clock.textContent = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }); }

(async function boot() {
  try { const r = await fetch('/api/status'); if (!r.ok) throw new Error(); S.status = await r.json(); }
  catch { S.demo = true; }
  build(); tick(); setInterval(tick, 1000 * 10);
  await refreshStatus();
  setInterval(refreshStatus, 5000);
  // Card readers emulate keyboards: the first digit opens the card pad.
  window.addEventListener('keydown', (e) => { if (!S.pad && /^\d$/.test(e.key)) { openPad(); S.padKeys(e); } });
  startCamera();
})();
