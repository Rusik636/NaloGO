"""
Tests for network failure handling and token lifecycle.

The invariant under test: "the service answered and refused" and "the service
never answered" are different outcomes and must never be confused. The first
needs a human, the second needs a retry. A library that reports the second as
the first makes callers revoke access from users whose access is fine.

One test per defect, not a happy path.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from nalogo import (
    Client,
    DomainException,
    NetworkException,
    PhoneException,
    RateLimitException,
    ServerException,
    ServiceUnavailableException,
    UnauthorizedException,
    UnprocessableEntityException,
    ValidationException,
)
from nalogo._http import AsyncHTTPClient, AuthProvider
from nalogo.auth import AuthProviderImpl
from nalogo.exceptions import (
    ConnectionException,
    TimeoutException,
    UnknownErrorException,
)

INCOME_URL = "https://lknpd.nalog.ru/api/v1/income"
USER_URL = "https://lknpd.nalog.ru/api/v1/user"
TOKEN_URL = "https://lknpd.nalog.ru/api/v1/auth/token"


def token_payload(token="access-1", refresh="refresh-1", expires_in_hours=24):
    """A token payload shaped like the one the tax service returns."""
    expiry = datetime.now(UTC) + timedelta(hours=expires_in_hours)
    return {
        "token": token,
        "refreshToken": refresh,
        "tokenExpireIn": expiry.isoformat().replace("+00:00", "Z"),
        "profile": {"inn": "123456789012", "displayName": "Test User"},
    }


async def make_client(**kwargs):
    """An authenticated client with retries off unless a test wants them."""
    client = Client(**{"timeout": 1.0, **kwargs})
    client.http_client.max_attempts = 1
    await client.authenticate(json.dumps(token_payload()))
    return client


class TestTransportErrorsEnterTheHierarchy:
    """Defect 1: httpx errors escaped past every `except DomainException`."""

    @respx.mock
    async def test_connect_error_is_a_domain_exception(self):
        respx.get(USER_URL).mock(side_effect=httpx.ConnectError("refused"))
        client = await make_client()

        with pytest.raises(DomainException):
            await client.user().get()

    @respx.mock
    async def test_connect_error_maps_to_connection_exception(self):
        respx.get(USER_URL).mock(side_effect=httpx.ConnectError("refused"))
        client = await make_client()

        with pytest.raises(ConnectionException) as exc:
            await client.user().get()
        assert exc.value.response is None
        assert exc.value.request_may_have_been_sent is False

    @respx.mock
    async def test_read_timeout_maps_to_timeout_exception(self):
        respx.get(USER_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        client = await make_client()

        with pytest.raises(TimeoutException) as exc:
            await client.user().get()
        # The request went out; the answer did not come back. Callers must not
        # treat this as "nothing happened".
        assert exc.value.request_may_have_been_sent is True

    @respx.mock
    async def test_raw_httpx_error_never_reaches_the_caller(self):
        respx.get(USER_URL).mock(side_effect=httpx.ReadError("boom"))
        client = await make_client()

        with pytest.raises(NetworkException):
            await client.user().get()

    @respx.mock
    async def test_message_does_not_leak_the_token(self):
        respx.get(USER_URL).mock(side_effect=httpx.ConnectError("refused"))
        client = await make_client()

        with pytest.raises(NetworkException) as exc:
            await client.user().get()
        assert "access-1" not in str(exc.value)


class TestRefreshDoesNotFakeRejection:
    """
    Defect 4, the main test of the task.

    A blinked connection during token refresh must not arrive as "your access
    is invalid" — the caller would demand the user re-link an intact account.
    """

    @respx.mock
    async def test_network_failure_during_refresh_is_not_unauthorized(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(401, text="expired"))
        respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("network blinked"))
        client = await make_client()

        with pytest.raises(NetworkException):
            await client.user().get()

    @respx.mock
    async def test_network_failure_during_refresh_is_not_swallowed_as_401(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(401, text="expired"))
        respx.post(TOKEN_URL).mock(side_effect=httpx.ReadTimeout("no answer"))
        client = await make_client()

        with pytest.raises(NetworkException):
            await client.user().get()

    @respx.mock
    async def test_rejected_refresh_token_still_reports_unauthorized(self):
        """The opposite mistake is just as harmful: a revoked token must not
        look like a network hiccup, or the caller retries forever."""
        respx.get(USER_URL).mock(return_value=httpx.Response(401, text="expired"))
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(401, text="revoked"))
        client = await make_client()

        with pytest.raises(UnauthorizedException):
            await client.user().get()

    @respx.mock
    async def test_failed_refresh_leaves_the_stored_token_intact(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(401, text="expired"))
        respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
        client = await make_client()

        with pytest.raises(NetworkException):
            await client.user().get()

        stored = await client.auth_provider.get_token()
        assert stored["token"] == "access-1"
        assert stored["refreshToken"] == "refresh-1"

    @respx.mock
    async def test_successful_refresh_retries_the_original_request(self):
        respx.get(USER_URL).mock(
            side_effect=[
                httpx.Response(401, text="expired"),
                httpx.Response(200, json={"inn": "123456789012"}),
            ]
        )
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json=token_payload("access-2", "refresh-2")
            )
        )
        client = await make_client()

        result = await client.user().get()
        assert result["inn"] == "123456789012"


class TestRefreshLock:
    """Defect 5: two concurrent 401s must not spend the refresh token twice."""

    @respx.mock
    async def test_parallel_401s_cause_exactly_one_refresh(self):
        refreshes = {"n": 0}
        unauthorized = {"n": 0}
        both_saw_401 = asyncio.Event()

        async def slow_refresh(_request):
            refreshes["n"] += 1
            # Hold the lock long enough for the second coroutine to get its
            # own 401 and queue behind us. Without the double-check after the
            # lock it would then refresh a second time, with a refresh token
            # the tax service has already rotated away.
            await asyncio.wait_for(both_saw_401.wait(), timeout=1)
            return httpx.Response(200, json=token_payload("access-2", "refresh-2"))

        def user_handler(request):
            if request.headers.get("Authorization") == "Bearer access-2":
                return httpx.Response(200, json={"inn": "123456789012"})
            unauthorized["n"] += 1
            if unauthorized["n"] >= 2:
                both_saw_401.set()
            return httpx.Response(401, text="expired")

        respx.post(TOKEN_URL).mock(side_effect=slow_refresh)
        respx.get(USER_URL).mock(side_effect=user_handler)
        client = await make_client()

        api = client.user()
        results = await asyncio.gather(api.get(), api.get())

        assert all(r["inn"] == "123456789012" for r in results)
        assert unauthorized["n"] == 2, "both requests must have hit 401 first"
        assert refreshes["n"] == 1, (
            "the tax service rotates the refresh token; a second refresh "
            "would travel with an already-spent one"
        )

    @respx.mock
    async def test_second_waiter_reuses_the_token_it_did_not_fetch(self):
        """The queued coroutine must retry with the fresh token, not fail."""
        refreshes = {"n": 0}
        both_saw_401 = asyncio.Event()

        async def slow_refresh(_request):
            refreshes["n"] += 1
            await asyncio.wait_for(both_saw_401.wait(), timeout=1)
            return httpx.Response(200, json=token_payload("access-2", "refresh-2"))

        seen = {"n": 0}

        def user_handler(request):
            if request.headers.get("Authorization") == "Bearer access-2":
                return httpx.Response(200, json={"inn": "123456789012"})
            seen["n"] += 1
            if seen["n"] >= 2:
                both_saw_401.set()
            return httpx.Response(401, text="expired")

        respx.post(TOKEN_URL).mock(side_effect=slow_refresh)
        respx.get(USER_URL).mock(side_effect=user_handler)
        client = await make_client()

        api = client.user()
        await asyncio.gather(api.get(), api.get())

        stored = await client.auth_provider.get_token()
        assert stored["refreshToken"] == "refresh-2"
        assert refreshes["n"] == 1


class TestStatusCodesAreDistinguishable:
    """Defect 3: 429 and 5xx used to be indistinguishable from unknown."""

    @respx.mock
    async def test_429_is_a_rate_limit(self):
        respx.get(USER_URL).mock(
            return_value=httpx.Response(
                429, text="slow down", headers={"Retry-After": "12"}
            )
        )
        client = await make_client()

        with pytest.raises(RateLimitException) as exc:
            await client.user().get()
        assert exc.value.retry_after == 12.0
        assert not isinstance(exc.value, UnknownErrorException)

    @respx.mock
    async def test_429_without_retry_after_still_parses(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(429, text="slow down"))
        client = await make_client()

        with pytest.raises(RateLimitException) as exc:
            await client.user().get()
        assert exc.value.retry_after is None

    @pytest.mark.parametrize("status", [502, 503, 504])
    @respx.mock
    async def test_gateway_statuses_are_service_unavailable(self, status):
        respx.get(USER_URL).mock(
            return_value=httpx.Response(status, text="maintenance")
        )
        client = await make_client()

        with pytest.raises(ServiceUnavailableException) as exc:
            await client.user().get()
        # Existing `except ServerException` handlers keep working.
        assert isinstance(exc.value, ServerException)

    @respx.mock
    async def test_500_stays_a_plain_server_error(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(500, text="boom"))
        client = await make_client()

        with pytest.raises(ServerException) as exc:
            await client.user().get()
        assert not isinstance(exc.value, ServiceUnavailableException)


class TestRetriesNeverDuplicateAReceipt:
    """
    Defect 2 and requirement 5.

    Issuing a receipt is not idempotent at the tax service. A repeat that the
    server may already have seen can produce a second document, which is worse
    than a failed call.
    """

    @respx.mock
    async def test_receipt_is_not_reissued_after_a_timeout(self):
        route = respx.post(INCOME_URL).mock(side_effect=httpx.ReadTimeout("no answer"))
        client = await make_client()
        client.http_client.max_attempts = 5

        with pytest.raises(TimeoutException):
            await client.income().create("Услуга", 100)

        assert route.call_count == 1, "a timed-out POST must never be repeated"

    @respx.mock
    async def test_receipt_is_retried_when_it_provably_never_left(self):
        route = respx.post(INCOME_URL).mock(
            side_effect=[
                httpx.ConnectError("refused"),
                httpx.Response(200, json={"approvedReceiptUuid": "uuid-1"}),
            ]
        )
        client = await make_client()
        client.http_client.max_attempts = 3

        result = await client.income().create("Услуга", 100)

        assert result["approvedReceiptUuid"] == "uuid-1"
        assert route.call_count == 2

    @respx.mock
    async def test_get_is_retried_on_any_transport_error(self):
        route = respx.get(USER_URL).mock(
            side_effect=[
                httpx.ReadTimeout("slow"),
                httpx.Response(200, json={"inn": "123456789012"}),
            ]
        )
        client = await make_client()
        client.http_client.max_attempts = 3

        await client.user().get()
        assert route.call_count == 2

    @respx.mock
    async def test_api_refusals_are_never_retried(self):
        route = respx.get(USER_URL).mock(return_value=httpx.Response(400, text="bad"))
        client = await make_client()
        client.http_client.max_attempts = 3

        with pytest.raises(DomainException):
            await client.user().get()
        assert route.call_count == 1

    @respx.mock
    async def test_attempts_are_bounded(self):
        route = respx.get(USER_URL).mock(side_effect=httpx.ConnectError("refused"))
        client = await make_client()
        client.http_client.max_attempts = 3

        with pytest.raises(ConnectionException):
            await client.user().get()
        assert route.call_count == 3

    async def test_backoff_grows_and_is_jittered(self):
        http = AsyncHTTPClient("https://x", auth_provider=_StubProvider())
        first = [http._backoff(0) for _ in range(50)]
        later = [http._backoff(3) for _ in range(50)]

        assert max(first) <= 0.5
        assert max(later) <= 4.0
        assert len(set(first)) > 1, "jitter must not be constant"


class _StubProvider(AuthProvider):
    """Minimal provider: the backoff test needs no tokens at all."""

    async def get_token(self):
        return None

    async def refresh(self, refresh_token):
        # Аргумент не используется, но он часть контракта AuthProvider.
        _ = refresh_token


class TestTokenLifetime:
    """Defect 7: the library ignored tokenExpireIn entirely."""

    def test_expiring_token_is_detected(self):
        provider = AuthProviderImpl()
        provider._token_data = token_payload(expires_in_hours=0)
        assert provider.is_token_expiring() is True

    def test_fresh_token_is_not_expiring(self):
        provider = AuthProviderImpl()
        provider._token_data = token_payload(expires_in_hours=24)
        assert provider.is_token_expiring() is False

    def test_margin_triggers_before_actual_expiry(self):
        provider = AuthProviderImpl()
        expiry = datetime.now(UTC) + timedelta(seconds=30)
        provider._token_data = {
            "token": "t",
            "tokenExpireIn": expiry.isoformat().replace("+00:00", "Z"),
        }
        assert provider.is_token_expiring() is True

    @pytest.mark.parametrize("value", [None, "", "not-a-date", 12345])
    def test_unknown_expiry_does_not_trigger_refresh(self, value):
        """Treating unknown as expired would refresh before every request and
        spin the refresh-token rotation endlessly."""
        provider = AuthProviderImpl()
        provider._token_data = {"token": "t", "tokenExpireIn": value}
        assert provider.is_token_expiring() is False

    def test_no_token_is_not_expiring(self):
        assert AuthProviderImpl().is_token_expiring() is False

    @respx.mock
    async def test_expiring_token_is_refreshed_before_the_request(self):
        refresh_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json=token_payload("access-2", "refresh-2")
            )
        )
        user_route = respx.get(USER_URL).mock(
            return_value=httpx.Response(200, json={"inn": "123456789012"})
        )
        client = Client(timeout=1.0)
        client.http_client.max_attempts = 1
        await client.authenticate(json.dumps(token_payload(expires_in_hours=0)))

        await client.user().get()

        assert refresh_route.call_count == 1
        # No wasted 401 round-trip: the very first call already carried the
        # new token.
        assert user_route.call_count == 1
        assert user_route.calls[0].request.headers["Authorization"] == "Bearer access-2"


class TestTokenStorage:
    """Defect 8: write failures vanished without a trace."""

    def test_write_failure_is_logged(self, tmp_path, caplog):
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory")
        provider = AuthProviderImpl(storage_path=str(blocked / "token.json"))
        provider._token_data = token_payload()

        with caplog.at_level("WARNING"):
            provider._save_token_to_storage()

        assert any("Could not persist" in r.message for r in caplog.records)

    def test_write_failure_does_not_leak_the_token(self, tmp_path, caplog):
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory")
        provider = AuthProviderImpl(storage_path=str(blocked / "token.json"))
        provider._token_data = token_payload(token="super-secret")

        with caplog.at_level("WARNING"):
            provider._save_token_to_storage()

        assert "super-secret" not in caplog.text

    def test_unreadable_storage_is_logged(self, tmp_path, caplog):
        broken = tmp_path / "token.json"
        broken.write_text("{ not json")

        with caplog.at_level("WARNING"):
            provider = AuthProviderImpl(storage_path=str(broken))

        assert provider._token_data is None
        assert any("Could not read" in r.message for r in caplog.records)


class TestConnectionReuse:
    """Defect 9: a fresh pool and TLS handshake per request."""

    @respx.mock
    async def test_same_client_across_requests(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(200, json={"inn": "1"}))
        client = await make_client()

        await client.user().get()
        first = client.http_client._client
        await client.user().get()

        assert client.http_client._client is first

    @respx.mock
    async def test_aclose_releases_the_pool(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(200, json={"inn": "1"}))
        client = await make_client()
        await client.user().get()

        await client.aclose()
        assert client.http_client._client is None

    @respx.mock
    async def test_client_works_as_async_context_manager(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(200, json={"inn": "1"}))

        async with Client(timeout=1.0) as client:
            client.http_client.max_attempts = 1
            await client.authenticate(json.dumps(token_payload()))
            await client.user().get()

        assert client.http_client._client is None

    @respx.mock
    async def test_reuse_after_close(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(200, json={"inn": "1"}))
        client = await make_client()
        await client.user().get()
        await client.aclose()

        # A closed client must not poison the instance.
        await client.user().get()
        assert client.http_client._client is not None


class TestUnprocessableEntityNaming:
    """
    422 used to surface as PhoneException regardless of what failed.

    A receipt rejected for a future operationTime came back as an exception
    named after phones, which sent people looking for an SMS problem that did
    not exist (see the report in issue #2).
    """

    def test_both_names_are_one_class(self):
        assert PhoneException is UnprocessableEntityException

    @respx.mock
    async def test_receipt_422_no_longer_reads_as_a_phone_error(self):
        respx.post(INCOME_URL).mock(
            return_value=httpx.Response(
                422,
                json={
                    "code": "validation.failed",
                    "message": "Время формирования запроса не может быть больше текущего",
                },
            )
        )
        client = await make_client()

        with pytest.raises(UnprocessableEntityException) as exc:
            await client.income().create("Услуга", 100)
        assert type(exc.value).__name__ == "UnprocessableEntityException"

    @respx.mock
    async def test_existing_handlers_keep_working(self):
        """The old name is an alias, so code written against it still catches."""
        respx.post(INCOME_URL).mock(return_value=httpx.Response(422, text="rejected"))
        client = await make_client()

        with pytest.raises(PhoneException):
            await client.income().create("Услуга", 100)

    @respx.mock
    async def test_still_distinct_from_400(self):
        respx.get(USER_URL).mock(return_value=httpx.Response(422, text="rejected"))
        client = await make_client()

        with pytest.raises(UnprocessableEntityException) as exc:
            await client.user().get()
        assert not isinstance(exc.value, ValidationException)
        assert exc.value.response.status_code == 422
