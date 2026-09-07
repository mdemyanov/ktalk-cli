"""AT-design: секрет не логируется и не попадает в вывод (NFR-5).

Покрывает NFR-5 единственное AC через представительный набор ошибочных сценариев, как
требует его формулировка ("проверка отсутствия строки ключа в захваченном выводе по
представительному набору сценариев"): исключение клиента, generic-исключение сети,
CLI stderr (текстовый режим), CLI --json.

Красные по замыслу: сегодня `KTALK_PERSONAL_API_KEY` не существует вовсе (FR-1 не
реализован), поэтому сценарии ниже падают на отсутствии функциональности раньше, чем
успели бы проверить факт маскирования — это ожидаемо для стадии red.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

SECRET = "pk-supersecret-abcdef123456"
SESSION_SECRET = "sess-supersecret-abcdef123456"


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


async def test_secret_not_in_auth_error_message(httpx_mock: HTTPXMock, base_url):
    """Значение сессионного токена не появляется в тексте KTalkAuthError.

    ADR-025: единственный оставшийся credential — сессионный токен, миграция от
    `personal_api_key=` (снятый параметр конструктора)."""
    from ktalk_cli.client import KTalkAuthError, KTalkClient

    httpx_mock.add_response(status_code=401)

    async with KTalkClient(base_url=base_url, session_token=SECRET) as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await client.list_recordings()

    assert SECRET not in str(exc_info.value)


async def test_secret_not_in_generic_exception_str_or_repr(httpx_mock: HTTPXMock, base_url):
    """ADR-003/ADR-025: KTalkError строит текст из статичных строк, никогда из
    str(request.url)/request.headers — секрет не должен всплыть даже в repr исключения
    при непредвиденной сетевой ошибке."""
    from ktalk_cli.client import KTalkClient

    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    async with KTalkClient(base_url=base_url, session_token=SECRET) as client:
        with pytest.raises(Exception) as exc_info:
            await client.list_recordings()

    assert SECRET not in str(exc_info.value)
    assert SECRET not in repr(exc_info.value)


def test_secret_not_in_cli_text_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Значение ключа не попадает в stdout/stderr CLI при ошибке (текстовый режим)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    # ADR-025: сама переменная больше не credential — сетевой вызов (и 401 ниже)
    # достижим только под сессионным токеном; тест по-прежнему проверяет, что
    # значение СНЯТОЙ переменной (SECRET) не утекает, включая её однократное
    # предупреждение (FR-43), в присутствии рабочей сессии.
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-network-reachable-0001")
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "sync", "--days", "7"])

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_secret_not_in_cli_json_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Значение ключа не попадает в stdout/stderr CLI при ошибке, включая --json-вывод."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    # ADR-025: сама переменная больше не credential — сетевой вызов (и 401 ниже)
    # достижим только под сессионным токеном; тест по-прежнему проверяет, что
    # значение СНЯТОЙ переменной (SECRET) не утекает, включая её однократное
    # предупреждение (FR-43), в присутствии рабочей сессии.
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-network-reachable-0001")
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "sync", "--days", "7", "--json"])

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_session_secret_not_in_cli_text_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """`redact_secrets` маскирует ОБА поля независимо (цикл по
    `(ktalk_personal_api_key, ktalk_session_token)`) — представительный набор NFR-5/NFR-10
    выше гоняет только `KTALK_PERSONAL_API_KEY` через CLI до печати; без этого теста ветка
    `settings.ktalk_session_token` в `redact_secrets` остаётся непокрытой мутационно (найдено
    QA-runner: удаление этого элемента кортежа не красит ни один существующий тест, хотя
    session-режим — штатный путь эпика 0.5.0/0.6.0, не гипотетический)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", SESSION_SECRET)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "sync", "--days", "7"])

    captured = capsys.readouterr()
    assert SESSION_SECRET not in captured.out
    assert SESSION_SECRET not in captured.err


def test_session_secret_not_in_cli_json_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Тот же случай, что выше, в `--json`-режиме."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", SESSION_SECRET)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "sync", "--days", "7", "--json"])

    captured = capsys.readouterr()
    assert SESSION_SECRET not in captured.out
    assert SESSION_SECRET not in captured.err


