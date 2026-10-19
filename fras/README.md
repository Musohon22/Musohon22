# FRAS — yuz orqali davomat tizimi (Face Recognition Attendance System)

Zavodlar uchun davomat: terminal yuzni taniydi, darvozani ochadi, hodisani yozadi; tizim smena qoidalari
bo'yicha tabel hisoblaydi; HR tuzatish, ta'til, e'tiroz va davr yopishni boshqaradi; SaaS egasi mijozlar,
tariflar va to'lovlarni yuritadi. Spetsifikatsiya: Claude Doc'dagi «Texnik va UX/UI spetsifikatsiya» va
«Biznes va monetizatsiya» bo'limlari.

> **Muhim:** repozitoriyda haqiqiy yuz tanish modeli yo'q. `dev` provayderi — test uchun o'rinbosar,
> u yuzni tanimaydi (UI'da «DEV biometrika» belgisi turadi, `FRAS_ENV=prod` da ishga tushmaydi).
> Ishlab chiqarishda ONNX detektor va recognizer modellari beriladi va aniqlik o'z ma'lumotlaringizda
> `scripts/evaluate_biometrics.py` bilan o'lchanadi — hech qanday aniqlik foizi oldindan va'da qilinmaydi.

## Tarkib

| Qism | Yo'l | Nima |
|---|---|---|
| Server (API) | `fras/` | Python 3.13, Starlette, SQLite (WAL; sxema Postgres'ga ko'chiriladigan) |
| Boshqaruv paneli | `web/admin` → `/app/` | HR, rahbarlar, xavfsizlik, administratorlar |
| Xodim portali | `web/portal` → `/me/` | Telefon uchun: davomatim, jadval, ta'til, e'tiroz, rozilik |
| Terminal kiosk | `web/terminal` → edge agentda `/` | Kamera, natija ekranlari, karta/PIN, yordam |
| Platforma paneli | `web/platform` → `/platform/` | SaaS egasi: mijozlar, MRR, fakturalar, qarzdorlik, tiketlar |
| ROI kalkulyatori | `web/public` → `/roi` | Ochiq sahifa, PDF hisobot |
| Edge agent | `edge/fras_edge` | Darvoza yonidagi kompyuter: lokal tanish, rele, oflayn navbat |
| Baholash | `scripts/evaluate_biometrics.py` | FAR/FRR, EER, ishonch oraliqlari, chegara tavsiyasi |

## Tez boshlash (demo)

```bash
pip install -r requirements.txt
export FRAS_DATA_DIR=./data FRAS_DEV_RELAX_MFA=1     # demo: MFA majburiy emas (prod'da taqiqlangan)
python -m fras seed-demo                             # o'ylab topilgan demo zavod, loginlarni chop etadi
python -m fras serve --port 8000
```

Keyin: `http://localhost:8000/app/` (tashkilot kodi `demo`, `admin@demo.uz` / `hr@demo.uz` …,
parol `Demo-Parol-2026`), `/me/` (login `t-1001`), `/platform/` (`owner@fras.local`), `/roi`,
`/terminal/` (serverdan ochilsa DEMO rejim — hech narsa yozilmaydi).

Haqiqiy terminal (edge agent) — demo chiqargan ikkinchi qurilma kodi bilan:

```bash
cd edge
python -m fras_edge --server http://localhost:8000 activate --code <KOD>
python -m fras_edge --server http://localhost:8000 run --port 8100   # kiosk: http://127.0.0.1:8100/
```

## Testlar

```bash
python -m unittest discover -s tests -t .
```

Qamrov: davomat dvigateli (tungi smena, tanaffus, kechikish, qo'shimcha ish, tuzatishlar), qaror mantig'i
(chegara zonasi, liveness, top-2), autentifikatsiya va xavfsizlik (lockout, MFA, refresh rotatsiyasi, CSRF,
RBAC doirasi, maker-checker, audit zanjiri), qurilma imzolari va idempotentlik, oflayn sinxronlash,
biometrik rozilik/ro'yxatdan o'tish/dublikat, billing bosqichlari, baholash skripti.

## Sozlamalar (muhit o'zgaruvchilari)

| O'zgaruvchi | Ma'nosi |
|---|---|
| `FRAS_ENV` | `dev` (standart) yoki `prod` — prod'da kalitlar majburiy, DEV provayder va MFA yumshatish taqiqlanadi |
| `FRAS_SECRET_KEY`, `FRAS_MASTER_KEY` | JWT kaliti; 32 baytli base64 master kalit (tenant DEK'larini o'raydi) |
| `FRAS_DATA_DIR`, `FRAS_DB_PATH` | Ma'lumotlar papkasi va SQLite fayli |
| `FRAS_BIOMETRIC_PROVIDER` | `onnx` yoki `dev` |
| `FRAS_DETECTOR_MODEL`, `FRAS_RECOGNIZER_MODEL`, `FRAS_PAD_MODEL` | ONNX model fayllari (PAD ixtiyoriy) |
| `FRAS_PUBLIC_URL` | Havolalar uchun tashqi manzil |
| `FRAS_TIMEZONE` | «Bugun» chegarasi uchun standart vaqt mintaqasi (`Asia/Tashkent`) |
| `FRAS_SMTP_HOST`, `FRAS_TELEGRAM_BOT_TOKEN` | Bildirishnoma kanallari |
| `FRAS_HEARTBEAT_OFFLINE_S` | Qurilma necha soniyadan so'ng offline hisoblanadi (90) |
| `FRAS_DEV_RELAX_MFA` | Faqat demo/dev: imtiyozli rollar uchun MFA talabini o'chiradi |

## Aniqlikni o'lchash

```bash
python scripts/evaluate_biometrics.py --data photos/enrolled --impostors photos/visitors \
    --detector det.onnx --recognizer rec.onnx --out report
```

`photos/enrolled/<odam>/*.jpg` — har bir odamning birinchi 3 rasmi shablon, qolganlari tekshiruv;
`photos/visitors/` — ro'yxatda yo'q odamlar (ochiq to'plam). Hisobot: FAR/FRR jadvali 95% ishonch
oraliqlari bilan, EER, rank-1, yuz topilmagan rasmlar ulushi va namunaning chegaralari
(masalan, FAR ≤ 1e-4 deyish uchun xatosiz ≥ 30 000 begona taqqoslash kerak). Liveness/PAD bu yerda
baholanmaydi — buning uchun haqiqiy hujum namunalari (bosma rasm, ekran, niqob) kerak.

## Asosiy kafolatlar

- Davomat hodisalari va audit jurnali faqat qo'shiladi (SQLite triggerlari), audit xesh-zanjir bilan.
- Terminal internetsiz ishlaydi; navbat tasdiqlanmaguncha o'chirilmaydi; qayta yuborish dublikat yaratmaydi.
- Chegara zonasidagi natija hech qachon darvozani to'g'ridan-to'g'ri ochmaydi: qayta urinish → karta/PIN → HR ko'rigi.
- Biometrikaga rozilik bermagan xodim uchun muqobil usul majburiy.
- To'lov muammosi davomat yozuvini va terminallarni hech qachon to'xtatmaydi (faqat o'sish/yozish cheklanadi).
