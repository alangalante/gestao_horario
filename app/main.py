from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .calculations import cycle_bounds, format_minutes, month_dates, worked_minutes
from .database import BASE_DIR, UPLOAD_DIR, connection, get_setting, init_db, punches_from_row
from .parser import PDFParseError, parse_timesheet


app = FastAPI(title="Meu Ponto", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


WEEKDAY_NAMES = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


@app.on_event("startup")
def startup() -> None:
    init_db()


def redirect_with(message: str, kind: str = "success", month: Optional[str] = None) -> RedirectResponse:
    month_query = f"month={month}&" if month and len(month) == 7 and month[4] == "-" else ""
    return RedirectResponse(f"/?{month_query}message={quote(message)}&kind={kind}", status_code=303)


def dashboard_context(request: Request) -> dict:
    today = date.today()
    requested_month = request.query_params.get("month")
    try:
        selected_year, selected_month = map(int, requested_month.split("-")) if requested_month else (today.year, today.month)
    except (ValueError, AttributeError):
        selected_year, selected_month = today.year, today.month

    with connection() as conn:
        schedules = {row["weekday"]: row["expected_minutes"] for row in conn.execute("SELECT * FROM schedule")}
        holidays = {
            row["holiday_date"]: row["name"]
            for row in conn.execute("SELECT holiday_date, name FROM holidays")
        }
        holiday_rows = conn.execute(
            "SELECT * FROM holidays ORDER BY holiday_date DESC"
        ).fetchall()
        employees = conn.execute("SELECT * FROM employees ORDER BY id").fetchall()
        employee = employees[0] if employees else None
        imports = conn.execute(
            """SELECT imports.*, employees.name AS employee_name
               FROM imports JOIN employees ON employees.id = imports.employee_id
               ORDER BY imports.id DESC LIMIT 10"""
        ).fetchall()
        rows = []
        monthly_worked = 0
        monthly_expected_to_date = 0
        monthly_expected_full = 0
        incomplete_count = 0
        attendance = {}
        if employee:
            start = f"{selected_year:04d}-{selected_month:02d}-01"
            end = f"{selected_year:04d}-{selected_month:02d}-31"
            attendance = {
                row["work_date"]: row
                for row in conn.execute(
                    "SELECT * FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
                    (employee["id"], start, end),
                )
            }

        for current in month_dates(selected_year, selected_month):
            record = attendance.get(current.isoformat())
            punches = punches_from_row(record) if record else []
            worked = worked_minutes(punches)
            holiday_name = holidays.get(current.isoformat())
            expected = 0 if holiday_name else schedules.get(current.weekday(), 0)
            is_closed = current <= today
            incomplete = len(punches) % 2 == 1
            monthly_worked += worked
            monthly_expected_full += expected
            if is_closed:
                monthly_expected_to_date += expected
            if incomplete:
                incomplete_count += 1
            balance = worked - expected if is_closed else None
            rows.append(
                {
                    "date": current,
                    "weekday": WEEKDAY_NAMES[current.weekday()],
                    "punches": punches,
                    "worked": format_minutes(worked),
                    "expected": format_minutes(expected),
                    "balance": format_minutes(balance, True) if balance is not None else "—",
                    "balance_value": balance,
                    "incomplete": incomplete,
                    "future": not is_closed,
                    "holiday": holiday_name,
                }
            )

        anchor = int(get_setting(conn, "cycle_anchor_month", "1"))
        opening = int(get_setting(conn, "opening_balance_minutes", "0"))
        cycle_start, cycle_end = cycle_bounds(today, anchor)
        cycle_worked = 0
        if employee:
            cycle_rows = conn.execute(
                "SELECT * FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
                (employee["id"], cycle_start.isoformat(), min(today, cycle_end).isoformat()),
            ).fetchall()
            cycle_worked = sum(worked_minutes(punches_from_row(row)) for row in cycle_rows)
        cycle_expected = 0
        cursor = cycle_start
        while cursor <= min(today, cycle_end):
            if cursor.isoformat() not in holidays:
                cycle_expected += schedules.get(cursor.weekday(), 0)
            cursor = date.fromordinal(cursor.toordinal() + 1)

        month_options = set()
        for imported in imports:
            month_options.add((imported["reference_year"], imported["reference_month"]))
        month_options.add((selected_year, selected_month))

        # Semanas completas (segunda a domingo) que cruzam o mês selecionado.
        first_month_day = date(selected_year, selected_month, 1)
        last_month_day = list(month_dates(selected_year, selected_month))[-1]
        first_week_start = first_month_day - timedelta(days=first_month_day.weekday())
        last_week_start = last_month_day - timedelta(days=last_month_day.weekday())
        weekly_attendance = {}
        if employee:
            weekly_attendance = {
                row["work_date"]: row
                for row in conn.execute(
                    "SELECT * FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
                    (
                        employee["id"],
                        first_week_start.isoformat(),
                        (last_week_start + timedelta(days=6)).isoformat(),
                    ),
                )
            }
        weekly_status = []
        week_start = first_week_start
        while week_start <= last_week_start:
            week_end = week_start + timedelta(days=6)
            display_start = max(week_start, first_month_day)
            display_end = min(week_end, last_month_day)
            week_worked = 0
            week_expected_to_date = 0
            week_expected_full = 0
            week_incomplete = 0
            current = display_start
            while current <= display_end:
                expected = 0 if current.isoformat() in holidays else schedules.get(current.weekday(), 0)
                week_expected_full += expected
                if current <= today:
                    week_expected_to_date += expected
                record = weekly_attendance.get(current.isoformat())
                punches = punches_from_row(record) if record else []
                week_worked += worked_minutes(punches)
                if len(punches) % 2:
                    week_incomplete += 1
                current += timedelta(days=1)
            has_started = display_start <= today
            week_balance = week_worked - week_expected_to_date if has_started else None
            weekly_status.append(
                {
                    "start": display_start,
                    "end": display_end,
                    "worked": format_minutes(week_worked),
                    "expected": format_minutes(week_expected_to_date),
                    "target": format_minutes(week_expected_full),
                    "balance": format_minutes(week_balance, True) if week_balance is not None else "—",
                    "balance_value": week_balance,
                    "current": week_start <= today <= week_end,
                    "future": not has_started,
                    "incomplete": week_incomplete,
                }
            )
            week_start += timedelta(days=7)

        return {
            "request": request,
            "today": today,
            "employee": employee,
            "rows": rows,
            "imports": imports,
            "schedules": schedules,
            "weekday_names": WEEKDAY_NAMES,
            "selected_month": f"{selected_year:04d}-{selected_month:02d}",
            "month_options": sorted(month_options, reverse=True),
            "worked_total": format_minutes(monthly_worked),
            "expected_to_date": format_minutes(monthly_expected_to_date),
            "month_balance": format_minutes(monthly_worked - monthly_expected_to_date, True),
            "month_balance_value": monthly_worked - monthly_expected_to_date,
            "projection": format_minutes(monthly_worked - monthly_expected_full, True),
            "incomplete_count": incomplete_count,
            "weekly_total": format_minutes(sum(schedules.values())),
            "cycle_anchor": anchor,
            "opening_balance": opening,
            "opening_balance_display": format_minutes(opening, True),
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "cycle_balance": format_minutes(opening + cycle_worked - cycle_expected, True),
            "cycle_balance_value": opening + cycle_worked - cycle_expected,
            "weekly_status": weekly_status,
            "holidays": holiday_rows,
            "message": request.query_params.get("message"),
            "message_kind": request.query_params.get("kind", "success"),
        }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=dashboard_context(request),
    )


