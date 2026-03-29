#!/usr/bin/env python3
"""
Сервер для виджетов зарплатных счётчиков.
Запуск: python app.py
Открыть: http://127.0.0.1:5001
"""
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import json
import os
from urllib.request import urlopen, Request
from flask import Flask, render_template, jsonify, request, send_from_directory

MSK = ZoneInfo("Europe/Moscow")

from schedule import (
    is_working_day,
    working_seconds_in_month,
    working_days_in_month,
    working_seconds_in_year,
    working_seconds_elapsed_in_month,
    working_seconds_elapsed_in_week,
    working_seconds_elapsed_in_year,
    elapsed_in_day,
    work_seconds_per_day,
    is_working_now,
    work_status_now,
    get_day_times,
)

# Дефолты для обратной совместимости
DEFAULTS = {
    "name": "Работа",
    "employer": "",
    "startedAt": None,
    "schedule": "5x2",
    "workFrom": "09:00",
    "workTo": "17:00",
    "lunchFrom": "13:00",
    "lunchTo": "14:00",
    "lunchEnabled": True,
    "daySchedules": None,
    "vacations": [],
    "rate": 0,
    "rateUnit": "month",
    "taxType": "none",
    "taxRate": 0.0,
    "currency": "RUB",
    "calendarCountry": "RU",
    "calendarOverrides": [],
    "calendar": None,
}

TAX_MULT = {"none": 1.0, "13": 0.87, "4": 0.96, "6": 0.94, "15": 0.85}


def parse_tax_rate(entity: dict) -> float:
    """Поддержка нового taxRate и обратная совместимость со старым taxType."""
    if "taxRate" in entity and entity.get("taxRate") not in (None, ""):
        try:
            return max(0.0, min(100.0, float(entity.get("taxRate") or 0.0)))
        except Exception:
            pass
    tax_type = str(entity.get("taxType", "none"))
    if tax_type == "none":
        return 0.0
    try:
        return max(0.0, min(100.0, float(tax_type)))
    except Exception:
        pass
    mult = TAX_MULT.get(tax_type, 1.0)
    return max(0.0, min(100.0, (1.0 - mult) * 100.0))


def tax_multiplier(entity: dict) -> float:
    return max(0.0, 1.0 - (parse_tax_rate(entity) / 100.0))


def parse_job(data: dict) -> dict:
    j = {**DEFAULTS, **data}
    j["rate"] = float(j.get("rate") or 0)
    payouts = j.get("payouts")
    if not isinstance(payouts, list):
        payouts = []
    normalized_payouts = []
    for p in payouts:
        if not isinstance(p, dict):
            continue
        normalized_payouts.append({
            "title": str(p.get("title") or ""),
            "kind": str(p.get("kind") or "other"),
            "amount": float(p.get("amount") or 0),
            "taxType": str(p.get("taxType") or "none"),
            "taxRate": float(p.get("taxRate") or 0),
            "schedule": str(p.get("schedule") or ""),
            "fromDate": str(p.get("fromDate") or ""),
            "toDate": str(p.get("toDate") or ""),
            "hidden": bool(p.get("hidden")),
        })
    j["payouts"] = normalized_payouts
    vacations = j.get("vacations")
    if not isinstance(vacations, list):
        vacations = []
    normalized_vacations = []
    for v in vacations:
        if not isinstance(v, dict):
            continue
        normalized_vacations.append({
            "title": str(v.get("title") or ""),
            "fromDate": str(v.get("fromDate") or ""),
            "toDate": str(v.get("toDate") or ""),
        })
    j["vacations"] = normalized_vacations
    j["taxRate"] = float(j.get("taxRate") or 0)
    j["currency"] = str(j.get("currency") or "RUB").upper()
    j["calendarCountry"] = str(j.get("calendarCountry") or "RU").upper()
    overrides = j.get("calendarOverrides")
    if not isinstance(overrides, list):
        overrides = []
    normalized_overrides = []
    for o in overrides:
        if not isinstance(o, dict):
            continue
        normalized_overrides.append({
            "date": str(o.get("date") or ""),
            "type": str(o.get("type") or "off"),
        })
    j["calendarOverrides"] = normalized_overrides
    calendar = j.get("calendar")
    if not isinstance(calendar, dict):
        calendar = {}
    j["calendar"] = {
        "offDates": list(calendar.get("offDates") or []),
        "workDates": list(calendar.get("workDates") or []),
    }
    return j


