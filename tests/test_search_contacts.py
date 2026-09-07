"""AT-design: ADR-010 — резолюция участника через справочник контактов
(`ktalk_cli.contacts` — предполагаемое имя нового модуля, симметрично
`ktalk_cli.rooms`; `search_contacts(client, query)` — свободная функция вне
`client.py`, гейт C13, по образцу `rooms.get_room`).

Покрывает контракт с QA-author ADR-010-spec: 0/1/>1 совпадений без автовыбора,
api-key fail-closed до сети, секреты не в выводе, структурная граница с
allow-list компоновщиком `build_meeting_body` (резолюция не просачивается
внутрь), запрос формируется с фиксированными `top=25`/`fillInMeetingStatus=
false`/`includeKiosks=true`.

Красные по замыслу: `ktalk_cli.contacts` не существует.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

FIXTURES_QUERY = "иванов"


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


def _candidate(key: str, surname: str, firstname: str, post: str = "") -> dict:
    return {
        "key": key,
        "firstname": firstname,
        "surname": surname,
        "patronymic": "",
        "post": post,
        "userType": "user",
        "contactType": "user",
        "hasEmail": True,
        "hasMobilePhone": False,
        "mobilePhone": None,
        "avatarUrl": None,
    }


# --- AC-10-1: 0 совпадений ---------------------------------------------------------------


async def test_ac_10_1_zero_matches_search_contacts_returns_empty_list(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contacts import search_contacts

    httpx_mock.add_response(json={"contacts": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        candidates = await search_contacts(client, "zzz-no-such-name-zzz")

    assert candidates == []


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_ac_10_1_zero_matches_cli_message_names_the_query_and_nonzero_exit(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """CLI `search-contacts --query "..."`: 0 совпадений -> текст называет сам
    запрос дословно и код возврата ненулевой."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "test-session-token")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"contacts": []})

    from ktalk_cli.cli import main

    rc = main(
        ["--db", "/nonexistent/does-not-exist.db", "search-contacts", "--query", "zzz-no-match"]
    )

    assert rc != 0
    captured = capsys.readouterr()
    assert "zzz-no-match" in captured.out + captured.err
    assert "ничего не найдено" in (captured.out + captured.err).lower()


# --- AC-10-2: ровно 1 совпадение ---------------------------------------------------------