@app.post("/settings")
def save_settings(
    cycle_anchor_month: int = Form(...),
    opening_balance_hours: int = Form(0),
    opening_balance_minutes: int = Form(0),
    opening_balance_sign: int = Form(1),
    monday: int = Form(0),
    tuesday: int = Form(0),
    wednesday: int = Form(0),
    thursday: int = Form(0),
    friday: int = Form(0),
    saturday: int = Form(0),
    sunday: int = Form(0),
):
    values = [monday, tuesday, wednesday, thursday, friday, saturday, sunday]
    if not 1 <= cycle_anchor_month <= 12 or any(value < 0 or value > 24 * 60 for value in values):
        return redirect_with("Configuração inválida.", "error")
    opening = opening_balance_sign * (abs(opening_balance_hours) * 60 + abs(opening_balance_minutes))
    with connection() as conn:
        for weekday, minutes in enumerate(values):
            conn.execute("UPDATE schedule SET expected_minutes = ? WHERE weekday = ?", (minutes, weekday))
        conn.execute("UPDATE settings SET value = ? WHERE key = 'cycle_anchor_month'", (str(cycle_anchor_month),))
        conn.execute("UPDATE settings SET value = ? WHERE key = 'opening_balance_minutes'", (str(opening),))
    return redirect_with("Jornada e ciclo salvos.")