def to_monthly_net(job: dict, total_sec_month: float, now: datetime) -> float:
    """Перевести ставку в месячную чистую зарплату."""
    rate = job["rate"]
    if rate <= 0:
        return 0
    tax = tax_multiplier(job)
    unit = job.get("rateUnit") or "month"
    sched = job.get("schedule") or "5x2"
    started_at = None
    if job.get("startedAt"):
        try:
            started_at = datetime.fromisoformat(str(job["startedAt"]).replace("Z", "")).date()
        except Exception:
            pass

    if unit == "month":
        gross = rate
    elif unit == "day":
        days = working_days_in_month(now.year, now.month, sched, started_at)
        gross = rate * days
    elif unit == "hour":
        gross = rate * (total_sec_month / 3600)
    else:
        gross = rate

    return gross * tax


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(raw[:10])
    except Exception:
        return None


def seconds_to_hms(total_seconds: int) -> tuple[int, int, int]:
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return h, m, s


def working_seconds_between(start_dt: datetime, end_dt: datetime, schedule: str, started_at: date | None,
                            work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                            lunch_enabled: bool = True, day_schedules: dict | None = None,
                            excluded_dates: set[date] | None = None,
                            calendar_data: dict | None = None) -> float:
    if end_dt <= start_dt:
        return 0.0
    total = 0.0
    cur = start_dt.date()
    end_date = end_dt.date()
    while cur <= end_date:
        if is_working_day(cur, schedule, started_at, calendar_data) and (not excluded_dates or cur not in excluded_dates):
            wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, cur, schedule)
            start_sec = 0
            end_sec = 24 * 3600
            if cur == start_dt.date():
                start_sec = start_dt.hour * 3600 + start_dt.minute * 60 + start_dt.second
            if cur == end_dt.date():
                end_sec = end_dt.hour * 3600 + end_dt.minute * 60 + end_dt.second
            if end_sec > start_sec:
                sh, sm, ss = seconds_to_hms(start_sec)
                eh, em, es = seconds_to_hms(end_sec)
                sec_start = elapsed_in_day(sh, sm, ss, wf, wt, lf, lt, le)
                sec_end = elapsed_in_day(eh, em, es, wf, wt, lf, lt, le)
                total += max(0.0, sec_end - sec_start)
        cur += timedelta(days=1)
    return total


def vacation_days(job: dict) -> set[date]:
    days: set[date] = set()
    for v in job.get("vacations", []):
        start = parse_iso_date(v.get("fromDate"))
        end = parse_iso_date(v.get("toDate"))
        if not start or not end or end < start:
            continue
        cur = start
        while cur <= end:
            days.add(cur)
            cur += timedelta(days=1)
    return days


def payout_ranges(now: datetime) -> dict[str, tuple[datetime, datetime]]:
    day_start = datetime(now.year, now.month, now.day, 0, 0, 0)
    week_start_date = now.date() - timedelta(days=now.weekday())
    week_start = datetime(week_start_date.year, week_start_date.month, week_start_date.day, 0, 0, 0)
    month_start = datetime(now.year, now.month, 1, 0, 0, 0)
    year_start = datetime(now.year, 1, 1, 0, 0, 0)
    return {
        "day": (day_start, now),
        "week": (week_start, now),
        "month": (month_start, now),
        "year": (year_start, now),
    }


def payout_amounts(job: dict, now: datetime, started_at: date | None) -> dict[str, tuple[float, float]]:
    wf = job.get("workFrom") or "09:00"
    wt = job.get("workTo") or "17:00"
    lf = job.get("lunchFrom") or "13:00"
    lt = job.get("lunchTo") or "14:00"
    le = job.get("lunchEnabled", True) not in (False, "false", 0)
    ds = job.get("daySchedules") or None
    base_sched = job.get("schedule") or "5x2"
    calendar_data = job.get("calendar") or None
    ranges = payout_ranges(now)
    totals_net = {"day": 0.0, "week": 0.0, "month": 0.0, "year": 0.0}
    totals_gross = {"day": 0.0, "week": 0.0, "month": 0.0, "year": 0.0}

    for payout in job.get("payouts", []):
        if payout.get("hidden"):
            continue
        amount = float(payout.get("amount") or 0)
        if amount <= 0:
            continue
        from_date = parse_iso_date(payout.get("fromDate"))
        to_date = parse_iso_date(payout.get("toDate"))
        if not from_date or not to_date or to_date < from_date:
            continue
        payout_sched = payout.get("schedule") or base_sched
        # Не начислять выплату за дни до даты устройства (совпадает с is_working_day + started_at).
        eff_from = from_date
        if started_at and started_at > eff_from:
            eff_from = started_at
        eff_to = to_date
        if eff_from > eff_to:
            continue
        period_start = datetime(eff_from.year, eff_from.month, eff_from.day, 0, 0, 0)
        period_end = datetime(eff_to.year, eff_to.month, eff_to.day, 23, 59, 59)
        earned_until = min(now, period_end)
        if earned_until <= period_start:
            continue
        total_sec = working_seconds_between(period_start, period_end, payout_sched, started_at, wf, wt, lf, lt, le, ds, None, calendar_data)
        if total_sec <= 0:
            continue
        tax_mult = tax_multiplier(payout)
        net_amount = amount * tax_mult
        gross_amount = amount

        for key, (range_start, range_end) in ranges.items():
            overlap_start = max(range_start, period_start)
            overlap_end = min(range_end, earned_until)
            if overlap_end <= overlap_start:
                continue
            overlap_sec = working_seconds_between(overlap_start, overlap_end, payout_sched, started_at, wf, wt, lf, lt, le, ds, None, calendar_data)
            if overlap_sec <= 0:
                continue
            ratio = overlap_sec / total_sec
            totals_net[key] += net_amount * ratio
            totals_gross[key] += gross_amount * ratio

    return {
        "day": (totals_net["day"], totals_gross["day"]),
        "week": (totals_net["week"], totals_gross["week"]),
        "month": (totals_net["month"], totals_gross["month"]),
        "year": (totals_net["year"], totals_gross["year"]),
    }


