"""Report definitions and file rendering (XLSX / CSV / PDF)."""

from __future__ import annotations

import csv
import io
from calendar import monthrange
from datetime import date, timedelta

from .. import db as dbm
from ..util import daterange, parse_dt

STATUS_CODE = {"present": "", "late": "K", "absent": "Y", "leave": "T", "off": "D", "holiday": "B",
               "incomplete": "?", "scheduled": "", "business_trip": "XS", "remote": "M"}

CATALOG = [
    {"type": "daily", "group": "attendance", "name": "Kunlik davomat", "perm": "report.view", "params": ["date"]},
    {"type": "timesheet", "group": "attendance", "name": "Oylik tabel", "perm": "report.view", "params": ["month"]},
    {"type": "lateness", "group": "time", "name": "Kechikishlar va erta ketishlar", "perm": "report.view",
     "params": ["from", "to"]},
    {"type": "hours", "group": "time", "name": "Ishlangan soatlar va qo'shimcha ish", "perm": "report.view",
     "params": ["from", "to"]},
    {"type": "absences", "group": "absence", "name": "Yo'qliklar", "perm": "report.view", "params": ["from", "to"]},
    {"type": "departments", "group": "attendance", "name": "Bo'limlar kesimi", "perm": "report.view",
     "params": ["from", "to"]},
    {"type": "anomalies", "group": "attendance", "name": "Anomaliyalar va tuzatishlar", "perm": "report.view",
     "params": ["from", "to"]},
    {"type": "devices", "group": "devices", "name": "Qurilmalar ishlashi", "perm": "device.read", "params": ["from", "to"]},
    {"type": "suspicious", "group": "security", "name": "Shubhali urinishlar", "perm": "alert.read",
     "params": ["from", "to"]},
    {"type": "payroll", "group": "attendance", "name": "Payroll eksporti", "perm": "report.export", "params": ["from", "to"]},
]


def _h(minutes: int) -> str:
    h, m = divmod(int(minutes or 0), 60)
    return f"{h}:{m:02d}"


def _emp_rows(conn, tenant_id: str, scope: tuple[str, list], filters: dict, include_inactive_since: str | None = None):
    sql, params = scope
    where = ["e.tenant_id = ?", sql]
    p = [tenant_id, *params]
    if include_inactive_since:
        where.append("(e.status = 'active' OR e.deactivated_at >= ?)")
        p.append(include_inactive_since)
    else:
        where.append("e.status = 'active'")
    for col in ("site_id", "department_id", "team"):
        if filters.get(col):
            where.append(f"e.{col} = ?")
            p.append(filters[col])
    return dbm.all_(conn, f"SELECT e.id, e.personnel_no, e.last_name, e.first_name, e.team, d.name AS department "
                          f"FROM employees e LEFT JOIN departments d ON d.id = e.department_id WHERE {' AND '.join(where)} "
                          f"ORDER BY d.name, e.last_name", p)


def _summaries(conn, tenant_id: str, ids: list[str], start: str, end: str) -> dict:
    out: dict[str, dict] = {i: {} for i in ids}
    for chunk in range(0, len(ids), 900):
        part = ids[chunk:chunk + 900]
        for s in dbm.all_(conn, f"SELECT * FROM daily_summaries WHERE tenant_id = ? AND work_date BETWEEN ? AND ? AND "
                                f"employee_id IN ({','.join('?' * len(part))})", [tenant_id, start, end, *part]):
            out[s["employee_id"]][s["work_date"]] = s
    return out


