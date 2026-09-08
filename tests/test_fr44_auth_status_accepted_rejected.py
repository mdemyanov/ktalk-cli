"""AT-design: FR-44 — `auth-status` различает принятое и отвергнутое значение.

Покрывает `openspec/specs/talk-api-auth-modes/spec.md`, требование «Auth-status
diagnosis distinguishes an accepted session token from a rejected one» (4 сценария,
включая «Probe rejected for permissions, not credential») + новую форму
`--json`-ответа (`{"alive": bool, "note": str|None}`, без `scopes`/`expired_at`)
названную ADR-025 «Решение» п.3. Источник — `content/30-requirements/single-auth-mode.md`
FR-44, issue #11, дефект `ktalk-mcp-qqc` (403 схлопывается в отказ токена).

Урок дерева 2026-09-04 (`content/lessons-learned.md`): признак в теле ответа без
эскалации в код возврата неотличим потребителем, читающим только код, от отсутствия
отказа — тест обязан утверждать ОБА канала отдельными assert'ами в одном сценарии
(не полагаться на то, что проверка одного канала подразумевает другой). Урок
действует в обе стороны (ADR-025-spec «Разведение 401/403…»): эскалация в код
возврата при живом токене — то же нарушение, что и молчание при настоящем отказе.

Красные по замыслу: сегодня `cmd_auth_status` (`cli_sync.py`) возвращает `0`
безусловно (не пробрасывает `status.alive`), а `--json`-ответ несёт `scopes`/
`expired_at` (`cli_sync.py`, `AuthStatus`, `auth.py`). `_auth_status_session`
(`client.py`) не перехватывает непарсящееся тело отдельно от `KTalkAuthError` — тест
4 падает на утечке сырого текста `json.JSONDecodeError`, не на импорте (имена не
меняются, `client.py`/`cli_sync.py` уже существуют). `_auth_status_session` также
не разбирает `exc.status_code` на пойманном `KTalkAuthError` — 403 схлопывается в
тот же вердикт `alive=False`, что и 401 (тесты `test_fr44_5_*`..`test_fr44_7_*`).
"""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock


def test_fr44_1_probe_accepted_alive_true_exit_zero_and_no_scope_fields(
    monkeypatch, httpx_mock: HTTPXMock
):
    """Scenario «Probe accepted» + форма ответа ADR-025: `alive: true`, код `0`, и
    ключи ответа — ровно `{"alive", "note"}`, без `scopes`/`expired_at` (постоянный
    `null` — нечестная форма, ADR-025 «Альтернативы»)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-accepted-0001")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    rc = main(["auth-status", "--json"])
    assert rc == 0


def test_fr44_1b_probe_accepted_json_shape_has_only_alive_and_note(
    monkeypatch, httpx_mock: HTTPXMock, capsys
):
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-accepted-0002")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    main(["auth-status", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert set(data.keys()) == {"alive", "note"}
    assert data["alive"] is True


def test_fr44_2_probe_rejected_401_signals_both_alive_and_exit_code(
    monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Probe rejected as invalid or expired (fixture, no live contour
    required)» — воспроизводится на фикстуре 401. Оба канала — поле `alive` в теле
    `--json` и код возврата процесса — обязаны сигналить отказ независимо друг от
    друга (урок 2026-09-04): один ассерт на каждый канал."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-rejected-0001")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    rc = main(["auth-status", "--json"])
    data = json.loads(capsys.readouterr().out)

    # Канал 1: поле в теле ответа.
    assert data["alive"] is not True
    # Канал 2: код возврата процесса — независимый ассерт, не производный от канала 1.
    assert rc != 0


def test_fr44_3_probe_rejected_note_does_not_claim_validity(
    monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Probe rejected...»: `note` не утверждает валидность значения —
    ни разу не встречается самостоятельное слово «валиден» (без «не» перед ним)."""
    import re

    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-rejected-0002")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    main(["auth-status", "--json"])
    data = json.loads(capsys.readouterr().out)

    note = data.get("note") or ""
    assert re.search(r"\bвалиден\b", note, re.IGNORECASE) is None