def api_earned_single(job: dict, now: datetime) -> dict:
    job = parse_job(job)
    started_at = None
    if job.get("startedAt"):
        try:
            started_at = parse_iso_date(str(job["startedAt"]))
        except Exception:
            pass

    wf = job.get("workFrom") or "09:00"
    wt = job.get("workTo") or "17:00"
    lf = job.get("lunchFrom") or "13:00"
    lt = job.get("lunchTo") or "14:00"
    le = job.get("lunchEnabled", True) not in (False, "false", 0)
    ds = job.get("daySchedules") or None
    calendar_data = job.get("calendar") or None
    vac_days = vacation_days(job)
    sched = job.get("schedule") or "5x2"
    work_status = work_status_now(now.date(), now.hour, now.minute, wf, wt, lf, lt, sched, started_at, le, ds, calendar_data)
    if now.date() in vac_days and is_working_day(now.date(), sched, started_at, calendar_data):
        work_status = "vacation"

    if job["rate"] <= 0:
        payout_parts = payout_amounts(job, now.replace(tzinfo=None), started_at)
        return {
            "earned": round(payout_parts["month"][0], 2),
            "earned_day": round(payout_parts["day"][0], 2),
            "earned_week": round(payout_parts["week"][0], 2),
            "earned_month": round(payout_parts["month"][0], 2),
            "earned_year": round(payout_parts["year"][0], 2),
            "earned_gross_day": round(payout_parts["day"][1], 2),
            "earned_gross_week": round(payout_parts["week"][1], 2),
            "earned_gross_month": round(payout_parts["month"][1], 2),
            "earned_gross_year": round(payout_parts["year"][1], 2),
            "is_working_now": work_status == "working",
            "work_status": work_status,
        }

    total_sec_full = working_seconds_in_month(now.year, now.month, sched, started_at, wf, wt, lf, lt, le, ds, calendar_data)
    month_start = datetime(now.year, now.month, 1, 0, 0, 0)
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1, 0, 0, 0) - timedelta(seconds=1)
    else:
        month_end = datetime(now.year, now.month + 1, 1, 0, 0, 0) - timedelta(seconds=1)
    total_sec = working_seconds_between(month_start, month_end, sched, started_at, wf, wt, lf, lt, le, ds, vac_days, calendar_data)
    salary_full = to_monthly_net(job, total_sec_full, now)
    # Отпуск уменьшает месячную "стоимость месяца", а не ускоряет счётчик.
    salary = salary_full * (total_sec / total_sec_full) if total_sec_full > 0 else 0

    elapsed_sec = working_seconds_between(month_start, now.replace(tzinfo=None), sched, started_at, wf, wt, lf, lt, le, ds, vac_days, calendar_data)

    if total_sec <= 0:
        earned_month = 0
    else:
        earned_month = salary * (elapsed_sec / total_sec)

    y, mo, d = now.year, now.month, now.day
    today = now.date()
    day_start = datetime(y, mo, d, 0, 0, 0)
    sec_day = working_seconds_between(day_start, now.replace(tzinfo=None), sched, started_at, wf, wt, lf, lt, le, ds, vac_days, calendar_data)
    earned_day = salary * (sec_day / total_sec) if total_sec > 0 else 0

    week_start_date = today - timedelta(days=today.weekday())
    week_start = datetime(week_start_date.year, week_start_date.month, week_start_date.day, 0, 0, 0)
    sec_week = working_seconds_between(week_start, now.replace(tzinfo=None), sched, started_at, wf, wt, lf, lt, le, ds, vac_days, calendar_data)
    earned_week = salary * (sec_week / total_sec) if total_sec > 0 else 0

    year_start = datetime(y, 1, 1, 0, 0, 0)
    year_end = datetime(y + 1, 1, 1, 0, 0, 0) - timedelta(seconds=1)
    total_year = working_seconds_between(year_start, year_end, sched, started_at, wf, wt, lf, lt, le, ds, vac_days, calendar_data)
    sec_year = working_seconds_between(year_start, now.replace(tzinfo=None), sched, started_at, wf, wt, lf, lt, le, ds, vac_days, calendar_data)
    earned_year = 12 * salary * (sec_year / total_year) if total_year > 0 else 0

    tax_mult = tax_multiplier(job)
    gross_mult = 1.0 / tax_mult if tax_mult > 0 else 1.0

    payout_parts = payout_amounts(job, now.replace(tzinfo=None), started_at)
    total_day = earned_day + payout_parts["day"][0]
    total_week = earned_week + payout_parts["week"][0]
    total_month = earned_month + payout_parts["month"][0]
    total_year = earned_year + payout_parts["year"][0]
    total_gross_day = earned_day * gross_mult + payout_parts["day"][1]
    total_gross_week = earned_week * gross_mult + payout_parts["week"][1]
    total_gross_month = earned_month * gross_mult + payout_parts["month"][1]
    total_gross_year = earned_year * gross_mult + payout_parts["year"][1]

    return {
        "earned": round(total_month, 2),
        "earned_day": round(total_day, 2),
        "earned_week": round(total_week, 2),
        "earned_month": round(total_month, 2),
        "earned_year": round(total_year, 2),
        "earned_gross_day": round(total_gross_day, 2),
        "earned_gross_week": round(total_gross_week, 2),
        "earned_gross_month": round(total_gross_month, 2),
        "earned_gross_year": round(total_gross_year, 2),
        "is_working_now": work_status == "working",
        "work_status": work_status,
    }