def test_secret_not_in_auth_status_cli_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """`ktalk auth-status --json` (NEW команда) не утекает ключом даже на сетевой ошибке."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    # ADR-025: сама переменная больше не credential — сетевой вызов (и 401 ниже)
    # достижим только под сессионным токеном; тест по-прежнему проверяет, что
    # значение СНЯТОЙ переменной (SECRET) не утекает, включая её однократное
    # предупреждение (FR-43), в присутствии рабочей сессии.
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-network-reachable-0001")
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "auth-status", "--json"])

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_secret_not_in_settings_repr_or_str(monkeypatch):
    """Security review SEC-001: pydantic по умолчанию печатает значения ВСЕХ полей в
    `repr(settings)`/`str(settings)` — в отличие от `AuthContext`, который уже маскирует
    себя явно, `Settings` этого не делала. Секретные поля объявлены `Field(repr=False)`."""
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_cli.config import Settings

    settings = Settings()
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)


# --- NFR-10 (волна 0.6.0): расширяет NFR-5 на новые пути (комната/календарь/создание) --


async def test_nfr10_secret_not_in_get_room_error_message(httpx_mock: HTTPXMock, base_url):
    """Значение ключа не появляется в тексте ошибки при отказе `get_room`.

    Session-режим: `get_room` имеет ровно один (session) профиль в плоской таблице
    (ADR-025) — сетевой вызов реально происходит, замоканный 401 достижим.
    """
    from ktalk_cli.client import KTalkAuthError, KTalkClient
    from ktalk_cli.rooms import get_room

    httpx_mock.add_response(status_code=401)  # недокументированный путь: get_room
    httpx_mock.add_response(status_code=401)  # контрольный вызов ADR-004 (401/401 -> reraise)

    async with KTalkClient(base_url=base_url, session_token=SECRET) as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await get_room(client, "test-room-alpha")

    assert SECRET not in str(exc_info.value)


async def test_nfr10_secret_not_in_calendar_error_message(httpx_mock: HTTPXMock, base_url):
    """Значение ключа не появляется в тексте ошибки при отказе чтения календаря.

    Session-режим — тот же принцип, что у `get_room` выше: `get_calendar` имеет
    ровно один (session) профиль (ADR-025), 401 достижим."""
    from datetime import date

    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkAuthError, KTalkClient

    httpx_mock.add_response(status_code=401)  # недокументированный путь: get_calendar
    httpx_mock.add_response(status_code=401)  # контрольный вызов ADR-004 (401/401 -> reraise)

    async with KTalkClient(base_url=base_url, session_token=SECRET) as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))

    assert SECRET not in str(exc_info.value)


def test_nfr10_secret_not_in_create_meeting_preview_cli_output(
    tmp_path, monkeypatch, capsys
):
    """NFR-10: предпросмотр создания встречи не утекает ключом — даже без сети,
    предпросмотр читает Settings ленивым образом нигде, но проверяем на всякий
    случай через тот же CLI-барьер."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    main(
        [
            "--db",
            str(db),
            "create-meeting-preview",
            "--subject",
            "Синтетическая встреча",
            "--start",
            "2026-08-15T10:00:00+03:00",
            "--end",
            "2026-08-15T11:00:00+03:00",
            "--timezone",
            "GMT+3",
            "--room-name",
            "test-room-alpha",
            "--no-required-attendees",
            "--enable-auto-recording",
            "true",
            "--pin-code",
            "1234",
            "--allow-anonymous",
            "false",
        ]
    )

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_secret_redacted_from_unexpected_exception_via_cli_main(
    tmp_path, monkeypatch, capsys
):
    """Барьер-редактор (ADR-003 «SecretRedactor», ранее спроектирован, но не был вызван
    ниоткуда): даже если секрет случайно попадёт в текст исключения, НЕ являющегося
    `KTalkError`/`KTalkConfigError` (т.е. минующего специальный обработчик `cmd_sync`/
    `cmd_auth_status` и всплывающего через общий `except Exception` в `cli.py::main`),
    значение ключа не должно долететь до stderr в открытом виде."""
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    from ktalk_cli import cli

    def _boom(reg, args):
        raise RuntimeError(f"unexpected failure, credential was {SECRET}")

    monkeypatch.setitem(cli._HANDLERS, "list", _boom)

    db = tmp_path / "r.db"
    rc = cli.main(["--db", str(db), "list"])

    captured = capsys.readouterr()
    assert rc == 1
    assert SECRET not in captured.out
    assert SECRET not in captured.err
    assert "REDACTED" in captured.err


def test_session_token_redacted_from_unexpected_exception_via_cli_main(
    tmp_path, monkeypatch, capsys
):
    """NFR-10: барьер `redact_secrets` маскирует ОБА канала аутентификации.

    Близнец теста выше для `KTALK_SESSION_TOKEN`: ветка `settings.ktalk_session_token`
    в `config.py::redact_secrets` иначе не упражняется ни одним тестом (находка QA
    волны 2, мутация #6 — удаление session-токена из списка маскирования оставляло
    весь suite зелёным).
    """
    monkeypatch.setenv("KTALK_SESSION_TOKEN", SECRET)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    from ktalk_cli import cli

    def _boom(reg, args):
        raise RuntimeError(f"unexpected failure, credential was {SECRET}")

    monkeypatch.setitem(cli._HANDLERS, "list", _boom)

    db = tmp_path / "r.db"
    rc = cli.main(["--db", str(db), "list"])

    captured = capsys.readouterr()
    assert rc == 1
    assert SECRET not in captured.out
    assert SECRET not in captured.err
    assert "REDACTED" in captured.err
