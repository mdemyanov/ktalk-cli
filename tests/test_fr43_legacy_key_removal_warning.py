"""AT-design: FR-43 — однократное предупреждение о снятой `KTALK_PERSONAL_API_KEY`.

Покрывает `openspec/specs/talk-api-auth-modes/spec.md`, требование «Presence of the
removed personal-key variable is never silent» (5 сценариев) — источник
`content/30-requirements/single-auth-mode.md` FR-43, issue #10.

Проверка ведётся ЧЕРЕЗ CLI (`ktalk_cli.cli.main`, `capsys`), не через прямой импорт
`warn_if_legacy_key_present` — поведение (что видит вызывающий на stderr), не
внутренняя точка вызова (ADR-025-spec называет функцию как один из возможных
вариантов реализации, не как контракт вызывающей стороны).

Красные по замыслу: сегодня в дереве нет никакого кода, печатающего предупреждение
об обнаружении `KTALK_PERSONAL_API_KEY` — переменная читается молча и используется
как credential. Тесты падают на `AssertionError` (отсутствие ожидаемой строки/
неверный счётчик), не на импорте — используются только существующие
`ktalk_cli.cli.main`/`Settings`.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pytest_httpx import HTTPXMock

MARKER = "KTALK_PERSONAL_API_KEY"


def _count_marker(text: str) -> int:
    return sum(1 for line in text.splitlines() if MARKER in line)


def test_fr43_1_warning_printed_once_for_single_request_command(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «The warning fires once per invocation...» (случай одного запроса):
    `auth-status` — один пробный запрос -> ровно одна строка предупреждения, команда
    завершается штатно (не блокируется предупреждением)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-legacy-1")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-active-warn-0001")
    httpx_mock.add_response(json={"recordings": []})  # проба list_recordings(top=1)

    from ktalk_cli.cli import main

    rc = main(["auth-status", "--json"])

    captured = capsys.readouterr()
    assert _count_marker(captured.err) == 1
    assert rc == 0


def test_fr43_2_warning_printed_once_not_per_request_multi_request_sync(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «The warning fires once per invocation, not once per request»:
    `sync` с пагинацией (2 HTTP-запроса за вызов) -> предупреждение всё равно одно.

    Фикстура — в форме api-key-пагинации (`entities`/`nextPageToken`), потому что
    СЕГОДНЯ (до FR-42) ключ ещё побеждает по приоритету, и именно эта ветка реально
    уйдёт в сеть дважды. После реализации FR-42 диспетчер всегда идёт по сессии
    (`skip`-пагинация, форма `{"recordings": [...]}`) — Dev обязан заменить форму
    фикстуры на session-пагинацию (полная страница `top` записей + пустая страница),
    иначе тест перестанет создавать более одного запроса не по вине FR-43."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-legacy-2")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-active-warn-0002")
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    today = date.today().isoformat()
    httpx_mock.add_response(
        json={
            "entities": [
                {"id": "r1", "title": "T", "createdDate": f"{today}T10:00:00Z", "duration": 60}
            ],
            "nextPageToken": "page-2",
        }
    )
    httpx_mock.add_response(json={"entities": [], "nextPageToken": None})  # конец пагинации

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    rc = main(["--db", str(db), "sync", "--days", "7"])

    captured = capsys.readouterr()
    assert len(httpx_mock.get_requests()) == 2  # действительно больше одного запроса
    assert _count_marker(captured.err) == 1
    assert rc == 0


def test_fr43_3_no_warning_when_variable_absent(monkeypatch, tmp_path, capsys):
    """Scenario «Absence of the variable produces no warning» — регрессия: нет
    переменной -> нет упоминания вовсе, на любой команде."""
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-active-warn-0003")

    from ktalk_cli.cli import main

    main(["--db", str(tmp_path / "r.db"), "create-meeting-preview", "--subject", "X"])

    captured = capsys.readouterr()
    assert MARKER not in captured.err
    assert MARKER not in captured.out


def test_fr43_4_warning_plus_config_error_when_no_session_credential_resolves(
    monkeypatch, tmp_path, capsys
):
    """Scenario «No session credential and the legacy variable set still yields the
    configuration error, plus the warning»: предупреждение печатается, И команда
    всё равно отказывает конфигурационной ошибкой (не подменяет отсутствие
    рабочего credential). Счётчик маркера остаётся 1 — если бы отказ ТОЖЕ называл
    `KTALK_PERSONAL_API_KEY` (FR-42 AC3 нарушена), счётчик стал бы 2."""
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-legacy-4")
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_cli.cli import main

    rc = main(["auth-status", "--json"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "KTALK_SESSION_TOKEN" in captured.err
    assert _count_marker(captured.err) == 1


def test_fr43_5_warning_never_leaks_variable_value_full_or_tail(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «The warning never carries the variable's value» — не целиком, не
    хвостом (частичным совпадением). Тест-носитель FR-43 AC4 требования: барьер
    `redact_secrets` + представительный сценарий, парный с `tests/test_secret_masking.py`."""
    secret = "pk-super-secret-tail-9f8e7d6c5b4a"
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", secret)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-active-warn-0005")
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    main(["auth-status", "--json"])

    captured = capsys.readouterr()
    assert secret not in captured.err
    assert secret not in captured.out
    tail = secret[-8:]
    assert tail not in captured.err
    assert tail not in captured.out
