from datetime import UTC, datetime

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass


def utcnow():
    """Return a naive UTC datetime for compatibility with existing DB columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def display_timezone(tz_name=None):
    if tz_name and ZoneInfo is not None:
        try:
            return ZoneInfo(str(tz_name))
        except ZoneInfoNotFoundError:
            pass

    return datetime.now().astimezone().tzinfo or UTC


def serialize_utc_naive(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat()


def utc_naive_to_local(value, tz_name=None):
    if value is None:
        return None

    tz = display_timezone(tz_name)
    return value.replace(tzinfo=UTC).astimezone(tz).replace(tzinfo=None)
