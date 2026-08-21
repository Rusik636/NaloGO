"""
Tests for timezone handling of receipt datetimes.

Regression coverage for the bug where all datetimes were force-converted to
UTC and sent with a "Z" suffix, causing the tax authority to record receipts
shifted by the Moscow offset.
"""

import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

import pytest

from nalogo import Client
from nalogo.dto.income import AtomDateTime
from nalogo.exceptions import (
    DateTimeFormatException,
    DomainException,
    InputException,
    TimezoneException,
)
from nalogo.timezone import (
    API_TIMEZONE,
    DEFAULT_INPUT_TIMEZONE,
    resolve_timezone,
    to_api_timezone,
)

MSK = ZoneInfo("Europe/Moscow")
EKB = ZoneInfo("Asia/Yekaterinburg")
VLA = ZoneInfo("Asia/Vladivostok")


def serialize(dt: datetime | str, tz: str | tzinfo | None = None) -> str:
    """Serialize a datetime the way it is sent to the API."""
    return AtomDateTime.from_datetime(dt, tz).model_dump()["value"]


class TestResolveTimezone:
    """resolve_timezone() accepts the documented spellings."""

    def test_none_defaults_to_moscow(self):
        assert resolve_timezone(None) is DEFAULT_INPUT_TIMEZONE
        assert resolve_timezone(None) == MSK

    def test_iana_name(self):
        assert resolve_timezone("Asia/Yekaterinburg") == ZoneInfo("Asia/Yekaterinburg")

    def test_tzinfo_passed_through(self):
        tz = timezone(timedelta(hours=7))
        assert resolve_timezone(tz) is tz

    def test_unknown_name_raises_value_error(self):
        with pytest.raises(TimezoneException, match="Unknown timezone"):
            resolve_timezone("Mars/Olympus")

    def test_wrong_type_raises(self):
        with pytest.raises(TimezoneException, match="must be a str, tzinfo"):
            resolve_timezone(3)

    def test_is_catchable_as_domain_exception(self):
        with pytest.raises(DomainException):
            resolve_timezone("Mars/Olympus")

    def test_is_catchable_as_value_error(self):
        with pytest.raises(ValueError):
            resolve_timezone("Mars/Olympus")


class TestToApiTimezone:
    """Everything lands in Moscow; input_tz only interprets naive values."""

    def test_naive_moscow_input_keeps_wall_clock(self):
        result = to_api_timezone(datetime(2025, 12, 28, 0, 30), MSK)
        assert result.hour == 0
        assert result.minute == 30
        assert result.utcoffset() == timedelta(hours=3)

    def test_naive_regional_input_is_converted_to_moscow(self):
        """Noon in Yekaterinburg is 10:00 Moscow, and 10:00 is what is sent."""
        result = to_api_timezone(datetime(2025, 12, 28, 12, 0), EKB)
        assert result.hour == 10
        assert result.tzinfo == API_TIMEZONE

    def test_aware_ignores_input_tz(self):
        """An aware datetime already names an instant; input_tz must not apply."""
        aware = datetime(2025, 12, 28, 12, 0, tzinfo=EKB)
        assert to_api_timezone(aware, VLA) == to_api_timezone(aware, MSK)

    def test_aware_utc_is_converted(self):
        utc = datetime(2025, 12, 27, 21, 30, tzinfo=UTC)
        result = to_api_timezone(utc, MSK)
        assert result.hour == 0
        assert result.day == 28

    def test_output_is_always_moscow(self):
        for tz in (MSK, EKB, VLA, UTC):
            assert (
                to_api_timezone(datetime(2025, 6, 1, 9, 0), tz).tzinfo == API_TIMEZONE
            )


class TestAtomDateTimeSerialization:
    """Serialized payload must carry a local offset, never a UTC 'Z'."""

    def test_default_is_moscow_offset(self):
        assert serialize(datetime(2025, 12, 28, 0, 30)) == "2025-12-28T00:30:00+03:00"

    def test_never_emits_z_suffix(self):
        assert not serialize(datetime(2025, 12, 28, 0, 30)).endswith("Z")

    def test_regression_utc_input_keeps_moscow_wall_clock(self):
        """A UTC 21:30 input must be sent as 00:30 MSK, not as 21:30."""
        utc = datetime(2025, 12, 27, 21, 30, tzinfo=UTC)
        assert serialize(utc) == "2025-12-28T00:30:00+03:00"

    def test_naive_input_is_not_mislabelled_as_utc(self):
        """Naive local time must keep its wall clock, not shift by the offset."""
        assert serialize(datetime(2025, 12, 28, 0, 30)).startswith("2025-12-28T00:30")

    @pytest.mark.parametrize(
        ("tz_name", "expected"),
        [
            # naive 12:00 local -> the equivalent Moscow wall clock
            ("Europe/Kaliningrad", "2025-12-28T13:00:00+03:00"),
            ("Europe/Moscow", "2025-12-28T12:00:00+03:00"),
            ("Asia/Yekaterinburg", "2025-12-28T10:00:00+03:00"),
            ("Asia/Vladivostok", "2025-12-28T05:00:00+03:00"),
        ],
    )
    def test_naive_input_zone_shifts_to_moscow(self, tz_name, expected):
        assert serialize(datetime(2025, 12, 28, 12, 0), tz_name) == expected

    def test_offset_is_always_moscow(self):
        for tz_name in ("Asia/Vladivostok", "Europe/Kaliningrad", "UTC"):
            assert serialize(datetime(2025, 12, 28, 12, 0), tz_name).endswith("+03:00")

    def test_accepts_tzinfo_object(self):
        result = serialize(datetime(2025, 12, 28, 12, 0), ZoneInfo("Asia/Omsk"))
        assert result == "2025-12-28T09:00:00+03:00"

    def test_aware_input_ignores_configured_zone(self):
        """Region setting must not corrupt an explicit instant."""
        aware = datetime(2025, 12, 28, 12, 0, tzinfo=EKB)
        assert serialize(aware, "Asia/Vladivostok") == "2025-12-28T10:00:00+03:00"

    def test_no_fractional_seconds(self):
        """PHP's DATE_ATOM carries no microseconds."""
        dt = datetime(2025, 12, 28, 0, 30, 15, 123456)
        assert serialize(dt) == "2025-12-28T00:30:15+03:00"

    def test_now_is_always_moscow(self):
        assert AtomDateTime.now().value.utcoffset() == timedelta(hours=3)
        assert AtomDateTime.now("Asia/Yekaterinburg").value.utcoffset() == timedelta(
            hours=3
        )

    def test_tz_field_is_not_serialized(self):
        assert set(AtomDateTime.now().model_dump()) == {"value"}


