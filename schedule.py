"""
Расчёт рабочих секунд с учётом графика, времени работы и обеда.
"""
from datetime import date

from calendar_ru import is_working_day as is_ru_working_day


def parse_time(s: str) -> tuple[int, int]:
    """'09:00' -> (9, 0), '17:30' -> (17, 30)"""
    if not s:
        return 9, 0
    parts = str(s).strip().split(':')
    h = int(parts[0]) if parts else 9
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def time_to_seconds(h: int, m: int) -> int:
    return h * 3600 + m * 60


def is_working_day(d: date, schedule: str, started_at: date | None) -> bool:
    """
    Является ли дата рабочим днём.
    schedule: 5x2, 2x2, 3x1, 1x1, 6x1, 24x7
    started_at: дата устройства (для сменных графиков)
    """
    if started_at and d < started_at:
        return False

    if schedule == "24x7":
        return True

    if schedule == "5x2":
        return is_ru_working_day(d)

    if schedule in ("2x2", "3x1", "1x1", "6x1") and started_at:
        days_since = (d - started_at).days
        if days_since < 0:
            return False

        if schedule == "2x2":
            return (days_since % 4) in (0, 1)
        if schedule == "3x1":
            return (days_since % 4) in (0, 1, 2)
        if schedule == "1x1":
            return (days_since % 2) == 0
        if schedule == "6x1":
            return d.weekday() < 6  # пн-сб

    return is_ru_working_day(d)


def work_seconds_per_day(work_from: str, work_to: str, lunch_from: str, lunch_to: str, lunch_enabled: bool = True) -> float:
    """Рабочих секунд в одном дне. lunch_enabled=False — обед не вычитается."""
    h1, m1 = parse_time(work_from)
    h2, m2 = parse_time(work_to)
    start = time_to_seconds(h1, m1)
    end = time_to_seconds(h2, m2)
    total = end - start
    if lunch_enabled:
        l1, lm1 = parse_time(lunch_from)
        l2, lm2 = parse_time(lunch_to)
        lunch_s = time_to_seconds(l1, lm1)
        lunch_e = time_to_seconds(l2, lm2)
        if lunch_s < end and lunch_e > start:
            overlap = min(lunch_e, end) - max(lunch_s, start)
            total -= max(0, overlap)
    return float(total)


def elapsed_in_day(h: int, m: int, s: int, work_from: str, work_to: str, lunch_from: str, lunch_to: str, lunch_enabled: bool = True) -> float:
    """Рабочих секунд с начала дня до (h, m, s)."""
    sec = h * 3600 + m * 60 + s
    start = time_to_seconds(*parse_time(work_from))
    end = time_to_seconds(*parse_time(work_to))
    work_per_day = work_seconds_per_day(work_from, work_to, lunch_from, lunch_to, lunch_enabled)

    if sec <= start:
        return 0
    if not lunch_enabled:
        return min(sec - start, work_per_day) if sec <= end else work_per_day
    lunch_s = time_to_seconds(*parse_time(lunch_from))
    lunch_e = time_to_seconds(*parse_time(lunch_to))
    if sec <= lunch_s:
        return sec - start
    if sec <= lunch_e:
        return lunch_s - start
    if sec <= end:
        return (lunch_s - start) + (sec - lunch_e)
    return work_per_day


def working_days_in_month(year: int, month: int, schedule: str, started_at: date | None) -> int:
    from datetime import timedelta
    count = 0
    d = date(year, month, 1)
    while d.month == month:
        if is_working_day(d, schedule, started_at):
            count += 1
        d += timedelta(days=1)
    return count


def get_day_times(wf: str, wt: str, lf: str, lt: str, le: bool, day_schedules: dict | None, d: date, sched: str) -> tuple:
    """Для 5x2 и day_schedules возвращает (wf, wt, lf, lt, le) для даты d. Для 24x7 — круглосуточно."""
    if sched == "24x7":
        return "00:00", "24:00", "13:00", "14:00", False
    if day_schedules and sched == "5x2" and d.weekday() < 5:
        s = day_schedules.get(str(d.weekday())) or day_schedules.get(d.weekday())
        if s:
            return (
                s.get("workFrom", wf), s.get("workTo", wt),
                s.get("lunchFrom", lf), s.get("lunchTo", lt),
                s.get("lunchEnabled", le) if "lunchEnabled" in s else le,
            )
    return wf, wt, lf, lt, le


def working_seconds_in_month(year: int, month: int, schedule: str, started_at: date | None,
                            work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                            lunch_enabled: bool = True, day_schedules: dict | None = None) -> float:
    from datetime import timedelta
    total = 0.0
    d = date(year, month, 1)
    while d.month == month:
        if is_working_day(d, schedule, started_at):
            wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, d, schedule)
            total += work_seconds_per_day(wf, wt, lf, lt, le)
        d += timedelta(days=1)
    return total


