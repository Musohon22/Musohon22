// SCR-20 … SCR-23: Face enrollment wizard and duplicate-face reviews.
import { h, clear, btn, select, input, field, checkbox, toast, errorText, emptyState, load, badge, kv, confirmDanger } from '/assets/core/ui.js';
import { fmtDateTime } from '/assets/core/format.js';
import { pageHead } from './common.js';

const HINTS = {
  no_face: 'Yuzingizni ramka markaziga keltiring', multiple_faces: 'Kadrda faqat bitta odam bo\'lsin', too_dark: "Yorug'lik yetarli emas",
  too_bright: 'Orqa fon juda yorug\'', uneven_light: "Yorug'lik bir tekis emas", blurry: 'Qimirlamang', too_far: 'Yaqinroq keling', too_close: 'Biroz uzoqlashing',
  turn_to_camera: "To'g'ri qarang", look_straight: "To'g'ri qarang",
};
const CHECKS = [['face', 'Yuz topildi'], ['single', 'Bitta yuz'], ['distance', 'Masofa'], ['angle', 'Burchak'], ['light', "Yorug'lik"], ['sharp', 'Aniqlik (xiralik yo\'q)']];
const POSES = [['front', "To'g'ri qarang"], ['left', 'Boshingizni biroz chapga buring'], ['right', "Boshingizni biroz o'ngga buring"]];
const CHALLENGES = ['Boshingizni sekin chapga buring', "Ko'zingizni qisib qo'ying", 'Boshingizni sekin o\'ngga buring'];