class TestApiWiring:
    """Timezone flows from Client down to the Income API."""

    def test_client_defaults_to_moscow(self):
        assert Client().timezone == MSK

    def test_client_accepts_custom_timezone(self):
        assert Client(timezone="Asia/Vladivostok").timezone == VLA

    def test_client_rejects_unknown_timezone(self):
        with pytest.raises(TimezoneException, match="Unknown timezone"):
            Client(timezone="Nowhere/Nothing")

    def test_income_api_inherits_client_timezone(self):
        assert Client(timezone="Asia/Omsk").income().timezone == ZoneInfo("Asia/Omsk")


class TestMultiRegion:
    """A single taxpayer accepting payments across regions."""

    @pytest.fixture
    def client(self):
        return Client(timezone="Asia/Yekaterinburg")

    def test_per_call_override_beats_client_setting(self, client):
        api = client.income()
        assert api.timezone == EKB
        # same call, but this payment was taken in Vladivostok
        tz = resolve_timezone("Asia/Vladivostok")
        assert (
            AtomDateTime.from_datetime(datetime(2025, 12, 28, 12, 0), tz).model_dump()[
                "value"
            ]
            == "2025-12-28T05:00:00+03:00"
        )

    def test_aware_datetime_needs_no_configuration(self):
        """The safe pattern: an aware datetime is correct under any setting."""
        instant = datetime(2025, 12, 28, 12, 0, tzinfo=VLA)
        for setting in (None, "Europe/Moscow", "Asia/Yekaterinburg"):
            assert serialize(instant, setting) == "2025-12-28T05:00:00+03:00"

    def test_same_instant_from_three_regions_is_identical(self):
        """Noon MSK expressed in three zones must produce one payload."""
        noon_msk = datetime(2025, 12, 28, 12, 0, tzinfo=MSK)
        payloads = {
            serialize(noon_msk.astimezone(tz), None) for tz in (MSK, EKB, VLA, UTC)
        }
        assert payloads == {"2025-12-28T12:00:00+03:00"}


class TestIsoStringInput:
    """ISO 8601 strings are accepted wherever a datetime is."""

    @pytest.mark.parametrize(
        ("iso", "expected"),
        [
            # offset in the string wins
            ("2025-12-28T12:00:00+10:00", "2025-12-28T05:00:00+03:00"),
            ("2025-12-28T12:00:00+03:00", "2025-12-28T12:00:00+03:00"),
            ("2025-12-28T12:00:00Z", "2025-12-28T15:00:00+03:00"),
            # space separator, as produced by many databases
            ("2025-12-28 12:00:00+10:00", "2025-12-28T05:00:00+03:00"),
            # fractional seconds are truncated, not rejected
            ("2025-12-28T12:00:00.123456+10:00", "2025-12-28T05:00:00+03:00"),
        ],
    )
    def test_offset_aware_strings(self, iso, expected):
        assert serialize(iso) == expected

    def test_string_without_offset_uses_input_timezone(self):
        assert serialize("2025-12-28T12:00:00", "Asia/Vladivostok") == (
            "2025-12-28T05:00:00+03:00"
        )

    def test_date_only_is_midnight_in_input_timezone(self):
        assert serialize("2025-12-28", "Asia/Vladivostok") == (
            "2025-12-27T17:00:00+03:00"
        )

    def test_surrounding_whitespace_is_tolerated(self):
        assert serialize("  2025-12-28T12:00:00+03:00  ") == "2025-12-28T12:00:00+03:00"

    def test_string_and_datetime_agree(self):
        as_obj = datetime(2025, 12, 28, 12, 0, tzinfo=VLA)
        assert serialize(as_obj) == serialize("2025-12-28T12:00:00+10:00")

    @pytest.mark.parametrize(
        "bad", ["28.12.2025", "not a date", "2025-13-45T99:00:00", ""]
    )
    def test_unparseable_string_raises(self, bad):
        with pytest.raises(DateTimeFormatException, match="Cannot parse datetime"):
            serialize(bad)

    def test_wrong_type_raises_input_exception(self):
        with pytest.raises(InputException, match="must be a datetime or an ISO"):
            AtomDateTime.from_datetime(1735377000)

    def test_errors_are_catchable_as_value_error(self):
        with pytest.raises(ValueError):
            serialize("28.12.2025")

    def test_error_message_names_the_bad_value(self):
        with pytest.raises(DateTimeFormatException, match=re.escape("28.12.2025")):
            serialize("28.12.2025")