async def test_ac_10_2_single_match_returns_one_candidate_with_key_name_post(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contacts import search_contacts

    httpx_mock.add_response(
        json={"contacts": [_candidate("668", "Иванов", "Иван", post="Разработчик")]}
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        candidates = await search_contacts(client, FIXTURES_QUERY)

    assert len(candidates) == 1
    assert candidates[0]["key"] == "668"
    assert "Иванов" in candidates[0]["name"]
    assert candidates[0]["post"] == "Разработчик"


# --- AC-10-3: >1 совпадений, без ранжирования ---------------------------------------------


async def test_ac_10_3_multiple_matches_returns_full_unranked_list_preserving_server_order(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Порядок кандидатов — как в ответе сервера, не пересортирован по
    «похожести» (ADR-010 п.3: автовыбор/ранжирование запрещены явно)."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contacts import search_contacts

    server_order = [
        _candidate("668", "Иванов", "Иван"),
        _candidate("101", "Иванова", "Мария"),
        _candidate("999", "Иванов", "Пётр"),
    ]
    httpx_mock.add_response(json={"contacts": server_order})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        candidates = await search_contacts(client, FIXTURES_QUERY)

    assert len(candidates) == 3
    assert [c["key"] for c in candidates] == ["668", "101", "999"]


# AC-10-4 (api-key fail-closed на `search_contacts`) снято ADR-025 вместе с
# режимом: плоская таблица несёт один (session) профиль, api-key-ветку сравнивать
# не с чем.


# --- AC-10-5: секреты не в выводе по всем веткам ------------------------------------------


async def test_ac_10_5_secret_not_in_zero_match_output(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contacts import search_contacts
    from ktalk_cli.formatters import format_search_contacts

    httpx_mock.add_response(json={"contacts": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        candidates = await search_contacts(client, FIXTURES_QUERY)

    text = format_search_contacts(candidates, query=FIXTURES_QUERY)
    assert session_token not in text


async def test_ac_10_5_secret_not_in_single_match_output(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contacts import search_contacts
    from ktalk_cli.formatters import format_search_contacts

    httpx_mock.add_response(json={"contacts": [_candidate("668", "Иванов", "Иван")]})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        candidates = await search_contacts(client, FIXTURES_QUERY)

    text = format_search_contacts(candidates, query=FIXTURES_QUERY)
    assert session_token not in text


async def test_ac_10_5_secret_not_in_multi_match_output(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contacts import search_contacts
    from ktalk_cli.formatters import format_search_contacts

    httpx_mock.add_response(
        json={
            "contacts": [
                _candidate("668", "Иванов", "Иван"),
                _candidate("101", "Иванова", "Мария"),
            ]
        }
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        candidates = await search_contacts(client, FIXTURES_QUERY)

    text = format_search_contacts(candidates, query=FIXTURES_QUERY)
    assert session_token not in text


# --- Структурные тесты: запрос, профиль, форматтер, компоновщик, реестр MCP/CLI ------------


async def test_search_contacts_sends_expected_get_request_with_fixed_top_and_flags(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contacts import search_contacts

    httpx_mock.add_response(json={"contacts": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await search_contacts(client, FIXTURES_QUERY)

    request = httpx_mock.get_request()
    assert request.url.path == "/api/contacts"
    params = request.url.params
    assert params.get("query") == FIXTURES_QUERY
    assert params.get("top") == "25"
    assert params.get("fillInMeetingStatus") == "false"
    assert params.get("includeKiosks") == "true"


def test_operation_profiles_search_contacts_session_present():
    from ktalk_cli.auth import OPERATION_PROFILES

    profile = OPERATION_PROFILES["search_contacts"]
    assert profile is not None
    assert profile.path_template == "/api/contacts"


def test_format_search_contacts_25_candidates_not_truncated():
    from ktalk_cli.formatters import format_search_contacts

    candidates = [
        {"key": str(1000 + i), "name": f"Синтетический {i}", "post": "тест"} for i in range(25)
    ]

    text = format_search_contacts(candidates, query=FIXTURES_QUERY)

    for candidate in candidates:
        assert candidate["key"] in text


def test_build_meeting_body_has_no_parameter_for_contact_search():
    """AC-10-6 / ADR-010 п.2: компоновщик тела принимает только готовые
    числовые `key` — ни `query`, ни объект клиента для поиска в сигнатуре нет."""
    import inspect

    from ktalk_cli.meeting_body import build_meeting_body, build_required_attendees

    body_params = set(inspect.signature(build_meeting_body).parameters)
    attendees_params = set(inspect.signature(build_required_attendees).parameters)

    for forbidden in ("query", "search", "client", "contact_query"):
        assert forbidden not in body_params
        assert forbidden not in attendees_params


def test_meeting_body_module_does_not_import_search_contacts():
    """Структурная гарантия ADR-005 (allow-list компоновщик) не расширяется
    сетевой зависимостью — `meeting_body.py` не импортирует `search_contacts`
    ни напрямую, ни через `contacts`/`client`-модуль поиска."""
    import inspect

    import ktalk_cli.meeting_body as mb

    source = inspect.getsource(mb)
    assert "search_contacts" not in source
    assert "import ktalk_cli.contacts" not in source
    assert "from ktalk_cli.contacts" not in source


def test_build_parser_registers_search_contacts_subcommand():
    from ktalk_cli.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["search-contacts", "--query", "x"])
    assert args.command == "search-contacts"
