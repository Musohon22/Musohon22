// SCR-75 profile & MFA, SCR-90 notifications.
import { h, clear, btn, input, field, table, toast, emptyState, load, kv, showError, errorText, select } from '/assets/core/ui.js';
import { fmtDateTime, relTime } from '/assets/core/format.js';
import { pageHead, act } from './common.js';

export function mfaSetupBlock(box, onDone) {
  const api = window.__fras_api;
  const start = btn("MFA'ni sozlash", { onClick: async () => {
    try {
      const r = await (api || (await import('../app.js')).app.api).post('/api/v1/me/mfa/setup', {}, { idempotent: false });
      const code = input({ inputmode: 'numeric', maxlength: 6, autofocus: true });
      clear(box).append(h('h2', {}, 'Ikki bosqichli autentifikatsiya'),
        h('ol', {}, h('li', {}, 'Telefoningizda autentifikator ilovasini oching (Google Authenticator, Microsoft Authenticator, Aegis).'),
          h('li', {}, "Hisob qo'shish → kalitni qo'lda kiriting:"), h('li', {}, 'Ilova ko\'rsatgan 6 xonali kodni kiriting.')),
        h('div', { class: 'qr-box' }, r.secret.replace(/(.{4})/g, '$1 ').trim()), h('div', { class: 'caption mono', style: { overflowWrap: 'anywhere' } }, r.otpauth_uri),
        field({ label: 'Kod', input: code }), btn('Yoqish', { onClick: async () => {
          try {
            const res = await (api || (await import('../app.js')).app.api).post('/api/v1/me/mfa/enable', { code: code.value }, { idempotent: false });
            clear(box).append(h('h2', {}, 'MFA yoqildi ✓'), h('div', { class: 'note warning' }, 'Zaxira kodlarini xavfsiz joyda saqlang — har biri bir marta ishlaydi. Qayta ko\'rsatilmaydi.'),
              h('div', { class: 'qr-box', style: { fontSize: '16px', textAlign: 'left' } }, res.backup_codes.join('  ')), btn('Davom etish', { onClick: onDone }));
          } catch (e) { toast(errorText(e), 'error'); }
        } }));
    } catch (e) { toast(errorText(e), 'error'); }
  } });
  clear(box).append(h('h2', {}, 'MFA talab qilinadi'), h('p', { class: 'muted' }, "Rolingiz uchun ikki bosqichli autentifikatsiya majburiy. Bir daqiqada sozlang."), start);
}

export async function render(main, params, app) {
  window.__fras_api = app.api;
  const me = app.me;
  const mfaBox = h('div', { class: 'card stack' });
  const sessBox = h('div');
  main.append(pageHead('Mening profilim'), h('div', { class: 'grid cols-2' },
    h('div', { class: 'card stack' }, h('h3', {}, 'Ma\'lumotlar'), kv([['Ism', me.user.name], ['Login', me.user.login], ['Tashkilot', `${me.tenant.name} (${me.tenant.slug})`], ['Rollar', me.roles.map((r) => `${r.name} · ${r.scope_type}`).join(', ')], ['Tarif', me.plan.name]]),
      field({ label: 'Interfeys tili', input: (() => { const s = select([['uz', "O'zbek"], ['ru', 'Русский'], ['en', 'English']], { value: me.user.language }); s.addEventListener('change', () => act(() => app.api.patch('/api/v1/me', { language: s.value }), 'Saqlandi')); return s; })() }),
      passwordBlock(app)), mfaBox), h('h2', { style: { marginTop: '24px' } }, 'Faol sessiyalarim'), sessBox);
  if (me.user.mfa_enabled) mfaBox.append(h('h3', {}, 'MFA'), h('div', { class: 'note success' }, '✓ Ikki bosqichli autentifikatsiya yoqilgan'), h('div', { class: 'caption' }, "Qurilmani yo'qotsangiz, administrator MFA'ni qayta o'rnatadi."));
  else mfaSetupBlock(mfaBox, () => app.go('/profile'));
  const refresh = () => load(sessBox, () => app.api.get('/api/v1/me/sessions'), (r) => table({ rows: r.items, columns: [
    { key: 'created_at', label: 'Boshlangan', render: (s) => fmtDateTime(s.created_at, app.tz) }, { key: 'ip', label: 'IP' }, { key: 'user_agent', label: 'Brauzer', wrap: true },
    { key: 'x', label: '', render: (s) => (s.current ? h('span', { class: 'badge info' }, 'Joriy') : btn('Chiqarish', { variant: 'tertiary', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/me/sessions/${s.id}/revoke`), 'Sessiya tugatildi')) refresh(); } })) }] }));
  await refresh();
}

function passwordBlock(app) {
  const cur = input({ type: 'password', autocomplete: 'current-password' }), nw = input({ type: 'password', autocomplete: 'new-password' });
  const fc = field({ label: 'Joriy parol', input: cur }), fn = field({ label: 'Yangi parol', input: nw, help: 'Kamida 10 belgi, katta-kichik harf va raqam' });
  return h('div', { class: 'stack' }, h('h3', {}, "Parolni o'zgartirish"), fc, fn, h('div', { class: 'btn-bar' }, btn("O'zgartirish", { variant: 'secondary', onClick: async () => {
    try { await app.api.post('/api/v1/me/password', { current: cur.value, new: nw.value }, { idempotent: false }); toast("Parol o'zgartirildi. Boshqa sessiyalar yopildi.", 'success'); cur.value = nw.value = ''; }
    catch (e) { if (e.code === 'PASSWORD_MISMATCH') fc.setError("Joriy parol noto'g'ri"); else if (e.code === 'PASSWORD_WEAK' || e.status === 422) fn.setError("Parol talabga javob bermaydi"); else showError(e); }
  } })));
}

export async function renderNotifications(main, params, app) {
  const box = h('div');
  main.append(pageHead('Bildirishnomalar', null, [btn("Hammasini o'qildi", { variant: 'secondary', onClick: async () => { await app.api.post('/api/v1/notifications/read-all'); refresh(); } })]), box);
  const refresh = () => load(box, () => app.api.get('/api/v1/notifications'), (r) => (r.items.length ? h('div', { class: 'stack' }, r.items.map((n) => h('a', { class: 'card', href: n.link || '#', 'data-link': n.link ? '' : undefined, style: { display: 'block', color: 'inherit', opacity: n.read_at ? 0.7 : 1 }, onclick: () => app.api.post(`/api/v1/notifications/${n.id}/read`) },
    h('div', { class: 'row' }, h('strong', {}, n.title), h('span', { style: { flex: 1 } }), h('span', { class: 'caption' }, relTime(n.created_at))), h('div', { class: 'muted small' }, n.body)))) : emptyState({ icon: '🔔', title: "Bildirishnoma yo'q" })));
  await refresh();
}
