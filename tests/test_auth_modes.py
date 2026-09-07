"""AT-design: авторизация — профиль эндпоинтов, сужено ADR-025.

ADR-025 снимает режим персонального API-ключа целиком: `AuthMode`, `Settings.
ktalk_personal_api_key`/`.auth_mode`, `KTalkClient(personal_api_key=...)`,
`SCOPE_LABELS` удалены. FR-1/FR-2/FR-3/NFR-2 этого файла (селектор режима,
заголовок `X-Auth-Token`, приоритет ключа) закрывали ровно снятый режим — удалены,
не мигрированы: сравнивать больше не с чем. FR-6 (профиль эндпоинтов) остаётся —
session-путь и отказ до сети на операции без профиля не меняются этим ADR
(`list_archive` не имел рабочего пути под сессией и до снятия ключа).
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


# --- FR-6: профиль эндпоинтов ------------------------------------------------------------


async def test_ac_fr6_1_session_mode_uses_internal_list_path(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """AC FR-6/1: список записей идёт по /api/recordings, не по Domain (путь,
    достижимый только под снятым режимом ключа)."""
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await client.list_recordings()

    request = httpx_mock.get_request()
    assert "/api/recordings" in str(request.url)
    assert "/api/Domain" not in str(request.url)


async def test_ac_fr6_3_operation_without_profile_refuses_before_network_call(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """AC FR-6/3: операция без рабочего пути под сессией (архив) -> явное сообщение
    «недоступна», не голый 401/403, и это решается ДО сети — httpx-мок не должен
    получить ни одного запроса."""
    from ktalk_cli.client import KTalkClient, OperationNotAvailableError

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(OperationNotAvailableError):
            await client.list_archive(from_date="2026-01-01", to_date="2026-02-01")

    assert httpx_mock.get_requests() == []


# --- ADR-008: EndpointProfile.mutating -------------------------------------------------


def test_endpoint_profile_mutating_defaults_to_false():
    from ktalk_cli.client import EndpointProfile

    profile = EndpointProfile("/api/recordings")
    assert profile.mutating is False


def test_only_create_and_cancel_meeting_profiles_are_mutating():
    """ADR-008 §1 + ADR-011 §1: `mutating=True` — только у `create_meeting` и
    `cancel_meeting` (вторая мутирующая операция, тот же барьер, не слабее
    первой), ни одна другая запись плоской таблицы (ADR-025) не меняется по
    умолчанию."""
    from ktalk_cli.client import OPERATION_PROFILES

    mutating_operations = {"create_meeting", "cancel_meeting"}
    for operation, profile in OPERATION_PROFILES.items():
        if profile is None:
            continue
        assert profile.mutating is (operation in mutating_operations), operation
