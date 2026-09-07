"""AT-design: FR-47 — `create-meeting-preview` называет все непереданные поля
одним отказом.

Покрывает `openspec/specs/meeting-scheduling/spec.md`, требование «Every field whose
absence independently causes rejection is named together, not one at a time»
(4 сценария). Источник — `content/30-requirements/cli-diagnostics-completeness.md`
FR-47, issue #12. Регрессии (FR-13/NFR-9 «один недостающий параметр»,
«явный пустой список» и т.п.) остаются в `tests/test_meeting_body.py`, не
дублируются здесь.

Красные по замыслу: `build_meeting_body` (`meeting_body.py:143-146`) сегодня
поднимает `MissingFieldError` на ПЕРВОМ встреченном `None` — `.fields` (список,
ADR-026-spec §1) не существует вовсе, есть только `.field` (строка) — тесты 1, 4, 5
падают на `AttributeError`/неполном перечислении, не на импорте (`MissingFieldError`/
`build_meeting_body` уже существуют).
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

FULL_KWARGS = {
    "subject": "Синтетическая встреча",
    "start": "2026-08-15T10:00:00+03:00",
    "end": "2026-08-15T11:00:00+03:00",
    "timezone": "GMT+3",
    "room_name": "test-room-alpha",
    "required_attendee_keys": ["1001", "1002"],
    "description": "Синтетическое описание",
    "enable_auto_recording": True,
    "pin_code": "1234",
    "allow_anonymous": False,
}


def test_fr47_1_two_missing_fields_named_together_in_fields_attribute():
    """Scenario «Two or more unset required fields are named in one rejection»:
    `subject` и `timezone` оба не переданы -> `.fields` содержит ОБА имени JSON-полей
    одним отказом, не только первое встреченное (`subject`)."""
    from ktalk_cli.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["subject"] = None
    kwargs["timezone"] = None

    with pytest.raises(MissingFieldError) as exc_info:
        build_meeting_body(**kwargs)

    assert set(exc_info.value.fields) == {"subject", "timezone"}
    message = str(exc_info.value)
    assert "subject" in message
    assert "timezone" in message


def test_fr47_2_exactly_one_missing_field_message_unchanged_from_today():
    """Scenario «Exactly one unset field still produces today's single-field
    message» — сравнение СТРОКИ целиком (не только присутствия подстроки), чтобы
    Dev не расширил формулировку одиночного случая заодно с многопольным."""
    from ktalk_cli.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["subject"] = None

    with pytest.raises(MissingFieldError) as exc_info:
        build_meeting_body(**kwargs)

    assert str(exc_info.value) == (
        'Поле «subject» не передано явно вызывающим — запрос на создание встречи '
        "отклонён до сетевого вызова (NFR-9)."
    )


def test_fr47_3_timezone_format_error_not_folded_into_missing_fields_list():
    """Scenario «A format error on a present timezone is not folded into the
    missing-fields list»: все обязательные поля переданы, `timezone` — в неверном
    формате -> `TimezoneFormatError`, не `MissingFieldError`."""
    from ktalk_cli.meeting_body import TimezoneFormatError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["timezone"] = "Europe/Moscow"

    with pytest.raises(TimezoneFormatError):
        build_meeting_body(**kwargs)


def test_fr47_4_allow_anonymous_none_does_not_duplicate_expiration_field():
    """Edge case companion-спеки ADR-026 §2 (эксплицитно назван в брифе координатора):
    `allowAnonymous` сам отсутствует (уже в списке missing) и
    `anonymousAccessExpirationDate` тоже не передан -> второе поле НЕ дублируется в
    списке (условие `allow_anonymous is True` ложно, когда `allow_anonymous is None`)."""
    from ktalk_cli.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["allow_anonymous"] = None
    kwargs["anonymous_access_expiration"] = None

    with pytest.raises(MissingFieldError) as exc_info:
        build_meeting_body(**kwargs)

    assert exc_info.value.fields.count("allowAnonymous") == 1
    assert "anonymousAccessExpirationDate" not in exc_info.value.fields


def test_fr47_5_cli_no_arguments_names_every_required_field_same_exit_code_no_network(
    httpx_mock: HTTPXMock, tmp_path
):
    """Scenario «Aggregating the field list spends no network call and does not
    change the exit code» + issue #12 буквально («вызов без единого аргумента»):
    ни один сетевой запрос, код возврата не меняется (1, как и для одного поля), а
    текст отказа называет КАЖДОЕ обязательное поле."""
    from ktalk_cli.cli import main

    rc = main(["--db", str(tmp_path / "r.db"), "create-meeting-preview"])

    assert rc == 1
    assert httpx_mock.get_requests() == []


def test_fr47_5b_cli_no_arguments_stderr_names_every_required_field(
    httpx_mock: HTTPXMock, tmp_path, capsys
):
    """Часть того же сценария, выделена отдельно ради читаемого diff при падении:
    девять полей, каждое из которых само по себе сегодня вызывает `MissingFieldError`
    при полностью пустом вызове (`allow_anonymous`/`pin_code`/`required_attendee_keys`
    тоже `None` без соответствующих `--no-*` флагов)."""
    from ktalk_cli.cli import main

    main(["--db", str(tmp_path / "r.db"), "create-meeting-preview"])
    stderr = capsys.readouterr().err

    expected_fields = {
        "subject",
        "start",
        "end",
        "timezone",
        "roomName",
        "requiredAttendees",
        "allowAnonymous",
        "enableAutoRecording",
        "pinCode",
    }
    missing_from_message = {f for f in expected_fields if f not in stderr}
    assert not missing_from_message, (
        f"текст отказа не называет: {sorted(missing_from_message)}\nstderr={stderr!r}"
    )
