#!/usr/bin/env python3
"""
Сервер для виджетов зарплатных счётчиков.
Запуск: python app.py
Открыть: http://127.0.0.1:5001
"""
from datetime import datetime, date
from zoneinfo import ZoneInfo
from flask import Flask, render_template, jsonify, request

MSK = ZoneInfo("Europe/Moscow")

from schedule import (
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
    "startedAt": None,
    "schedule": "5x2",
    "workFrom": "09:00",
    "workTo": "17:00",
    "lunchFrom": "13:00",
    "lunchTo": "14:00",
    "lunchEnabled": True,
    "daySchedules": None,
    "rate": 0,
    "rateUnit": "month",
    "taxType": "none",
}

TAX_MULT = {"none": 1.0, "13": 0.87, "4": 0.96, "6": 0.94, "15": 0.85}


def parse_job(data: dict) -> dict:
    j = {**DEFAULTS, **data}
    j["rate"] = float(j.get("rate") or 0)
    return j


def to_monthly_net(job: dict, total_sec_month: float, now: datetime) -> float:
    """Перевести ставку в месячную чистую зарплату."""
    rate = job["rate"]
    if rate <= 0:
        return 0
    tax = TAX_MULT.get(str(job.get("taxType", "none")), 1.0)
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


def api_earned_single(job: dict, now: datetime) -> dict:
    job = parse_job(job)
    started_at = None
    if job.get("startedAt"):
        try:
            started_at = datetime.fromisoformat(str(job["startedAt"]).replace("Z", "")).date()
        except Exception:
            pass

    wf = job.get("workFrom") or "09:00"
    wt = job.get("workTo") or "17:00"
    lf = job.get("lunchFrom") or "13:00"
    lt = job.get("lunchTo") or "14:00"
    le = job.get("lunchEnabled", True) not in (False, "false", 0)
    ds = job.get("daySchedules") or None
    sched = job.get("schedule") or "5x2"
    work_status = work_status_now(now.date(), now.hour, now.minute, wf, wt, lf, lt, sched, started_at, le, ds)

    if job["rate"] <= 0:
        return {"earned": 0, "earned_day": 0, "earned_week": 0, "earned_month": 0, "earned_year": 0,
                "earned_gross_day": 0, "earned_gross_week": 0, "earned_gross_month": 0, "earned_gross_year": 0,
                "is_working_now": work_status == "working", "work_status": work_status}

    total_sec = working_seconds_in_month(now.year, now.month, sched, started_at, wf, wt, lf, lt, le, ds)
    salary = to_monthly_net(job, total_sec, now)

    elapsed_sec = working_seconds_elapsed_in_month(
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        sched, started_at, wf, wt, lf, lt, le, ds
    )

    if total_sec <= 0:
        earned_month = 0
    else:
        earned_month = salary * (elapsed_sec / total_sec)

    y, mo, d = now.year, now.month, now.day
    h, mi, s = now.hour, now.minute, now.second
    today = now.date()
    wfd, wtd, lfd, ltd, led = get_day_times(wf, wt, lf, lt, le, ds, today, sched)
    sec_day = elapsed_in_day(h, mi, s, wfd, wtd, lfd, ltd, led)
    earned_day = salary * (sec_day / total_sec) if total_sec > 0 else 0

    sec_week = working_seconds_elapsed_in_week(y, mo, d, h, mi, s, sched, started_at, wf, wt, lf, lt, le, ds)
    earned_week = salary * (sec_week / total_sec) if total_sec > 0 else 0

    total_year = working_seconds_in_year(y, sched, started_at, wf, wt, lf, lt, le, ds)
    sec_year = working_seconds_elapsed_in_year(y, mo, d, h, mi, s, sched, started_at, wf, wt, lf, lt, le, ds)
    earned_year = 12 * salary * (sec_year / total_year) if total_year > 0 else 0

    tax_mult = TAX_MULT.get(str(job.get("taxType", "none")), 1.0)
    gross_mult = 1.0 / tax_mult if tax_mult > 0 else 1.0

    return {
        "earned": round(earned_month, 2),
        "earned_day": round(earned_day, 2),
        "earned_week": round(earned_week, 2),
        "earned_month": round(earned_month, 2),
        "earned_year": round(earned_year, 2),
        "earned_gross_day": round(earned_day * gross_mult, 2),
        "earned_gross_week": round(earned_week * gross_mult, 2),
        "earned_gross_month": round(earned_month * gross_mult, 2),
        "earned_gross_year": round(earned_year * gross_mult, 2),
        "is_working_now": work_status == "working",
        "work_status": work_status,
    }


app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


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
    app.run(host="127.0.0.1", port=5001, debug=True)