app = Flask(__name__)
HOLIDAY_CACHE: dict[tuple[str, int], list[str]] = {}


def parse_metrika_id(value: str | None) -> int | None:
    try:
        return int(str(value or "").strip())
    except Exception:
        return None


@app.route("/")
@app.route("/index.html")
def index():
    return render_template(
        "index.html",
        yandex_metrika_id=parse_metrika_id(os.getenv("YANDEX_METRIKA_ID")),
    )


@app.route("/sw.js")
def service_worker():
    # Serve SW from site root so it can control "/" scope for full offline PWA.
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/api/holidays", methods=["GET"])
def api_holidays():
    country = str(request.args.get("country") or "RU").upper()
    year = int(request.args.get("year") or datetime.now(MSK).year)
    key = (country, year)
    if key in HOLIDAY_CACHE:
        return jsonify({"offDates": HOLIDAY_CACHE[key], "source": "cache"})
    try:
        url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
        req = Request(url, headers={"User-Agent": "zp-widget/1.0"})
        with urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        off_dates = sorted({str(x.get("date")) for x in data if isinstance(x, dict) and x.get("date")})
        HOLIDAY_CACHE[key] = off_dates
        return jsonify({"offDates": off_dates, "source": "api"})
    except Exception:
        # Fallback-safe: если API недоступен — возвращаем пустой список,
        # и клиент/движок используют стандартный пн-пт график + ручные overrides.
        HOLIDAY_CACHE[key] = []
        return jsonify({"offDates": [], "source": "fallback"})


@app.route("/api/earned", methods=["POST"])
def api_earned():
    """
    Рассчитать заработанную сумму.
    Body: { "salary": 150000 } — для обратной совместимости
    или полный объект job с полями: name, startedAt, schedule, workFrom, workTo,
    lunchFrom, lunchTo, rate, rateUnit, taxType
    """
    data = request.get_json() or {}
    now = datetime.now(MSK)

    # Обратная совместимость: только salary
    if "salary" in data and "rate" not in data:
        data = {"rate": data["salary"], "rateUnit": "month", "taxType": "none"}

    result = api_earned_single(data, now)
    return jsonify(result)


@app.route("/api/earned_batch", methods=["POST"])
def api_earned_batch():
    """Рассчитать для нескольких работ. Body: { "jobs": [...] }"""
    data = request.get_json() or {}
    jobs = data.get("jobs", [])
    now = datetime.now(MSK)
    results = [api_earned_single(j, now) for j in jobs]
    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
