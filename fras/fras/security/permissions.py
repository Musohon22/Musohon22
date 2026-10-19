"""Role → permission matrix (spec section D.2).

Permissions are granted per role; *scope* comes from the user's role
assignment (global / site / department / team / self). A permission held
through several roles gets the union of their scopes.

"Masked" access in the spec is modelled by NOT holding
`employee.read_sensitive`: the API then strips PINFL, phone, birth date.
"Request" vs "approve" are distinct permissions so maker-checker can be
enforced independently of roles.
"""

from __future__ import annotations

ALL_PERMISSIONS = {
    "org.read": "Tashkiliy tuzilmani ko'rish",
    "org.manage": "Tashkiliy tuzilmani boshqarish",
    "employee.read": "Xodimlarni ko'rish",
    "employee.read_sensitive": "Shaxsiy maydonlarni ko'rish (PINFL, telefon)",
    "employee.write": "Xodim yaratish/tahrirlash",
    "employee.deactivate": "Xodimni deaktivatsiya qilish",
    "employee.import": "Xodimlarni import qilish",
    "employee.export": "Xodimlarni eksport qilish",
    "employee.merge": "Takroriy xodimlarni birlashtirish",
    "biometric.read": "Biometrik holatni ko'rish",
    "biometric.enroll": "Yuzni ro'yxatdan o'tkazish",
    "biometric.revoke": "Biometrik profilni bekor qilish",
    "biometric.review": "Dublikat yuzlarni ko'rib chiqish",
    "attendance.read": "Davomat hodisalarini ko'rish",
    "attendance.capture_view": "Shubhali hodisa kadrini ko'rish",
    "attendance.verify": "Shubhali hodisani tasdiqlash/rad etish",
    "correction.request": "Tuzatish so'rovi yaratish",
    "correction.approve": "Tuzatishni tasdiqlash",
    "period.close": "Davrni yopish",
    "period.reopen": "Davrni qayta ochish",
    "shift.manage": "Smena shablonlarini boshqarish",
    "shift.assign": "Smena biriktirish",
    "calendar.manage": "Bayram kalendarini boshqarish",
    "leave.request": "Ta'til so'rovi yaratish",
    "leave.approve": "Ta'tilni tasdiqlash",
    "report.view": "Hisobotlarni ko'rish",
    "report.export": "Hisobotlarni eksport qilish",
    "device.read": "Qurilmalarni ko'rish",
    "device.manage": "Qurilmalarni boshqarish",
    "device.restart": "Qurilmani qayta yuklash",
    "device.open_gate": "Turniketni masofadan ochish",
    "user.manage": "Foydalanuvchilarni boshqarish",
    "role.read": "Rollarni ko'rish",
    "role.manage": "Rollarni boshqarish",
    "session.revoke": "Sessiyalarni bekor qilish",
    "audit.read": "Audit logni ko'rish",
    "audit.export": "Audit logni eksport qilish",
    "alert.read": "Xavfsizlik ogohlantirishlarini ko'rish",
    "alert.manage": "Ogohlantirishlarni boshqarish",
    "settings.read": "Sozlamalarni ko'rish",
    "settings.attendance_rules": "Davomat qoidalarini o'zgartirish",
    "settings.biometric_policy": "Biometrik siyosatni o'zgartirish",
    "settings.retention": "Saqlash muddatlarini o'zgartirish",
    "settings.notifications": "Bildirishnoma sozlamalari",
    "integration.manage": "Integratsiyalar va API kalitlari",
    "backup.manage": "Backup va tiklash",
    "billing.read": "Obuna va hisob-fakturalarni ko'rish",
    "billing.manage": "Obunani boshqarish",
    "self.read": "O'z ma'lumotlarini ko'rish",
    "self.request": "O'z nomidan so'rov yuborish",
}

_READ_BASE = {"org.read", "attendance.read", "report.view", "employee.read"}

