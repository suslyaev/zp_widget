"""
Календарь рабочих дней РФ.
Выходные: сб, вс. Праздники по производственному календарю РФ.
"""
from datetime import date, timedelta

# Праздничные дни РФ (даты, когда не работаем)
# Формат: (месяц, день) для ежегодных
# + переносы и особые периоды по годам
RU_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),  # Новогодние каникулы
    (2, 23),   # День защитника Отечества
    (3, 8),    # Международный женский день
    (5, 1),    # Праздник Весны и Труда
    (5, 9),    # День Победы
    (6, 12),   # День России
    (11, 4),   # День народного единства
}

# Дни переноса (рабочие субботы/воскресенья) - даты когда РАБОТАЕМ в выходной
# Ключ: год, значение: список дат (месяц, день)
RU_WORKING_WEEKENDS = {
    2024: [(4, 27)],   # Суббота 27 апреля - рабочий день
    2025: [(5, 2), (5, 8), (6, 13), (12, 31)],
    2026: [],
}

# Дополнительные выходные (когда праздник переносится и добавляется выходной)
# Ключ: год, значение: список (месяц, день)
RU_EXTRA_OFF = {
    2024: [],
    2025: [(2, 24), (3, 10)],  # Доп. выходные (перенос с сб/вс)
    2026: [],
}


def is_working_day(d: date) -> bool:
    """Является ли дата рабочим днём по календарю РФ."""
    year = d.year
    if year < 2024 or year > 2026:
        # Для других лет используем упрощённую логику: сб/вс выходные, праздники по фиксированным датам
        pass

    md = (d.month, d.day)
    weekday = d.weekday()  # 0=пн, 6=вс

    # Рабочий день переноса (суббота/воскресенье, но работаем)
    if year in RU_WORKING_WEEKENDS:
        for m, day in RU_WORKING_WEEKENDS[year]:
            if (d.month, d.day) == (m, day):
                return True

    # Выходные сб, вс (если не рабочий перенос)
    if weekday >= 5:
        return False

    # Праздник
    if md in RU_HOLIDAYS:
        return False

    # Дополнительные выходные по переносам
    if year in RU_EXTRA_OFF and md in RU_EXTRA_OFF[year]:
        return False

    # Новогодние каникулы - иногда продлеваются
    if d.month == 1 and d.day in (1, 2, 3, 4, 5, 6, 7, 8):
        return False

    return True


def working_days_in_month(year: int, month: int) -> int:
    """Количество рабочих дней в месяце."""
    count = 0
    d = date(year, month, 1)
    while d.month == month:
        if is_working_day(d):
            count += 1
        d += timedelta(days=1)
    return count


def working_seconds_in_month(year: int, month: int) -> float:
    """Рабочих секунд в месяце. График 9:00-17:00, обед 13:00-14:00 = 7 ч/день."""
    SECONDS_PER_WORK_DAY = 7 * 3600  # 7 часов
    return working_days_in_month(year, month) * SECONDS_PER_WORK_DAY


def working_seconds_elapsed_in_month(year: int, month: int, day: int, hour: int, minute: int, second: int) -> float:
    """
    Сколько рабочих секунд уже прошло в этом месяце на момент (day, hour, minute, second).
    Учитывает график 9-17, обед 13-14.
    """
    total = 0.0
    d = date(year, month, 1)
    today = date(year, month, day)
    SECONDS_PER_WORK_DAY = 7 * 3600

    while d < today:
        if is_working_day(d):
            total += SECONDS_PER_WORK_DAY
        d += timedelta(days=1)

    if not is_working_day(today):
        return total

    # Сегодня рабочий день — считаем сколько уже отработано
    # 9:00-12:59 = 4 часа, 14:00-16:59 = 3 часа (до 17:00)
    h, m, s = hour, minute, second
    sec_today = h * 3600 + m * 60 + s

    # Начало рабочего дня 9:00 = 32400 сек от полуночи
    # Обед 13:00-14:00 — вычитаем
    start_sec = 9 * 3600
    lunch_start = 13 * 3600
    lunch_end = 14 * 3600
    end_sec = 17 * 3600

    if sec_today <= start_sec:
        pass  # ещё не начали
    elif sec_today <= lunch_start:
        total += sec_today - start_sec
    elif sec_today <= lunch_end:
        total += (lunch_start - start_sec)  # до обеда полностью
    elif sec_today <= end_sec:
        total += (lunch_start - start_sec) + (sec_today - lunch_end)
    else:
        total += SECONDS_PER_WORK_DAY  # день полностью отработан

    return total


def working_seconds_elapsed_in_day(hour: int, minute: int, second: int) -> float:
    """Рабочих секунд с начала дня (0:00) до (hour, minute, second). График 9-17, обед 13-14."""
    sec_today = hour * 3600 + minute * 60 + second
    start_sec = 9 * 3600
    lunch_start = 13 * 3600
    lunch_end = 14 * 3600
    end_sec = 17 * 3600
    SECONDS_PER_WORK_DAY = 7 * 3600

    if sec_today <= start_sec:
        return 0
    elif sec_today <= lunch_start:
        return sec_today - start_sec
    elif sec_today <= lunch_end:
        return lunch_start - start_sec
    elif sec_today <= end_sec:
        return (lunch_start - start_sec) + (sec_today - lunch_end)
    else:
        return SECONDS_PER_WORK_DAY


def working_seconds_in_day() -> float:
    """Рабочих секунд в одном рабочем дне (7 ч)."""
    return 7 * 3600


def working_seconds_in_week(year: int, month: int, day: int) -> float:
    """Всего рабочих секунд в текущей неделе (пн-пт)."""
    d = date(year, month, day)
    week_start = d - timedelta(days=d.weekday())
    week_end = week_start + timedelta(days=6)
    count = 0
    cur = week_start
    while cur <= week_end:
        if is_working_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count * 7 * 3600


def working_seconds_elapsed_in_week(year: int, month: int, day: int, hour: int, minute: int, second: int) -> float:
    """Рабочих секунд с понедельника текущей недели до момента (day, h, m, s)."""
    d = date(year, month, day)
    week_start = d - timedelta(days=d.weekday())
    total = 0.0
    cur = week_start
    today = date(year, month, day)
    SECONDS_PER_WORK_DAY = 7 * 3600

    while cur < today:
        if is_working_day(cur):
            total += SECONDS_PER_WORK_DAY
        cur += timedelta(days=1)

    if not is_working_day(today):
        return total

    total += working_seconds_elapsed_in_day(hour, minute, second)
    return total


def working_seconds_in_year(year: int) -> float:
    """Рабочих секунд в году."""
    count = 0
    d = date(year, 1, 1)
    while d.year == year:
        if is_working_day(d):
            count += 1
        d += timedelta(days=1)
    return count * 7 * 3600


def working_seconds_elapsed_in_year(year: int, month: int, day: int, hour: int, minute: int, second: int) -> float:
    """Рабочих секунд с 1 января до момента (day, h, m, s)."""
    total = 0.0
    for m in range(1, month):
        total += working_seconds_in_month(year, m)
    total += working_seconds_elapsed_in_month(year, month, day, hour, minute, second)
    return total
