"""DEV-002 волны 3 (сверка CLI/MCP §2а ADR-012): подкоманды `ktalk`, закрывающие
пробел — те же операции чтения, что 7 MCP-инструментов сущности «Запись»
(`ktalk_list_recordings`, `ktalk_get_recording`, `ktalk_get_transcript`,
`ktalk_get_summary`, `ktalk_get_summary_by_type`, `ktalk_get_participants`,
`ktalk_download_recording`), сегодня доступные только через MCP.

Красные по замыслу: нет qa-author стабов на эту задачу (не мейнлайн-фича, разбор
пробела покрытия ADR-012 §2а) — классический TDD Dev'а (см. `nauta:dev` skill,
раздел «Fallback mode»). `--json` == valid JSON stdout, ошибки — stderr + rc=1,
команды регистрируются в `_REGISTRY_FREE_COMMANDS` (не открывают SQLite).
"""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture(autouse=True)
def _session_env(monkeypatch):
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "test-session-token")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)


def test_content_commands_are_registry_free():
    from ktalk_cli.cli import _REGISTRY_FREE_COMMANDS

    for cmd in (
        "list-recordings",
        "get-recording",
        "get-transcript",
        "get-summary",
        "get-summary-type",
        "get-participants",
        "download-recording",
        "list-archive",
        "get-chat-messages",
        "list-calendar",
        "get-room",
    ):
        assert cmd in _REGISTRY_FREE_COMMANDS, cmd


def test_build_parser_registers_all_content_subcommands():
    from ktalk_cli.cli import build_parser

    parser = build_parser()
    parser.parse_args(["list-recordings"])
    parser.parse_args(["get-recording", "REC-1"])
    parser.parse_args(["get-transcript", "REC-1"])
    parser.parse_args(["get-summary", "REC-1"])
    parser.parse_args(["get-summary-type", "REC-1", "--type", "protocol"])
    parser.parse_args(["get-participants", "REC-1"])
    parser.parse_args(["download-recording", "REC-1", "--target", "/tmp/x.mp4"])
    parser.parse_args(["list-archive", "--from", "2026-01-01", "--to", "2026-01-07"])
    parser.parse_args(["get-chat-messages", "--recording-key", "REC-1"])
    parser.parse_args(["list-calendar", "--start", "2026-01-01", "--end", "2026-01-07"])
    parser.parse_args(["get-room", "room-1"])


# --- list-recordings ----------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_list_recordings_json_valid_and_contains_recordings(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(
        json={"recordings": [{"key": "REC-1", "name": "Синк", "startTime": "2026-01-01T10:00:00Z"}]}
    )

    rc = main(["list-recordings", "--json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["recordings"][0]["key"] == "REC-1"


# --- get-recording -------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_recording_json_valid(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"key": "REC-1", "name": "Синк"})

    rc = main(["get-recording", "REC-1", "--json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["key"] == "REC-1"


def test_get_recording_error_goes_to_stderr_with_nonzero_exit(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(status_code=401, json={})

    rc = main(["get-recording", "REC-1", "--json"])

    assert rc != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() != ""


# --- get-transcript (chunking parity with MCP tool) -----------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_transcript_json_default_returns_raw_json(httpx_mock: HTTPXMock, capsys):
    """`--no-verify-identity`: предмет теста — форма raw-JSON транскрипта, не NFR-17
    (ADR-023 §1 сделал сверку идентичности умолчанием — без флага здесь потребовался
    бы и мок `get_recording`; отдельное покрытие умолчания-включено —
    `tests/test_nfr17_identity_verification.py`)."""
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"status": "done", "tracks": []})

    rc = main(["get-transcript", "REC-1", "--json", "--no-verify-identity"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "done"


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_transcript_markdown_default(httpx_mock: HTTPXMock, capsys):
    """`--no-verify-identity` — см. комментарий у `test_get_transcript_json_default_
    returns_raw_json` выше: предмет здесь — markdown-рендер, не NFR-17."""
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"status": "done", "tracks": []})

    rc = main(["get-transcript", "REC-1", "--no-verify-identity"])

    assert rc == 0
    assert "Транскрипт" in capsys.readouterr().out


# --- get-summary / get-summary-type ----------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_summary_json_valid(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"shortSummary": {"chunks": []}, "protocol": {"chunks": []}})

    rc = main(["get-summary", "REC-1", "--json"])

    assert rc == 0
    json.loads(capsys.readouterr().out)


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_summary_type_json_valid(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"chunks": []})

    rc = main(["get-summary-type", "REC-1", "--type", "protocol", "--json"])

    assert rc == 0
    json.loads(capsys.readouterr().out)


# --- get-participants ------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_participants_json_valid(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"key": "REC-1", "participantsCount": 0, "participants": []})
    httpx_mock.add_response(json={"artifacts": {"participants": []}})

    rc = main(["get-participants", "REC-1", "--json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["participants"] == []


# --- download-recording ------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_download_recording_json_valid_and_writes_file(httpx_mock: HTTPXMock, capsys, tmp_path):
    from ktalk_cli.cli import main

    target = tmp_path / "rec.mp4"
    httpx_mock.add_response(
        json={
            "key": "REC-1",
            "qualities": [{"name": "900p", "fileUrl": "https://test.ktalk.ru/file/900p.mp4"}],
        }
    )
    httpx_mock.add_response(content=b"binary-content")

    rc = main(["download-recording", "REC-1", "--target", str(target), "--json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["path"] == str(target)
    assert target.read_bytes() == b"binary-content"


# --- list-archive -------------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_list_archive_refuses_before_network_call(httpx_mock: HTTPXMock, capsys, monkeypatch):
    """ADR-025 п.4: `list-archive` остаётся вызываемой командой, но архив никогда
    не имел рабочего пути под сессией (замер, personal-api-key.md FR-6/FR-9) —
    после снятия ключа отказывает громко и до сети на КАЖДЫЙ вызов, не притворяется
    успехом (было rc=0/пустой список под снятым режимом ключа)."""
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)

    from ktalk_cli.cli import main

    rc = main(["list-archive", "--from", "2026-01-01", "--to", "2026-01-07", "--json"])

    assert rc == 1
    assert httpx_mock.get_requests() == []
    assert "архив" in capsys.readouterr().err


# --- get-chat-messages --------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_chat_messages_requires_recording_or_conference_key(capsys):
    from ktalk_cli.cli import main

    rc = main(["get-chat-messages", "--json"])

    assert rc != 0
    assert capsys.readouterr().err.strip() != ""


# --- list-calendar -------------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_list_calendar_json_valid(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"items": []})

    rc = main(["list-calendar", "--start", "2026-01-01", "--end", "2026-01-07", "--json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["items"] == []
    assert out["incomplete_segments"] == []


# --- get-room ---------------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_get_room_json_valid(httpx_mock: HTTPXMock, capsys):
    from ktalk_cli.cli import main

    httpx_mock.add_response(json={"roomName": "room-1"})

    rc = main(["get-room", "room-1", "--json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["roomName"] == "room-1"
