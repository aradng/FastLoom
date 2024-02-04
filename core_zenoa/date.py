from datetime import datetime

import jdatetime
import pytz


def datetime_to_jalali(dt: datetime, date_only: bool = False) -> str:
    dt = dt.astimezone(pytz.timezone("Asia/Tehran"))
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime(
        "%Y/%m/%d" if date_only else "%Y/%m/%d - %H:%M"
    )


def utcnow() -> datetime:
    return datetime.now(pytz.utc)


def datetime_to_timestamp(value: datetime) -> int:
    dt_utc = value.replace(tzinfo=pytz.UTC)
    return int(dt_utc.timestamp())