def run(conn, tenant_id: str, rtype: str, params: dict, scope: tuple[str, list], tz: str = "Asia/Tashkent") -> dict:
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz)
    loc = lambda v: parse_dt(v).astimezone(zone).strftime("%H:%M") if v else ""  # noqa: E731
    if rtype == "daily":
        day = params.get("date") or date.today().isoformat()
        emps = _emp_rows(conn, tenant_id, scope, params)
        sums = _summaries(conn, tenant_id, [e["id"] for e in emps], day, day)
        cols = ["Tabel №", "F.I.Sh.", "Bo'lim", "Smena", "Kirish", "Chiqish", "Ishlangan", "Kechikish (daq)", "Holat"]
        rows = []
        for e in emps:
            s = sums[e["id"]].get(day)
            rows.append([e["personnel_no"], f"{e['last_name']} {e['first_name']}", e["department"],
                         s["shift_code"] if s else "", loc(s["first_in"]) if s else "", loc(s["last_out"]) if s else "",
                         _h(s["worked_min"]) if s else "", s["late_min"] if s else 0, s["status"] if s else "—"])
        return {"title": f"Kunlik davomat — {day}", "columns": cols, "rows": rows}
    if rtype == "timesheet":
        month = params.get("month") or date.today().strftime("%Y-%m")
        y, m = map(int, month.split("-"))
        start, end = date(y, m, 1), date(y, m, monthrange(y, m)[1])
        emps = _emp_rows(conn, tenant_id, scope, params, include_inactive_since=start.isoformat())
        sums = _summaries(conn, tenant_id, [e["id"] for e in emps], start.isoformat(), end.isoformat())
        days = list(daterange(start, end))
        cols = ["Tabel №", "F.I.Sh.", "Bo'lim"] + [str(d.day) for d in days] + \
               ["Kunlar", "Soat", "Qo'shimcha", "Kechikish", "Yo'q"]
        rows = []
        for e in emps:
            row = [e["personnel_no"], f"{e['last_name']} {e['first_name']}", e["department"]]
            worked = ot = late = absent = present = 0
            for d in days:
                s = sums[e["id"]].get(d.isoformat())
                if not s:
                    row.append("")
                    continue
                code = STATUS_CODE.get(s["status"], s["status"][:2].upper())
                if s["status"] in ("present", "late") or (s["worked_min"] and s["status"] not in ("leave",)):
                    code = (code + " " if code else "") + _h(s["worked_min"])
                    present += 1
                row.append(code)
                worked += s["worked_min"]
                ot += s["overtime_min"]
                late += 1 if s["late_min"] else 0
                absent += 1 if s["status"] == "absent" else 0
            row += [present, _h(worked), _h(ot), late, absent]
            rows.append(row)
        return {"title": f"Oylik tabel — {month}", "columns": cols, "rows": rows,
                "legend": "K — kechikdi, Y — kelmadi, T — ta'til, D — dam olish, B — bayram, ? — anomaliya"}
    start = params.get("from") or (date.today() - timedelta(days=30)).isoformat()
    end = params.get("to") or date.today().isoformat()
    if rtype in ("lateness", "hours", "absences", "payroll", "departments"):
        emps = _emp_rows(conn, tenant_id, scope, params, include_inactive_since=start)
        sums = _summaries(conn, tenant_id, [e["id"] for e in emps], start, end)
        if rtype == "lateness":
            cols = ["Tabel №", "F.I.Sh.", "Bo'lim", "Kechikishlar soni", "Jami kechikish (daq)", "Erta ketishlar",
                    "Jami erta ketish (daq)"]
            rows = []
            for e in emps:
                ss = sums[e["id"]].values()
                late = [s for s in ss if s["late_min"]]
                early = [s for s in ss if s["early_leave_min"]]
                if late or early:
                    rows.append([e["personnel_no"], f"{e['last_name']} {e['first_name']}", e["department"], len(late),
                                 sum(s["late_min"] for s in late), len(early), sum(s["early_leave_min"] for s in early)])
            rows.sort(key=lambda r: -r[4])
            return {"title": f"Kechikishlar {start} — {end}", "columns": cols, "rows": rows}
        if rtype == "hours":
            cols = ["Tabel №", "F.I.Sh.", "Bo'lim", "Ish kunlari", "Ishlangan (soat)", "Qo'shimcha (soat)",
                    "Ishlangan (o'nlik)", "Qo'shimcha (o'nlik)"]
            rows = []
            for e in emps:
                ss = list(sums[e["id"]].values())
                w = sum(s["worked_min"] for s in ss)
                o = sum(s["overtime_min"] for s in ss)
                rows.append([e["personnel_no"], f"{e['last_name']} {e['first_name']}", e["department"],
                             sum(1 for s in ss if s["worked_min"]), _h(w), _h(o), round(w / 60, 2), round(o / 60, 2)])
            return {"title": f"Ishlangan soatlar {start} — {end}", "columns": cols, "rows": rows}
        if rtype == "absences":
            cols = ["Tabel №", "F.I.Sh.", "Bo'lim", "Sana", "Holat", "Izoh"]
            rows = []
            for e in emps:
                for d, s in sorted(sums[e["id"]].items()):
                    if s["status"] in ("absent", "leave", "incomplete"):
                        rows.append([e["personnel_no"], f"{e['last_name']} {e['first_name']}", e["department"], d,
                                     s["status"], s["explanation"]])
            return {"title": f"Yo'qliklar {start} — {end}", "columns": cols, "rows": rows}
        if rtype == "departments":
            agg: dict[str, dict] = {}
            for e in emps:
                a = agg.setdefault(e["department"] or "—", {"emp": 0, "days": 0, "late": 0, "absent": 0, "w": 0, "o": 0})
                a["emp"] += 1
                for s in sums[e["id"]].values():
                    a["days"] += 1 if s["worked_min"] else 0
                    a["late"] += 1 if s["late_min"] else 0
                    a["absent"] += 1 if s["status"] == "absent" else 0
                    a["w"] += s["worked_min"]
                    a["o"] += s["overtime_min"]
            cols = ["Bo'lim", "Xodimlar", "Ish kunlari", "Kechikishlar", "Kelmagan kunlar", "Ishlangan (soat)",
                    "Qo'shimcha (soat)", "Kechikish ulushi %"]
            rows = [[k, v["emp"], v["days"], v["late"], v["absent"], round(v["w"] / 60, 1), round(v["o"] / 60, 1),
                     round(100 * v["late"] / v["days"], 1) if v["days"] else 0] for k, v in sorted(agg.items())]
            return {"title": f"Bo'limlar kesimi {start} — {end}", "columns": cols, "rows": rows}
        # payroll: one line per employee, decimal hours as most payroll systems expect
        cols = ["personnel_no", "full_name", "period_start", "period_end", "days_worked", "hours_worked",
                "overtime_hours", "late_count", "absent_days", "leave_days", "holiday_hours"]
        rows = []
        for e in emps:
            ss = list(sums[e["id"]].values())
            rows.append([e["personnel_no"], f"{e['last_name']} {e['first_name']}", start, end,
                         sum(1 for s in ss if s["worked_min"]), round(sum(s["worked_min"] for s in ss) / 60, 2),
                         round(sum(s["overtime_min"] for s in ss) / 60, 2), sum(1 for s in ss if s["late_min"]),
                         sum(1 for s in ss if s["status"] == "absent"), sum(1 for s in ss if s["status"] == "leave"),
                         round(sum(s["worked_min"] for s in ss if s["status"] == "holiday" or
                                   (s["shift_code"] is None and s["worked_min"])) / 60, 2)])
        return {"title": f"Payroll {start} — {end}", "columns": cols, "rows": rows}
    if rtype == "anomalies":
        sql, p = scope
        rows = dbm.all_(conn, f"SELECT e.personnel_no, e.last_name || ' ' || e.first_name AS name, a.work_date, a.kind, "
                              f"a.status, a.resolved_at FROM anomalies a JOIN employees e ON e.id = a.employee_id WHERE "
                              f"a.tenant_id = ? AND a.work_date BETWEEN ? AND ? AND {sql} ORDER BY a.work_date",
                        [tenant_id, start, end, *p])
        corr = dbm.all_(conn, f"SELECT e.personnel_no, e.last_name || ' ' || e.first_name AS name, c.work_date, c.kind, "
                              f"c.status, c.reason_code FROM corrections c JOIN employees e ON e.id = c.employee_id WHERE "
                              f"c.tenant_id = ? AND c.work_date BETWEEN ? AND ? AND {sql} ORDER BY c.work_date",
                        [tenant_id, start, end, *p])
        return {"title": f"Anomaliyalar va tuzatishlar {start} — {end}",
                "columns": ["Tabel №", "F.I.Sh.", "Sana", "Turi", "Holat", "Izoh"],
                "rows": [[r["personnel_no"], r["name"], r["work_date"], f"anomaly:{r['kind']}", r["status"],
                          r["resolved_at"] or ""] for r in rows] +
                        [[r["personnel_no"], r["name"], r["work_date"], f"correction:{r['kind']}", r["status"],
                          r["reason_code"]] for r in corr]}
    if rtype == "devices":
        rows = dbm.all_(conn, "SELECT d.name, d.type, d.status, d.firmware, d.last_seen_at, "
                              "(SELECT COUNT(*) FROM attendance_events ev WHERE ev.device_id = d.id AND ev.captured_at "
                              "BETWEEN ? AND ?) AS events, (SELECT COUNT(*) FROM attendance_events ev WHERE ev.device_id = "
                              "d.id AND ev.late_arrival = 1 AND ev.captured_at BETWEEN ? AND ?) AS offline_events "
                              "FROM devices d WHERE d.tenant_id = ? ORDER BY d.name",
                        (start, end + "T23:59:59Z", start, end + "T23:59:59Z", tenant_id))
        return {"title": f"Qurilmalar {start} — {end}",
                "columns": ["Qurilma", "Turi", "Holat", "Firmware", "Oxirgi aloqa", "Hodisalar", "Offline'dan kelgan"],
                "rows": [list(r.values()) for r in rows]}
    if rtype == "suspicious":
        rows = dbm.all_(conn, "SELECT ev.captured_at, ev.result, ev.method, d.name AS device, ap.name AS gate, "
                              "r.decision FROM attendance_events ev LEFT JOIN devices d ON d.id = ev.device_id LEFT JOIN "
                              "access_points ap ON ap.id = ev.access_point_id LEFT JOIN event_reviews r ON r.event_id = "
                              "ev.id WHERE ev.tenant_id = ? AND ev.result IN ('pad','unknown','review') AND "
                              "ev.captured_at BETWEEN ? AND ? ORDER BY ev.captured_at DESC",
                        (tenant_id, start, end + "T23:59:59Z"))
        return {"title": f"Shubhali urinishlar {start} — {end}",
                "columns": ["Vaqt (UTC)", "Natija", "Usul", "Qurilma", "Darvoza", "Qaror"],
                "rows": [list(r.values()) for r in rows]}
    raise ValueError(f"unknown report {rtype}")


