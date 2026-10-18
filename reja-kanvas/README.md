# Reja Kanvas

Rejalarni ekranning istalgan joyiga kartochka qilib joylash, Word kabi yozish va bajarilganini rasman tasdiqlash uchun ilova.

- **frontend/** — Next.js 14 (App Router), TypeScript, Tailwind CSS, TipTap muharriri
- **backend/** — Python (Starlette + Pydantic), SQLite, JWT

## Ishga tushirish

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
python -m unittest discover tests      # 40 ta test
```

Muhit o'zgaruvchilari (hammasi ixtiyoriy):

| O'zgaruvchi | Standart qiymat | Vazifasi |
|---|---|---|
| `REJA_DATA_DIR` | `backend/data` | Baza, yuklangan fayllar va zaxira nusxalar |
| `REJA_SECRET_KEY` | tasodifiy, `data/secret.key` ga saqlanadi | JWT imzosi |
| `REJA_FRONTEND_ORIGINS` | `http://localhost:3000` | CORS uchun ruxsat etilgan manzillar (vergul bilan) |

Har kuni zaxira nusxa olish uchun: `python -m scripts.backup` (cron orqali). Oxirgi 14 ta nusxa saqlanadi; `data/uploads` papkasini alohida nusxalang.

### Frontend

```bash
cd frontend
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                     # http://localhost:3000
```

## Ekranlar

| Sahifa | Nima bor |
|---|---|
| `/canvas` | Cheksiz kanvas, "Bugun / Ertaga / Shu hafta / Keyinroq" zonalari, sudrash, qidiruv, mini-xarita, "Tartibga solish", bugungi progress va seriya |
| `/plan/:id` | Word'ga o'xshash hujjat (sarlavha, maqsad, mezon, bosqichlar, formatlangan matn) va 3 qadamli tasdiqlash paneli, tarix |
| `/calendar` | Oylik kalendar, kunni tanlab tez qo'shish |
| `/analytics` | Bajarilganlar, vaqtida bajarish ulushi, seriya, teglar va vaqt sarfi |
| Ctrl/Cmd+K | Buyruqlar paneli: "ertaga 15:00 uchrashuv #ish !yuqori" kabi gapdan reja yaratish, qidiruv |
| `/list` | Xuddi shu rejalar oddiy ro'yxat ko'rinishida (klaviatura va ekran o'quvchilar uchun qulay) |
| `/inbox` | Tasdig'ingizni kutayotgan rejalar va bildirishnomalar |
| `/trash` | 30 kunlik savatcha |
| `/settings` | Ism, til (o'zbek lotin/kirill, rus, ingliz), vaqt mintaqasi |
| `/s/:token` | Ulashilgan havola (faqat ko'rish yoki tahrirlash) |

## Kutilmagan holatlar va ularning yechimi

| Holat | Yechim | Qayerda |
|---|---|---|
| Xato bosib tasdiqlab yubordi | 10 soniyalik "Bekor qilish", keyin ham "Qayta ochish"; har biri tarixga yoziladi | `workflow.reopen`, `lib/actions.ts` |
| Bosqich endi kerak emas | "Kerak emas" holati: progressga kirmaydi, tasdiqni to'smaydi | `steps.status = cancelled` |
| Muddat o'tib bajarildi | Muhr "KECHIKIB BAJARILDI", necha daqiqa/soat kechikkani saqlanadi | `late_minutes` |
| Tasdiqlovchi javob bermayapti | 24 soatda eslatma, 48 soatda zaxira tasdiqlovchiga o'tadi, egasiga xabar boradi | `workflow.run_jobs` (har daqiqada) |
| Tasdiqlovchi rad etdi | "Qaytarildi" holati va sabab; tuzatib qayta yuborish mumkin | `workflow.reject` |
| Fayl katta yoki noto'g'ri | 20 MB, faqat PDF/JPG/PNG/WEBP, fayl ichi kengaytmasiga mosligi tekshiriladi | `attachments.py` |
| Huquqi yo'q odam | Hamma tekshiruv serverda; begona odam rejani umuman ko'rmaydi (404) | `plans.load_for` |
| Karta ekrandan "yo'qolib" qoldi | Mini-xarita, "Moslash", qidiruv kartaga uchib boradi | `Canvas.tsx` |
| Kartalar ustma-ust tushdi | 20 px to'rga yopishish, "Tartibga solish" muddat bo'yicha ustunlarga teradi | `lib/canvas.ts` |
| 300+ karta | Faqat ko'rinib turgan kartalar chiziladi, uzoqdan soddalashtirilgan ko'rinish | `Canvas.tsx` |
| Telefonda aylantirmoqchi edi, karta siljib ketdi | Telefonda sudrash uchun bosib turish kerak, oddiy surish kanvasni aylantiradi | `Canvas.tsx` |
| Sichqonchasiz foydalanuvchi | Tab bilan tanlash, strelkalar bilan surish, Enter ochadi, Space bajaradi; Ro'yxat ko'rinishi | `Canvas.tsx`, `/list` |
| Internet uzildi | O'zgarishlar navbatga yoziladi (localStorage), ulanganda tartib bilan yuboriladi; banner holatni ko'rsatadi | `lib/store.ts` |
| Server o'chib qoldi | Xuddi shu navbat, har 15 soniyada qayta urinish | `lib/store.ts` |
| Ikki qurilmada bir vaqtda tahrir | Har xil maydonlar avtomatik birlashadi; bir xil maydon bo'lsa, foydalanuvchi har biri uchun tanlaydi | `plans.apply_patch`, `ConflictDialog.tsx` |
| Oflayn yaratilgan reja ikki marta yuborildi | Reja id'sini mijoz yaratadi, server takrorni tanib qaytaradi | `plans.create` |
| Xato o'chirdi | 10 soniyalik "Bekor qilish" va 30 kunlik savatcha | `deletePlan`, `/trash` |
| Word'dan nusxa qo'ydi | Word uslublari tozalanadi, rasmlar olib tashlanib, ogohlantirish chiqadi | `Editor.tsx` |
| Matnda zararli kod | Server HTML'ni oq ro'yxat bo'yicha tozalaydi | `sanitize.py` |
| Ko'p reja to'planib qoldi | Kuniga bir marta: "Bugunga / Sana / Bekor qilish", ayblovsiz matn | `OverdueDialog.tsx` |
| Bir kun o'tkazib yubordi | Haftasiga 1 ta "dam olish kuni" seriyani saqlab qoladi | `stats.streak` |
| Boshqa vaqt mintaqasiga o'tdi | Vaqt UTC'da saqlanadi; kun chegarasi foydalanuvchi mintaqasida hisoblanadi | `timeutil.py`, `lib/time.ts` |
| Birinchi kirish | Shablonlar (Ish haftasi, Talaba, Sport, Oila) va 3 ta maslahat | `EmptyState.tsx` |
| Ulashilgan havola begonaga tushdi | Muddatli havolalar, istalgan payt bekor qilinadi; havola egasining pochtasi va fayllarini ko'rsatmaydi | `shares.py` |
| Parolni taxmin qilish | 15 daqiqada 10 ta xato urinishdan keyin bloklanadi | `security.LoginLimiter` |
| Kirill va lotinda qidirish | "режа" "reja"ni topadi | `translit.py`, `lib/search.ts` |

## Tekshirilgan va tekshirilmagan qismlar

- **Backend**: 40 ta avtomatik test o'tadi (`python -m unittest discover tests`), server ishga tushirilib, qo'lda ham tekshirildi.
- **Frontend**: bu muhitda npm registriga kirish yo'q edi, shuning uchun `npm install` va `next build` ishga tushirilmagan. Kod React, Next va TipTap uchun vaqtinchalik tur zaglushkalari bilan TypeScript'da tekshirildi, sof mantiq (vaqt mintaqalari, kirillga o'girish, qidiruv, avtomatik tartiblash) Node'da sinab ko'rildi. Birinchi `npm install && npm run build` da kichik tur xatolari chiqishi mumkin.

## Keyingi bosqichlar

To'liq funksiyalar katalogi (nima tayyor, nima keyingi navbatda): [FEATURES.md](FEATURES.md).