SYSTEM_ROLES: dict[str, dict] = {
    "super_admin": {
        "name": "Super Admin",
        "mfa": True,
        "permissions": {
            "org.read", "org.manage", "employee.read", "attendance.read", "report.view",
            "device.read", "device.manage", "device.restart", "device.open_gate",
            "user.manage", "role.read", "role.manage", "session.revoke", "audit.read",
            "alert.read", "settings.read", "settings.biometric_policy", "settings.retention",
            "settings.notifications", "integration.manage", "backup.manage",
            "billing.read", "billing.manage", "biometric.read",
        },
    },
    "site_admin": {
        "name": "Zavod administratori",
        "mfa": True,
        "permissions": {
            "org.read", "org.manage", "employee.read", "attendance.read", "report.view",
            "device.read", "device.manage", "device.restart", "device.open_gate",
            "user.manage", "role.read", "session.revoke", "audit.read", "alert.read",
            "settings.read", "calendar.manage", "biometric.read", "billing.read",
        },
    },
    "hr_manager": {
        "name": "HR Manager",
        "mfa": True,
        "permissions": _READ_BASE | {
            "employee.read_sensitive", "employee.write", "employee.deactivate", "employee.import",
            "employee.export", "employee.merge", "biometric.read", "biometric.enroll", "biometric.revoke",
            "correction.request", "correction.approve", "period.close", "period.reopen",
            "shift.manage", "shift.assign", "calendar.manage", "leave.request", "leave.approve",
            "report.export", "audit.read", "settings.read", "settings.attendance_rules",
            "settings.notifications",
        },
    },
    "hr_operator": {
        "name": "HR Operator",
        "mfa": False,
        "permissions": _READ_BASE | {
            "employee.read_sensitive", "employee.write", "employee.import", "biometric.read",
            "biometric.enroll", "correction.request", "shift.assign", "leave.request",
            "report.export", "settings.read",
        },
    },
    "shift_lead": {
        "name": "Smena boshlig'i",
        "mfa": False,
        "permissions": _READ_BASE | {"correction.request", "leave.request", "biometric.read"},
    },
    "dept_head": {
        "name": "Bo'lim boshlig'i",
        "mfa": False,
        "permissions": _READ_BASE | {
            "correction.request", "correction.approve", "shift.assign", "leave.approve",
            "report.export", "biometric.read",
        },
    },
    "security": {
        "name": "Xavfsizlik xodimi",
        "mfa": True,
        "permissions": _READ_BASE | {
            "biometric.read", "biometric.enroll", "biometric.review", "attendance.capture_view",
            "attendance.verify", "device.read", "device.restart", "device.open_gate",
            "audit.read", "alert.read", "alert.manage",
        },
    },
    "auditor": {
        "name": "Auditor",
        "mfa": True,
        "permissions": _READ_BASE | {
            "report.export", "device.read", "audit.read", "audit.export", "alert.read",
            "settings.read", "role.read", "biometric.read", "billing.read",
        },
    },
    "employee": {
        "name": "Xodim",
        "mfa": False,
        "permissions": {"self.read", "self.request"},
    },
}

# Roles a site admin may hand out (cannot create super admins).
SITE_ADMIN_GRANTABLE = set(SYSTEM_ROLES) - {"super_admin"}

PLATFORM_ROLES = {
    "owner": {"platform.*"},
    "billing": {"platform.read", "platform.billing"},
    "success": {"platform.read", "platform.tenants", "platform.support"},
    "support": {"platform.read", "platform.support"},
    "security": {"platform.read", "platform.audit"},
}


def platform_can(role: str, perm: str) -> bool:
    granted = PLATFORM_ROLES.get(role, set())
    return "platform.*" in granted or perm in granted


def role_requires_mfa(role_code: str, custom_roles: dict | None = None) -> bool:
    if role_code in SYSTEM_ROLES:
        return SYSTEM_ROLES[role_code]["mfa"]
    return False