def render(report: dict, fmt: str, watermark: str) -> tuple[bytes, str, str]:
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow([f"# {report['title']}", watermark])
        w.writerow(report["columns"])
        w.writerows(report["rows"])
        return buf.getvalue().encode("utf-8-sig"), "text/csv", "csv"
    if fmt == "xlsx":
        import xlsxwriter
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {"in_memory": True})
        ws = wb.add_worksheet("report")
        title = wb.add_format({"bold": True, "font_size": 13})
        head = wb.add_format({"bold": True, "bg_color": "#E8EEF8", "border": 1, "text_wrap": True})
        cell = wb.add_format({"border": 1})
        ws.write(0, 0, report["title"], title)
        ws.write(1, 0, watermark)
        if report.get("legend"):
            ws.write(2, 0, report["legend"])
        for i, c in enumerate(report["columns"]):
            ws.write(3, i, c, head)
            ws.set_column(i, i, max(6, min(28, len(str(c)) + 4)))
        for r, row in enumerate(report["rows"], start=4):
            for c, v in enumerate(row):
                ws.write(r, c, v, cell)
        ws.freeze_panes(4, 2)
        ws.set_footer(f"&L{watermark}&R&P/&N")
        wb.close()
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    if fmt == "pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
        buf = io.BytesIO()
        wide = len(report["columns"]) > 9
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4) if wide else A4, leftMargin=24, rightMargin=24,
                                topMargin=28, bottomMargin=28, title=report["title"])
        styles = getSampleStyleSheet()
        data = [report["columns"]] + [[str(v) for v in r] for r in report["rows"][:5000]]
        font = 6 if len(report["columns"]) > 20 else 8
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), font), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF8")),
                                   ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))

        def footer(canvas, d):
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.drawString(24, 14, watermark)
            canvas.drawRightString(d.pagesize[0] - 24, 14, f"{d.page}")
            canvas.restoreState()
        story = [Paragraph(report["title"], styles["Heading3"])]
        if report.get("legend"):
            story.append(Paragraph(report["legend"], styles["BodyText"]))
        story.append(table)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return buf.getvalue(), "application/pdf", "pdf"
    raise ValueError("format")
