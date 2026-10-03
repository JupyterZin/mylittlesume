from datetime import UTC, date, datetime

from talos.clock import add_business_days, in_quiet_hours, is_business_day, quiet_hours_end
from talos.config import Settings

TZ = "Europe/Lisbon"
W = Settings().quiet_window


def test_quiet_hours_crossing_midnight():
    # outubro: Lisboa = UTC+1
    assert in_quiet_hours(datetime(2026, 10, 5, 22, 0, tzinfo=UTC), TZ, W)  # 23:00 local
    assert in_quiet_hours(datetime(2026, 10, 5, 5, 0, tzinfo=UTC), TZ, W)  # 06:00 local
    assert not in_quiet_hours(datetime(2026, 10, 5, 12, 0, tzinfo=UTC), TZ, W)
    end = quiet_hours_end(datetime(2026, 10, 5, 22, 0, tzinfo=UTC), TZ, W)
    assert end == datetime(2026, 10, 6, 7, 0, tzinfo=UTC)  # 08:00 local


def test_business_days_skip_weekend_and_pt_holidays():
    assert not is_business_day(date(2026, 10, 5))  # Implantação da República
    assert not is_business_day(date(2026, 10, 10))  # sábado
    # sexta 2 out 10:00 UTC + 3 dias úteis → seg 5 é feriado → 6, 7, 8
    assert add_business_days(datetime(2026, 10, 2, 10, 0, tzinfo=UTC), 3, TZ).date() == date(2026, 10, 8)
