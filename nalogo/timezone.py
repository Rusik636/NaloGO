"""
Timezone handling for API datetime values.

Two distinct concerns are kept separate here:

* **Wire timezone** (:data:`API_TIMEZONE`) — the tax authority reads the wall
  clock of a transmitted datetime as Moscow time and ignores its offset, so
  everything must leave the library converted to Moscow. This is not a user
  preference and must not be changed to "the region I live in".
* **Input timezone** (:data:`DEFAULT_INPUT_TIMEZONE`, configurable) — how to
  interpret a *naive* datetime supplied by the caller. A user in Yekaterinburg
  writing ``datetime(2025, 12, 28, 12, 0)`` means noon local, not noon Moscow.

Aware datetimes carry their own offset, so the input timezone never applies to
them: they are simply converted to Moscow.
"""

from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .exceptions import (
    DateTimeFormatException,
    InputException,
    TimezoneException,
)

#: Timezone the API records receipts in. Everything is converted to it on the
#: wire, regardless of where the taxpayer is located.
API_TIMEZONE = ZoneInfo("Europe/Moscow")

#: Timezone assumed for naive datetimes when the caller configures none.
DEFAULT_INPUT_TIMEZONE = API_TIMEZONE


def resolve_timezone(tz: str | tzinfo | None) -> tzinfo:
    """
    Resolve a timezone specification to a tzinfo object.

    Args:
        tz: IANA timezone name (e.g. "Europe/Moscow"), a tzinfo object,
            or None to use DEFAULT_INPUT_TIMEZONE

    Returns:
        tzinfo instance

    Raises:
        TimezoneException: If the name is unknown or the type is unsupported
    """
    if tz is None:
        return DEFAULT_INPUT_TIMEZONE
    if isinstance(tz, tzinfo):
        return tz
    if isinstance(tz, str):
        try:
            return ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise TimezoneException(
                f"Unknown timezone: {tz!r}. Expected an IANA name "
                f"such as 'Europe/Moscow'."
            ) from exc
    raise TimezoneException(
        f"Timezone must be a str, tzinfo or None, got {type(tz).__name__}"
    )


def to_api_timezone(dt: datetime, input_tz: tzinfo) -> datetime:
    """
    Normalize a datetime to the timezone the API records receipts in.

    Naive datetimes are assumed to be wall clock time in ``input_tz`` and are
    labelled with it first. Aware datetimes already identify an instant, so
    ``input_tz`` is ignored for them. Both are then converted to
    :data:`API_TIMEZONE`.

    Args:
        dt: Datetime to normalize
        input_tz: Timezone assumed for naive input

    Returns:
        Timezone-aware datetime in API_TIMEZONE
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=input_tz)
    return dt.astimezone(API_TIMEZONE)


def parse_datetime(value: datetime | str, input_tz: tzinfo) -> datetime:
    """
    Accept a datetime object or an ISO 8601 string and normalize it.

    Strings are parsed with :meth:`datetime.fromisoformat`, which accepts the
    forms the API and most databases produce::

        "2025-12-28T12:00:00+10:00"   offset -> used as-is
        "2025-12-28T12:00:00Z"        UTC
        "2025-12-28T12:00:00"         no offset -> read as input_tz
        "2025-12-28"                  midnight in input_tz

    Args:
        value: Datetime object or ISO 8601 string
        input_tz: Timezone assumed when the value carries no offset

    Returns:
        Timezone-aware datetime in API_TIMEZONE

    Raises:
        DateTimeFormatException: If a string cannot be parsed
        InputException: If the value is neither a datetime nor a string
    """
    if isinstance(value, datetime):
        return to_api_timezone(value, input_tz)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise DateTimeFormatException(
                f"Cannot parse datetime: {value!r}. Expected ISO 8601, "
                f"for example '2025-12-28T12:00:00+03:00'."
            ) from exc
        return to_api_timezone(parsed, input_tz)
    raise InputException(
        f"Datetime must be a datetime or an ISO 8601 string, "
        f"got {type(value).__name__}"
    )
