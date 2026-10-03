"""Tempo: tudo é guardado em UTC (datetimes com fuso); exibição e calendário em Europe/Lisbon."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import holidays


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    """Datetimes sem fuso são tratados como UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def to_local(dt: datetime, tz: str) -> datetime:
    return as_utc(dt).astimezone(ZoneInfo(tz))


def local_to_utc(dt_local: datetime) -> datetime:
    return dt_local.astimezone(UTC)


def in_quiet_hours(now_utc: datetime, tz: str, window: tuple[time, time]) -> bool:
    start, end = window
    t = to_local(now_utc, tz).time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # janela que atravessa a meia-noite


def quiet_hours_end(now_utc: datetime, tz: str, window: tuple[time, time]) -> datetime:
    """Próximo fim da janela de silêncio (em UTC)."""
    local = to_local(now_utc, tz)
    end_local = local.replace(hour=window[1].hour, minute=window[1].minute, second=0, microsecond=0)
    if end_local <= local:
        end_local += timedelta(days=1)
    return local_to_utc(end_local)


def _pt_holidays(years: range) -> holidays.HolidayBase:
    return holidays.country_holidays("PT", years=years)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _pt_holidays(range(d.year, d.year + 1))


def add_business_days(start_utc: datetime, n: int, tz: str) -> datetime:
    """Soma n dias úteis (calendário PT) mantendo a hora local."""
    local = to_local(start_utc, tz)
    d = local.date()
    added = 0
    while added < n:
        d += timedelta(days=1)
        if is_business_day(d):
            added += 1
    target = datetime.combine(d, local.timetz())
    return local_to_utc(target)


def next_local_time(now_utc: datetime, tz: str, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    local = to_local(now_utc, tz)
    cand = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand <= local:
        cand += timedelta(days=1)
    return local_to_utc(cand)


def local_date(now_utc: datetime, tz: str) -> date:
    return to_local(now_utc, tz).date()
