"""AT-design: диагностика 401/403 (FR-5) и auth_status (FR-11), сужено ADR-025.

ADR-025 снимает режим персонального API-ключа целиком: `KTalkScopeError` больше не
поднимается (scope — понятие ключа, у сессии его нет), `AuthStatus.scopes`/
`.expired_at` удалены из DTO, `KTalkClient(personal_api_key=...)` — снятый параметр
конструктора. Api-key-сценарии этого файла (401/403 с указанием
`KTALK_PERSONAL_API_KEY`, деградация `access-info`, полный/протухший scope-набор)
удалены — они закрывали ровно снятый режим, не сценарий, применимый к сессии.
Session-сценарии мигрированы на `KTalkAuthError.session_token=`/без `.scopes`.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


# --- FR-5: диагностика протухшего токена -------------------------------------------------


async def test_ac_fr5_2_401_session_mentions_session_token_var(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-5/2: 401 в session-режиме -> сообщение указывает на KTALK_SESSION_TOKEN."""
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.client import KTalkAuthError, KTalkClient

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(KTalkAuthError, match="KTALK_SESSION_TOKEN"):
            await client.list_recordings()


async def test_ac_fr5_2b_403_session_generic_access_denied_no_scope_concept(
    httpx_mock: HTTPXMock, base_url
):
    """Group B: 403 в session-режиме — общее «доступ запрещён», без понятия scope
    (ADR-025: scope был понятием ключа, `KTalkScopeError` больше не поднимается)."""
    httpx_mock.add_response(status_code=403)

    from ktalk_cli.client import KTalkAuthError, KTalkClient, KTalkScopeError

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await client.list_recordings()

    assert not isinstance(exc_info.value, KTalkScopeError)
    assert "scope" not in str(exc_info.value).lower()


async def test_ac_fr5_3_unparseable_error_body_still_readable_message(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-5/3: тело ошибки не парсится как JSON -> читаемое сообщение без сырого
    трейсбэка. ADR-025: миграция с `personal_api_key=` на `session_token=` —
    сценарий (текст ошибки не зависит от тела 401) не меняется."""
    httpx_mock.add_response(status_code=401, content=b"<html>not json</html>")

    from ktalk_cli.client import KTalkAuthError, KTalkClient

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await client.list_recordings()

    text = str(exc_info.value)
    assert "Traceback" not in text
    assert "<html>" not in text


# --- FR-11: диагностика токена (auth_status) ----------------------------------------------


async def test_ac_fr11_3_auth_status_session_mode_real_probe_not_fake(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-11/3: session-режим -> честный ответ, но проверка — реальный сетевой
    запрос (list_recordings(top=1)), а не имитация без обращения к сети. ADR-025:
    `AuthStatus.scopes` удалён из DTO — ассерт на нём снят, не заменён `AttributeError`."""
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        status = await client.get_auth_status()

    assert status.alive is True
    assert status.note  # явно объясняет отсутствие scope/expiredAt для сессии
    request = httpx_mock.get_request()
    assert request is not None
    assert "/api/recordings" in str(request.url)


async def test_auth_status_network_error_is_not_reported_as_dead_key(
    httpx_mock: HTTPXMock, base_url
):
    """Edge case: ошибка сети/таймаут при auth_status — отдельный класс отказа,
    не должна маскироваться под alive=False («токен мёртв»). ADR-025: миграция с
    `personal_api_key=` на `session_token=`."""
    httpx_mock.add_exception(httpx.ConnectTimeout("simulated network timeout"))

    from ktalk_cli.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(Exception):  # noqa: B017 — тип решает Dev, важно что это НЕ AuthStatus(alive=False)
            await client.get_auth_status()