def test_fr44_4_unparsable_probe_body_yields_honest_result_not_raw_decode_error(
    monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Unparsable probe response still yields an honest, non-blocking
    result»: тело пробного запроса (200, не JSON) не должно поднять сырой
    `json.JSONDecodeError` до пользователя — `--json` обязан остаться валидным JSON
    с `alive` не `true`, не текстом «Ошибка: Expecting value...» на stderr."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-unparsable-0001")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(status_code=200, content=b"not json at all")

    from ktalk_cli.cli import main

    rc = main(["auth-status", "--json"])
    captured = capsys.readouterr()

    # Красный сегодня: `_auth_status_session` не ловит `ValueError` отдельно от
    # `KTalkAuthError` -> `json.JSONDecodeError` всплывает до `main()`'s generic
    # `except Exception`, stdout остаётся пустым, stderr несёт сырой текст ошибки.
    assert captured.out != "", "ожидается валидный --json на stdout, не пусто"
    data = json.loads(captured.out)
    assert data["alive"] is not True
    assert "Expecting value" not in captured.err
    assert "Traceback" not in captured.err
    assert rc != 0


_NOTE_403_VERBATIM = (
    "Доступ запрещён: у текущей сессии нет прав на пробную операцию (список "
    "записей). Токен при этом рабочий — обновлять его не нужно."
)


def test_fr44_5_probe_rejected_403_alive_true_and_exit_zero(
    monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Probe rejected for permissions, not credential (fixture, no live
    contour required)» — 403 на пробном запросе не отказ токена: `alive` остаётся
    `true`, код возврата остаётся `0`. Оба канала — отдельным ассертом (урок
    2026-09-04 действует и в эту сторону: эскалация в код возврата при живом
    токене — то же нарушение, что и молчание при настоящем отказе).

    Красный сегодня (дефект `ktalk-mcp-qqc`): `_auth_status_session` ловит
    `KTalkAuthError` без разбора `exc.status_code`, 403 даёт тот же вердикт, что
    401 — `alive: false`, `rc == 1`.
    """
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-forbidden-0001")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(status_code=403)

    from ktalk_cli.cli import main

    rc = main(["auth-status", "--json"])
    data = json.loads(capsys.readouterr().out)

    # Канал 1: поле в теле ответа — токен рабочий.
    assert data["alive"] is True
    # Канал 2: код возврата процесса — независимый ассерт, не производный от канала 1.
    assert rc == 0


def test_fr44_6_probe_rejected_403_note_is_verbatim_permission_gap(
    monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Probe rejected for permissions, not credential»: `note` называет
    нехватку прав дословно (BA-030) и явно не предлагает обновить токен —
    проверка дословного текста, не только присутствия подстроки (ADR-025-spec
    edge case «403 на пробном запросе внутри `ktalk doctor`»/«разводка 401/403»)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-forbidden-0002")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(status_code=403)

    from ktalk_cli.cli import main

    main(["auth-status", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["note"] == _NOTE_403_VERBATIM


def test_fr44_7_probe_rejected_403_note_differs_from_401_note(
    monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Malformed/masked-failure guard: 403 и 401 — разные причины отказа пробного
    запроса, `note` обязан их различать текстом, а не схлопывать в один и тот же
    вердикт (текущий баг `ktalk-mcp-qqc` — оба кода дают идентичный `note`
    «Токен сессии не прошёл проверку...»). Малое, но наблюдаемое поведение: без
    этого различения потребитель, читающий только `note`, не может отличить
    «токен мёртв» от «токену не хватает прав»."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-forbidden-0003")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(status_code=403)

    from ktalk_cli.cli import main

    main(["auth-status", "--json"])
    data_403 = json.loads(capsys.readouterr().out)

    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-forbidden-0003b")
    httpx_mock.add_response(status_code=401)

    main(["auth-status", "--json"])
    data_401 = json.loads(capsys.readouterr().out)

    assert data_403["note"] != data_401["note"]
