from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import jdatetime  # type: ignore[import-untyped]


def datetime_to_jalali(dt: datetime, date_only: bool = False) -> str:
    dt = dt.astimezone(ZoneInfo("Asia/Tehran"))
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime(
        "%Y/%m/%d" if date_only else "%Y/%m/%d - %H:%M"
    )


def utcnow() -> datetime:
    return datetime.now(ZoneInfo("UTC"))


def datetime_to_timestamp(value: datetime) -> int:
    dt_utc = value.replace(tzinfo=ZoneInfo("UTC"))
    return int(dt_utc.timestamp())


def get_zero_time() -> datetime:
    return datetime.combine(date.today(), time())