@app.post("/holidays")
def save_holiday(
    holiday_date: str = Form(...),
    name: str = Form(...),
    return_month: Optional[str] = Form(None),
):
    try:
        parsed_date = date.fromisoformat(holiday_date)
    except ValueError:
        return redirect_with("Data de feriado inválida.", "error", return_month)
    clean_name = " ".join(name.split())
    if not clean_name or len(clean_name) > 100:
        return redirect_with("Informe um nome de feriado com até 100 caracteres.", "error", return_month)
    with connection() as conn:
        conn.execute(
            """INSERT INTO holidays(holiday_date, name) VALUES (?, ?)
               ON CONFLICT(holiday_date) DO UPDATE SET name = excluded.name""",
            (parsed_date.isoformat(), clean_name),
        )
    return redirect_with(f"Feriado de {parsed_date.strftime('%d/%m/%Y')} salvo.", month=return_month)


@app.post("/holidays/{holiday_date}/delete")
def delete_holiday(holiday_date: str, return_month: Optional[str] = Form(None)):
    try:
        parsed_date = date.fromisoformat(holiday_date)
    except ValueError:
        return redirect_with("Data de feriado inválida.", "error", return_month)
    with connection() as conn:
        conn.execute("DELETE FROM holidays WHERE holiday_date = ?", (parsed_date.isoformat(),))
    return redirect_with(f"Feriado de {parsed_date.strftime('%d/%m/%Y')} removido.", "info", return_month)


@app.post("/imports")
async def import_pdf(file: UploadFile = File(...), mode: str = Form("update")):
    if mode not in {"update", "add_only"}:
        return redirect_with("Modo de importação inválido.", "error")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return redirect_with("Selecione um arquivo PDF.", "error")

    content = await file.read()
    if not content.startswith(b"%PDF"):
        return redirect_with("O arquivo enviado não parece ser um PDF válido.", "error")
    digest = hashlib.sha256(content).hexdigest()
    temp_path = UPLOAD_DIR / f".{digest}.tmp.pdf"
    temp_path.write_bytes(content)
    try:
        parsed = parse_timesheet(temp_path)
    except (PDFParseError, Exception) as exc:
        temp_path.unlink(missing_ok=True)
        message = str(exc) if isinstance(exc, PDFParseError) else "Não foi possível processar o PDF."
        return redirect_with(message, "error")

    with connection() as conn:
        employee = conn.execute("SELECT * FROM employees WHERE cpf = ?", (parsed.cpf,)).fetchone()
        if not employee:
            cursor = conn.execute("INSERT INTO employees(name, cpf) VALUES (?, ?)", (parsed.name, parsed.cpf))
            employee_id = cursor.lastrowid
        else:
            employee_id = employee["id"]
            conn.execute("UPDATE employees SET name = ? WHERE id = ?", (parsed.name, employee_id))

        duplicate = conn.execute(
            "SELECT id FROM imports WHERE employee_id = ? AND sha256 = ?",
            (employee_id, digest),
        ).fetchone()
        if duplicate:
            temp_path.unlink(missing_ok=True)
            return redirect_with("Este mesmo PDF já havia sido importado.", "info")

        stored_name = f"{parsed.year:04d}-{parsed.month:02d}_{digest[:12]}.pdf"
        cursor = conn.execute(
            """INSERT INTO imports(employee_id, original_name, stored_name, sha256,
               reference_year, reference_month, mode) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (employee_id, file.filename, stored_name, digest, parsed.year, parsed.month, mode),
        )
        import_id = cursor.lastrowid
        inserted = updated = unchanged = 0
        for day in parsed.days:
            punches_json = json.dumps(day.punches)
            existing = conn.execute(
                "SELECT * FROM attendance WHERE employee_id = ? AND work_date = ?",
                (employee_id, day.work_date.isoformat()),
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO attendance(employee_id, work_date, weekday_label,
                       punches_json, source_import_id) VALUES (?, ?, ?, ?, ?)""",
                    (employee_id, day.work_date.isoformat(), day.weekday_label, punches_json, import_id),
                )
                inserted += 1
            elif existing["punches_json"] == punches_json or mode == "add_only":
                unchanged += 1
            else:
                conn.execute(
                    "INSERT INTO attendance_versions(attendance_id, import_id, punches_json) VALUES (?, ?, ?)",
                    (existing["id"], import_id, existing["punches_json"]),
                )
                conn.execute(
                    """UPDATE attendance SET punches_json = ?, weekday_label = ?,
                       source_import_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                    (punches_json, day.weekday_label, import_id, existing["id"]),
                )
                updated += 1
        conn.execute(
            "UPDATE imports SET inserted_days = ?, updated_days = ?, unchanged_days = ? WHERE id = ?",
            (inserted, updated, unchanged, import_id),
        )
        final_path = UPLOAD_DIR / stored_name
        shutil.move(str(temp_path), final_path)

    return RedirectResponse(
        f"/?month={parsed.year:04d}-{parsed.month:02d}&message={quote(f'Importação concluída: {inserted} incluídos, {updated} atualizados e {unchanged} sem alteração.')}&kind=success",
        status_code=303,
    )