export async function render(main, params, app) {
  let emp;
  try { emp = await app.api.get(`/api/v1/employees/${params.id}`); } catch (e) { main.appendChild(h('div', { class: 'note danger' }, errorText(e))); return; }
  const steps = ['Rozilik', 'Kamera', 'Suratga olish', 'Liveness', 'Natija'];
  let step = 0, stream = null, frames = [], liveFrames = [], polling = null, provider = null;
  try { provider = await app.api.get('/api/v1/biometrics/provider'); } catch { /* optional */ }
  const stepper = h('div', { class: 'stepper', 'aria-label': 'Bosqichlar' });
  const body = h('div');
  const footer = h('div', { class: 'sticky-bar' });
  const consentDone = emp.biometric?.consent?.decision === 'granted';
  main.append(pageHead("Yuzni ro'yxatdan o'tkazish", `${emp.last_name} ${emp.first_name} · ${emp.personnel_no} · ${emp.department_name}`, [], [['Xodimlar', '/employees'], [emp.personnel_no, `/employees/${emp.id}`], ['Enrollment']]),
    provider?.dev ? h('div', { class: 'note warning', style: { marginBottom: '12px' } }, '⚠ DEV biometrik provayder faol: bu haqiqiy yuz tanish emas, faqat sinov uchun. Ishlab chiqarishda ONNX model ulanadi.') : null,
    stepper, body, footer);
  const drawStepper = () => { clear(stepper); steps.forEach((s, i) => stepper.appendChild(h('span', { class: `step ${i === step ? 'active' : i < step ? 'done' : ''}`, 'aria-current': i === step ? 'step' : undefined }, `${i < step ? '✓' : i + 1}. ${s}`))); };
  const stopCamera = () => { clearInterval(polling); polling = null; stream?.getTracks().forEach((t) => t.stop()); stream = null; };
  const cancel = btn('Bekor qilish', { variant: 'tertiary', onClick: async () => {
    if (step > 0 && !window.confirm("Enrollment bekor qilinadi, barcha vaqtinchalik kadrlar o'chiriladi. Davom etasizmi?")) return;
    stopCamera(); frames = []; liveFrames = []; app.go(`/employees/${emp.id}?tab=biometric`);
  } });
  const observer = new MutationObserver(() => { if (!document.body.contains(body)) { stopCamera(); observer.disconnect(); } });
  observer.observe(document.body, { childList: true, subtree: true });

  // -------------------------------------------------- 1. consent
  async function stepConsent() {
    step = 0; drawStepper(); clear(body); clear(footer);
    let policy = null;
    try { policy = await app.api.get('/api/v1/biometrics/policy-text'); } catch { /* shown below */ }
    const lang = select([['uz', "O'zbek"], ['ru', 'Русский']]);
    const text = h('div', { class: 'note', style: { whiteSpace: 'pre-wrap' } }, policy?.text.uz || '—');
    lang.addEventListener('change', () => { text.textContent = policy?.text[lang.value] || ''; });
    const method = select([['paper_scan', "Imzolangan qog'oz shakl (skan)"], ['e_signature', 'Elektron imzo (planshetda)']]);
    const file = h('input', { type: 'file', accept: '.pdf,.jpg,.jpeg,.png', class: 'input', style: { paddingTop: '8px' } });
    const fileField = field({ label: 'Rozilik hujjati (PDF/JPG ≤ 5 MB)', input: file });
    const explained = checkbox('Xodimga siyosat tushuntirildi va savollariga javob berildi');
    const card = input({ placeholder: 'RFID karta №' }), pin = input({ type: 'password', inputmode: 'numeric', placeholder: '4–6 raqam' });
    const altBox = h('div', { class: 'form-grid', hidden: true }, field({ label: 'Karta №', input: card }), field({ label: 'PIN', input: pin }));
    const err = h('div', { class: 'note danger', hidden: true });
    method.addEventListener('change', () => { fileField.hidden = method.value !== 'paper_scan'; });
    body.append(h('div', { class: 'card pad-lg stack' }, h('div', { class: 'row' }, h('h3', { style: { margin: 0, flex: 1 } }, 'Biometrik ma\'lumotlarga rozilik'), field({ label: 'Til', input: lang })),
      text, h('div', { class: 'caption' }, `Siyosat versiyasi: ${policy?.version || '—'}`),
      consentDone ? h('div', { class: 'note success' }, `Rozilik avval qayd etilgan: ${fmtDateTime(emp.biometric.consent.created_at, app.tz)}`) : null,
      field({ label: 'Rasmiylashtirish usuli', input: method }), fileField, explained, altBox, err));
    const readFile = (f) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
    async function submit(decision) {
      err.hidden = true;
      if (!explained.input.checked) { err.hidden = false; err.textContent = 'Siyosat tushuntirilganini tasdiqlang'; return; }
      let document = null;
      if (method.value === 'paper_scan' && decision === 'granted') {
        const f = file.files[0];
        if (!f) { err.hidden = false; err.textContent = 'Imzolangan hujjatni yuklang'; return; }
        if (f.size > 5 * 1024 * 1024) { err.hidden = false; err.textContent = 'Fayl 5 MB dan katta'; return; }
        document = await readFile(f);
      }
      const payload = { employee_id: emp.id, decision, method: method.value, document, explained: true };
      if (decision === 'declined') { payload.method = 'e_signature'; payload.alt_card_no = card.value || null; payload.alt_pin = pin.value || null; }
      try {
        await app.api.post('/api/v1/biometrics/consents', payload);
        if (decision === 'declined') { toast('Rad etish qayd etildi. Muqobil usul biriktirildi.', 'success'); app.go(`/employees/${emp.id}?tab=biometric`); return; }
        stepCamera();
      } catch (e) { err.hidden = false; err.textContent = e.code === 'ALT_METHOD_REQUIRED' ? 'Rad etilganda karta yoki PIN kiritilishi shart' : errorText(e); }
    }
    footer.append(cancel, btn('Xodim rad etdi', { variant: 'secondary', size: 'l', onClick: () => { if (altBox.hidden) { altBox.hidden = false; toast('Muqobil usul uchun karta yoki PIN kiriting va qayta bosing', 'info'); return; } return submit('declined'); } }),
      consentDone ? btn('Davom etish', { size: 'l', onClick: stepCamera }) : null, btn('Rozilikni qayd etish', { size: 'l', onClick: () => submit('granted') }));
  }

  // -------------------------------------------------- 2. camera
  const video = h('video', { autoplay: true, playsinline: true, muted: true });
  const oval = h('div', { class: 'oval' });
  const pill = h('div', { class: 'pill', role: 'status', 'aria-live': 'polite' }, 'Kamera ishga tushmoqda…');
  const camBox = h('div', { class: 'camera' }, video, oval, pill);
  const canvas = h('canvas', { width: 640, height: 480, style: { display: 'none' } });
  async function startCamera(deviceId) {
    stopCamera();
    try { stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId }, width: { ideal: 1280 }, height: { ideal: 720 } } : { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } } }); }
    catch (e) { throw Object.assign(new Error(e.name === 'NotAllowedError' ? 'ENR-E01: Kameraga ruxsat berilmagan. Brauzer sozlamalarida ruxsat bering.' : 'ENR-E02: Kamera topilmadi'), { code: e.name === 'NotAllowedError' ? 'ENR-E01' : 'ENR-E02' }); }
    video.srcObject = stream; await video.play().catch(() => {});
  }
  function grab(w = 640) {
    const vw = video.videoWidth || 640, vh = video.videoHeight || 480;
    canvas.width = w; canvas.height = Math.round((w * vh) / vw);
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.9);
  }
  async function stepCamera() {
    step = 1; drawStepper(); clear(body); clear(footer);
    const camSel = select([['', 'Standart kamera']]);
    const status = h('ul', { class: 'checklist' }, h('li', {}, 'Tekshirilmoqda…'));
    const next = btn('Davom etish', { size: 'l', disabled: true, onClick: stepCapture });
    body.append(h('div', { class: 'split' }, h('div', { class: 'stack' }, camBox), h('div', { class: 'card stack' }, field({ label: 'Kamera', input: camSel }),
      btn('Kamerani tekshirish', { variant: 'secondary', onClick: () => test() }), status, h('div', { class: 'caption' }, 'Talab: ≥ 15 FPS, ≥ 720p tavsiya, bir tekis yorug\'lik'))), canvas);
    footer.append(btn('Orqaga', { variant: 'tertiary', onClick: stepConsent }), cancel, next);
    async function test() {
      clear(status).appendChild(h('li', {}, 'Tekshirilmoqda (3 s)…'));
      try {
        await startCamera(camSel.value || undefined);
        if (camSel.options.length === 1) {
          const cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
          cams.forEach((c, i) => camSel.appendChild(h('option', { value: c.deviceId }, c.label || `Kamera ${i + 1}`)));
        }
        let n = 0; const t0 = performance.now();
        await new Promise((res) => { const tick = () => { n++; if (performance.now() - t0 < 1500) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
        const fps = Math.round(n / 1.5);
        const q = await app.api.post('/api/v1/biometrics/quality', { frame: grab() }, { idempotent: false });
        const res = video.videoHeight;
        clear(status).append(h('li', {}, h('span', { class: fps >= 15 ? 'ok' : 'warn' }, fps >= 15 ? '✓' : '⚠'), `Kadr tezligi ≈ ${fps} FPS`),
          h('li', {}, h('span', { class: res >= 720 ? 'ok' : 'warn' }, res >= 720 ? '✓' : '⚠'), `O'lcham ${video.videoWidth}×${res}`),
          h('li', {}, h('span', { class: q.brightness === undefined || (q.brightness > 60 && q.brightness < 210) ? 'ok' : 'warn' }, '•'), `Yorug'lik: ${q.brightness ?? '—'}`));
        pill.textContent = 'Kamera tayyor'; next.removeAttribute('aria-disabled');
      } catch (e) { clear(status).appendChild(h('li', {}, h('span', { class: 'bad' }, '✕'), e.message)); pill.textContent = e.code || 'Kamera xatosi'; }
    }
    camSel.addEventListener('change', test);
    test();
  }

  // -------------------------------------------------- 3. capture with live guidance
  function checklistFrom(q) {
    const iss = new Set(q.issues || []);
    return { face: q.faces >= 1, single: q.faces === 1, distance: !iss.has('too_far') && !iss.has('too_close'), angle: !iss.has('turn_to_camera') && !iss.has('look_straight'),
      light: !iss.has('too_dark') && !iss.has('too_bright') && !iss.has('uneven_light'), sharp: !iss.has('blurry') };
  }
  async function stepCapture() {
    step = 2; drawStepper(); clear(body); clear(footer); frames = [];
    const list = h('ul', { class: 'checklist' });
    const thumbs = h('div', { class: 'thumbs' });
    const prompt = h('div', { class: 'note' });
    const scoreEl = h('div', { class: 'caption' });
    const shoot = btn('Suratga olish', { size: 'l', disabled: true, onClick: () => take() });
    const next = btn('Davom etish', { size: 'l', disabled: true, onClick: stepLiveness });
    body.append(h('div', { class: 'split' }, camBox, h('div', { class: 'card stack' }, h('h3', {}, 'Sifat tekshiruvi'), list, scoreEl, prompt, h('h3', {}, 'Kadrlar'), thumbs)), canvas);
    footer.append(btn('Orqaga', { variant: 'tertiary', onClick: stepCamera }), cancel, shoot, next);
    if (!stream) { try { await startCamera(); } catch (e) { pill.textContent = e.message; return; } }
    let goodSince = 0, lastHint = 0, busy = false, last = null;
    const pose = () => POSES[Math.min(frames.length, POSES.length - 1)];
    const draw = (q) => {
      const c = checklistFrom(q);
      clear(list); CHECKS.forEach(([k, label]) => list.appendChild(h('li', {}, h('span', { class: c[k] ? 'ok' : 'bad' }, c[k] ? '✓' : '✕'), label)));
      scoreEl.textContent = `Sifat bali: ${Math.round((q.score || 0) * 100)}%`;
      clear(prompt).append(h('strong', {}, `${frames.length + 1}-kadr: `), pose()[1]);
      const ok = q.ok;
      oval.classList.toggle('good', ok);
      if (ok) shoot.removeAttribute('aria-disabled'); else shoot.setAttribute('aria-disabled', 'true');
      if (Date.now() - lastHint > 800) { pill.textContent = ok ? 'Ajoyib, ushlab turing' : HINTS[q.issues?.[0]] || 'Ramkaga qarang'; lastHint = Date.now(); }
      return ok;
    };
    async function take() {
      if (frames.length >= 5) return;
      frames.push(last || grab(960));
      oval.style.borderColor = '#fff'; setTimeout(() => { oval.style.borderColor = ''; }, 300);
      clear(thumbs); frames.forEach((f, i) => thumbs.appendChild(h('div', { class: 't' }, h('img', { src: f, alt: `${i + 1}-kadr` }),
        h('button', { class: 'btn icon', style: { position: 'absolute', top: 0, right: 0, background: 'rgba(0,0,0,.5)', color: '#fff', width: '22px', height: '22px' }, 'aria-label': 'Qayta olish', onclick: () => { frames.splice(i, 1); take.redraw(); } }, '↻'))));
      if (frames.length >= 3) next.removeAttribute('aria-disabled');
      goodSince = 0;
    }
    take.redraw = () => { clear(thumbs); frames.forEach((f, i) => thumbs.appendChild(h('div', { class: 't' }, h('img', { src: f, alt: `${i + 1}-kadr` })))); if (frames.length < 3) next.setAttribute('aria-disabled', 'true'); };
    polling = setInterval(async () => {
      if (busy || !stream) return; busy = true;
      try {
        last = grab(960);
        const q = await app.api.post('/api/v1/biometrics/quality', { frame: last }, { idempotent: false });
        const ok = draw(q);
        if (ok && frames.length < 3) { goodSince ||= Date.now(); if (Date.now() - goodSince > 1000) await take(); } else if (!ok) goodSince = 0;
      } catch (e) { pill.textContent = e.code === 'RATE_LIMITED' ? 'Biroz kuting…' : errorText(e); }
      finally { busy = false; }
    }, 600);
  }

  // -------------------------------------------------- 4. liveness (active challenge, random order)
  async function stepLiveness() {
    step = 3; drawStepper(); clear(body); clear(footer); clearInterval(polling); liveFrames = [];
    const order = [...CHALLENGES].sort(() => Math.random() - 0.5).slice(0, 2);
    const prompt = h('div', { class: 'note', style: { fontSize: '18px', fontWeight: 600 } }, 'Tayyorlaning…');
    const go = btn('Boshlash', { size: 'l', onClick: async () => {
      go.setAttribute('aria-disabled', 'true');
      for (const c of order) { prompt.textContent = c; pill.textContent = c; await new Promise((r) => setTimeout(r, 1200)); liveFrames.push(grab(960)); }
      prompt.textContent = 'Tayyor!'; pill.textContent = 'Tayyor'; stepResult();
    } });
    body.append(h('div', { class: 'split' }, camBox, h('div', { class: 'card stack' }, h('h3', {}, 'Jonlilik tekshiruvi'), h('p', { class: 'muted' }, "Ko'rsatmalarga amal qiling. Topshiriqlar tartibi har safar tasodifiy."), prompt)));
    footer.append(btn('Orqaga', { variant: 'tertiary', onClick: stepCapture }), cancel, go);
  }

  // -------------------------------------------------- 5. result
  async function stepResult() {
    step = 4; drawStepper(); clear(footer);
    clear(body).append(h('div', { class: 'card pad-lg state' }, h('div', { class: 'spin', style: { width: '32px', height: '32px', border: '3px solid var(--c-primary)', borderRightColor: 'transparent', borderRadius: '50%', animation: 'spin .8s linear infinite' } }), h('h3', {}, 'Profil yaratilmoqda…')));
    const all = [...frames, ...liveFrames].slice(0, 6);
    stopCamera();
    try {
      const r = await app.api.post('/api/v1/biometrics/enrollments', { employee_id: emp.id, frames: all });
      frames = []; liveFrames = [];
      clear(body).append(r.status === 'review'
        ? h('div', { class: 'card pad-lg stack' }, h('div', { class: 'note warning' }, h('strong', {}, 'Xavfsizlik tekshiruvi talab qilinadi. '), "Profil terminallarga yuborilmadi; xavfsizlik xodimi ko'rib chiqadi."))
        : h('div', { class: 'card pad-lg stack' }, h('div', { class: 'note success' }, h('strong', {}, '✓ Profil faol. '), r.message), kv([['Sifat', `${Math.round(r.quality * 100)}%`], ['Liveness', r.liveness], ['Model', h('span', { class: 'mono' }, r.model_version)], ['Galereya versiyasi', r.gallery_version]])));
      footer.append(btn('Profilga qaytish', { size: 'l', onClick: () => app.go(`/employees/${emp.id}?tab=biometric`) }));
    } catch (e) {
      const msg = { 'ENR-E20': 'Jonlilik tekshiruvi o\'tmadi. Yorug\'likni tekshiring va qayta urining (urinish xavfsizlik jurnaliga yozildi).', 'ENR-E10': `Kadr sifati yetarli emas: ${e.message}`, 'ENR-E22': 'Biometrik servis mavjud emas. Kadrlar saqlanmadi — qayta urining.', CONSENT_REQUIRED: 'Avval rozilikni qayd eting' }[e.code] || errorText(e);
      clear(body).append(h('div', { class: 'card pad-lg stack' }, h('div', { class: 'note danger' }, h('strong', {}, `${e.code}: `), msg)));
      footer.append(cancel, btn('Qayta urinish', { size: 'l', onClick: stepCapture }));
    }
  }

  if (consentDone) stepCamera(); else stepConsent();
}

// ---------------------------------------------------------------- SCR-22 duplicate face reviews
export async function renderReviews(main, params, app) {
  const box = h('div');
  main.append(pageHead("Dublikat yuzlar", "Yangi profil mavjud profilga juda o'xshash chiqqan holatlar"), box);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/biometrics/reviews'), (r) => (r.items.length ? h('div', { class: 'grid cols-2' }, r.items.map((rv) => h('div', { class: 'card stack' },
      h('div', { class: 'row' }, badge(`O'xshashlik ${(rv.score * 100).toFixed(1)}%`, 'danger'), h('span', { class: 'caption' }, fmtDateTime(rv.created_at, app.tz))),
      h('div', { class: 'grid cols-2' }, h('div', { class: 'card' }, h('div', { class: 'caption' }, 'Yangi profil'), h('strong', {}, `${rv.a_last} ${rv.a_first}`), h('div', { class: 'caption' }, rv.a_no)),
        h('div', { class: 'card' }, h('div', { class: 'caption' }, 'Mavjud profil'), h('strong', {}, `${rv.b_last} ${rv.b_first}`), h('div', { class: 'caption' }, rv.b_no))),
      h('div', { class: 'btn-bar' },
        btn('Turli odamlar', { variant: 'secondary', onClick: () => decide(rv, 'different') }),
        btn('Bir odam', { variant: 'danger', onClick: () => decide(rv, 'same_person') }))))) : emptyState({ icon: '✓', title: "Ko'rib chiqiladigan holat yo'q" })));
  }
  function decide(rv, decision) {
    confirmDanger({ title: decision === 'same_person' ? 'Bir odam deb belgilash' : 'Turli odamlar deb belgilash',
      consequences: decision === 'same_person' ? ['Ikkala profil bloklanadi', 'HR Managerga xodimlarni birlashtirish vazifasi yuboriladi'] : ['Yangi profil faollashadi va terminallarga yuboriladi'],
      reasonMin: 5, reasonLabel: 'Izoh', okLabel: 'Tasdiqlash',
      onConfirm: async ({ reason }) => { await app.api.post(`/api/v1/biometrics/reviews/${rv.id}/decide`, { decision, comment: reason }); toast('Qaror saqlandi', 'success'); refresh(); } });
  }
  await refresh();
}