def working_seconds_elapsed_in_month(year: int, month: int, day: int, hour: int, minute: int, second: int,
                                      schedule: str, started_at: date | None,
                                      work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                                      lunch_enabled: bool = True, day_schedules: dict | None = None) -> float:
    from datetime import timedelta
    total = 0.0
    d = date(year, month, 1)
    today = date(year, month, day)

    while d < today:
        if is_working_day(d, schedule, started_at):
            wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, d, schedule)
            total += work_seconds_per_day(wf, wt, lf, lt, le)
        d += timedelta(days=1)

    if not is_working_day(today, schedule, started_at):
        return total

    wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, today, schedule)
    total += elapsed_in_day(hour, minute, second, wf, wt, lf, lt, le)
    return total


def working_seconds_elapsed_in_day(hour: int, minute: int, second: int,
                                   work_from: str, work_to: str, lunch_from: str, lunch_to: str, lunch_enabled: bool = True) -> float:
    return elapsed_in_day(hour, minute, second, work_from, work_to, lunch_from, lunch_to, lunch_enabled)


def working_seconds_in_week(year: int, month: int, day: int, schedule: str, started_at: date | None,
                            work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                            lunch_enabled: bool = True, day_schedules: dict | None = None) -> float:
    from datetime import timedelta
    d = date(year, month, day)
    week_start = d - timedelta(days=d.weekday())
    week_end = week_start + timedelta(days=6)
    total = 0.0
    cur = week_start
    while cur <= week_end:
        if is_working_day(cur, schedule, started_at):
            wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, cur, schedule)
            total += work_seconds_per_day(wf, wt, lf, lt, le)
        cur += timedelta(days=1)
    return total


def working_seconds_elapsed_in_week(year: int, month: int, day: int, hour: int, minute: int, second: int,
                                     schedule: str, started_at: date | None,
                                     work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                                     lunch_enabled: bool = True, day_schedules: dict | None = None) -> float:
    from datetime import timedelta
    d = date(year, month, day)
    week_start = d - timedelta(days=d.weekday())
    today = date(year, month, day)
    total = 0.0
    cur = week_start
    while cur < today:
        if is_working_day(cur, schedule, started_at):
            wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, cur, schedule)
            total += work_seconds_per_day(wf, wt, lf, lt, le)
        cur += timedelta(days=1)
    if is_working_day(today, schedule, started_at):
        wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, today, schedule)
        total += elapsed_in_day(hour, minute, second, wf, wt, lf, lt, le)
    return total


def working_seconds_in_year(year: int, schedule: str, started_at: date | None,
                            work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                            lunch_enabled: bool = True, day_schedules: dict | None = None) -> float:
    from datetime import timedelta
    total = 0.0
    d = date(year, 1, 1)
    while d.year == year:
        if is_working_day(d, schedule, started_at):
            wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, d, schedule)
            total += work_seconds_per_day(wf, wt, lf, lt, le)
        d += timedelta(days=1)
    return total


def working_seconds_elapsed_in_year(year: int, month: int, day: int, hour: int, minute: int, second: int,
                                     schedule: str, started_at: date | None,
                                     work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                                     lunch_enabled: bool = True, day_schedules: dict | None = None) -> float:
    total = 0.0
    for m in range(1, month):
        total += working_seconds_in_month(year, m, schedule, started_at, work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules)
    total += working_seconds_elapsed_in_month(year, month, day, hour, minute, second,
                                             schedule, started_at, work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules)
    return total


def is_working_now(now_date: date, now_hour: int, now_minute: int,
                   work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                   schedule: str, started_at: date | None,
                   lunch_enabled: bool = True, day_schedules: dict | None = None) -> bool:
    return work_status_now(now_date, now_hour, now_minute,
                           work_from, work_to, lunch_from, lunch_to,
                           schedule, started_at, lunch_enabled, day_schedules) == "working"


def work_status_now(now_date: date, now_hour: int, now_minute: int,
                    work_from: str, work_to: str, lunch_from: str, lunch_to: str,
                    schedule: str, started_at: date | None,
                    lunch_enabled: bool = True, day_schedules: dict | None = None) -> str:
    """Возвращает 'working' | 'lunch' | 'off'."""
    if not is_working_day(now_date, schedule, started_at):
        return "off"
    if schedule == "24x7":
        return "working"
    wf, wt, lf, lt, le = get_day_times(work_from, work_to, lunch_from, lunch_to, lunch_enabled, day_schedules, now_date, schedule)
    h1, m1 = parse_time(wf)
    h2, m2 = parse_time(wt)
    t = now_hour * 60 + now_minute
    start_m = h1 * 60 + m1
    end_m = h2 * 60 + m2
    if t < start_m or t >= end_m:
        return "off"
    if le:
        l1, lm1 = parse_time(lf)
        l2, lm2 = parse_time(lt)
        lunch_s = l1 * 60 + lm1
        lunch_e = l2 * 60 + lm2
        if lunch_s <= t < lunch_e:
            return "lunch"
    return "working"
