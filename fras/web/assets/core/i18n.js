// Minimal i18n: Uzbek (Latin) is the source language; Russian translations for shared UI strings.
const RU = {
  'Dashboard': 'Панель', 'Xodimlar': 'Сотрудники', 'Davomat': 'Посещаемость', 'Davomat jurnali': 'Журнал посещаемости',
  'Tabel': 'Табель', 'Anomaliyalar': 'Аномалии', 'Tasdiqlar': 'Согласования', 'Davrlar': 'Периоды', 'Smenalar': 'Смены',
  'Jadval': 'График', 'Kalendar': 'Календарь', "Ta'tillar": 'Отпуска', 'Hisobotlar': 'Отчёты', 'Qurilmalar': 'Устройства',
  'Xavfsizlik': 'Безопасность', 'Foydalanuvchilar': 'Пользователи', 'Rollar': 'Роли', 'Sessiyalar': 'Сессии',
  'Audit log': 'Журнал аудита', 'Ogohlantirishlar': 'Оповещения', 'Sozlamalar': 'Настройки', 'Saqlash': 'Сохранить',
  'Bekor qilish': 'Отмена', 'Yangilash': 'Обновить', 'Eksport': 'Экспорт', 'Import': 'Импорт', 'Qidirish': 'Поиск',
  'Tozalash': 'Сбросить', 'Tasdiqlash': 'Подтвердить', 'Rad etish': 'Отклонить', 'Yopish': 'Закрыть', 'Orqaga': 'Назад',
  'Davom etish': 'Продолжить', 'Kirish': 'Вход', 'Chiqish': 'Выход', 'Parol': 'Пароль', 'Tashkilot kodi': 'Код организации',
  'Login': 'Логин', 'Qayta urinish': 'Повторить', 'Hammasi': 'Все', 'Faol': 'Активные', 'Kelganlar': 'Пришли',
  'Kechikkanlar': 'Опоздали', 'Hozir ishda': 'Сейчас на работе', 'Kelmaganlar': 'Не пришли', "Ta'til/kasal": 'Отпуск/больничный',
  "Ma'lumot topilmadi": 'Данные не найдены', 'Yuklanmoqda…': 'Загрузка…', 'Server xatosi': 'Ошибка сервера',
  "Xodim qo'shish": 'Добавить сотрудника', 'Profil': 'Профиль', 'Bildirishnomalar': 'Уведомления',
}
let lang = (() => { try { return localStorage.getItem('fras.lang') || 'uz'; } catch { return 'uz'; } })();

export const t = (s) => (lang === 'ru' && RU[s]) || s;
export const getLang = () => lang;
export function setLang(l) { lang = l; try { localStorage.setItem('fras.lang', l); } catch { /* ignore */ } document.documentElement.lang = l; }
