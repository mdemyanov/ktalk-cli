"""Файл session-токена как третий источник авторизации.

Проверено живьём 2026-08-21 (сессия PM): значение
`JSON.parse(localStorage.session).data.token` побайтово совпадает с рабочим
`KTALK_SESSION_TOKEN` (sha256 обоих — `f20f629b40c2…`), читающий транспорт
(query `sessionToken`) им авторизуется. Единственное, чего не хватало, —
источника: `Settings` читала только окружение и `.env` в cwd, поэтому
`env -u KTALK_SESSION_TOKEN ktalk auth-status` отказывал кодом 1 при уже
лежащем на диске файле.

Красные по замыслу: модуля `ktalk_cli.token_file` и подкоманды `ktalk token`
не существует.

`XDG_CONFIG_HOME` подменён на tmp в `tests/conftest.py` — тесты не видят
настоящий токен машины и не пишут в настоящий `~/.config`.
"""

from __future__ import annotations

import json
import stat

import pytest


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# --- token_file: путь, запись, чтение -------------------------------------


def test_token_path_defaults_to_xdg_config_ktalk_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import token_path

    assert token_path() == tmp_path / "ktalk-mcp" / "token"


def test_token_path_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "elsewhere" / "tok"))
    from ktalk_cli.token_file import token_path

    assert token_path() == tmp_path / "elsewhere" / "tok"


def test_write_token_creates_private_file_and_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import write_token

    path = write_token("FIXTUREnotArealToken01")

    assert path.read_text(encoding="utf-8") == "FIXTUREnotArealToken01"
    assert _mode(path) == 0o600
    assert _mode(path.parent) == 0o700


def test_write_token_strips_surrounding_whitespace(monkeypatch, tmp_path):
    """`pbpaste > file` и `echo` дают разный хвост; токен один и тот же."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import read_token, write_token

    write_token("  FIXTUREnotArealToken01\n")

    assert read_token() == "FIXTUREnotArealToken01"


def test_write_token_rejects_empty_value(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import write_token

    with pytest.raises(ValueError):
        write_token("   \n")


def test_read_token_absent_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import read_token

    assert read_token() is None


def test_read_token_refuses_world_readable_file(monkeypatch, tmp_path):
    """Тот же барьер, что у санкции записи (SEC-006): права шире 0600 —
    файла как будто нет. Иначе секрет молча читается с диска, доступного
    другому пользователю машины."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import read_token, write_token

    path = write_token("FIXTUREnotArealToken01")
    path.chmod(0o644)

    assert read_token() is None


# --- Settings: приоритет источников ---------------------------------------


def test_settings_reads_token_file_when_env_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # чтобы не подхватился .env репозитория
    from ktalk_cli.config import Settings
    from ktalk_cli.token_file import write_token

    write_token("FIXTUREnotArealToken01")

    settings = Settings()
    assert settings.auth_credential == "FIXTUREnotArealToken01"


def test_env_session_token_wins_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "from-env")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_cli.config import Settings
    from ktalk_cli.token_file import write_token

    write_token("fileFILE0123456789")

    assert Settings().auth_credential == "from-env"


def test_token_from_file_is_masked_in_error_text(monkeypatch, tmp_path):
    """NFR-5: барьер маскирования строит Settings() сам — токен из файла обязан
    попадать под ту же маску, что и токен из окружения."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    from ktalk_cli.config import redact_secrets
    from ktalk_cli.token_file import write_token

    write_token("FIXTUREnotArealToken01")

    assert "FIXTUREnotArealToken01" not in redact_secrets("token=FIXTUREnotArealToken01")


# --- CLI: ktalk token set | status ----------------------------------------


def test_cli_token_set_reads_stdin_and_writes_private_file(monkeypatch, tmp_path, capsys):
    """`copy(...)` в DevTools -> `pbpaste | ktalk token set -` — ручного chmod нет."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.cli import main
    from ktalk_cli.token_file import token_path

    monkeypatch.setattr("sys.stdin", _FakeStdin("FIXTUREnotArealToken01\n"))
    rc = main(["token", "set", "-"])

    assert rc == 0
    assert token_path().read_text(encoding="utf-8") == "FIXTUREnotArealToken01"
    assert _mode(token_path()) == 0o600
    assert "FIXTUREnotArealToken01" not in capsys.readouterr().out


def test_cli_token_status_json_reports_present_without_leaking_value(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("FIXTUREnotArealToken01")
    rc = main(["token", "status", "--json"])

    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["present"] is True
    assert payload["mode"] == "0600"
    assert "FIXTUREnotArealToken01" not in out


def test_cli_token_status_absent_file_is_not_an_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.cli import main

    rc = main(["token", "status", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["present"] is False


def test_cli_token_status_flags_too_wide_permissions(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("FIXTUREnotArealToken01").chmod(0o644)
    rc = main(["token", "status", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["present"] is True
    assert payload["usable"] is False


def test_cli_token_does_not_open_the_registry(monkeypatch, tmp_path):
    """`token` — в `_REGISTRY_FREE_COMMANDS`: секрет к реестру отношения не имеет."""
    from ktalk_cli.cli import _REGISTRY_FREE_COMMANDS

    assert "token" in _REGISTRY_FREE_COMMANDS


class _FakeStdin:
    def __init__(self, data: str) -> None:
        self._data = data

    def read(self) -> str:
        return self._data

    def isatty(self) -> bool:
        return False


# --- формат значения (находка живой проверки 2026-08-21) -------------------


def test_write_token_rejects_value_that_is_not_a_token(monkeypatch, tmp_path):
    """Живая проверка: `pbpaste | ktalk token set -` с устаревшим буфером записала
    в файл путь к markdown-файлу и отрапортовала успехом. Токен — одно слово из
    букв и цифр (наблюдаемый формат: 20 символов, тот же класс, что у прецедента
    mainpart — `^[A-Za-z0-9]{16,40}$`). Всё остальное отвергается до записи: иначе
    единственный сигнал об ошибке — отказ авторизации спустя минуты."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import token_path, write_token

    with pytest.raises(ValueError):
        write_token("/Users/mdemyanov/Devel/ktalk-mcp/README.md")

    assert not token_path().exists()


def test_write_token_rejects_too_short_value(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.token_file import write_token

    with pytest.raises(ValueError):
        write_token("short")


def test_cli_token_set_bad_value_exits_nonzero_and_keeps_old_token(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    from ktalk_cli.cli import main
    from ktalk_cli.token_file import read_token, write_token

    write_token("FIXTUREnotArealToken01")
    rc = main(["token", "set", "/Users/mdemyanov/Devel/ktalk-mcp/README.md"])

    assert rc != 0
    assert "не похоже на токен" in capsys.readouterr().err
    assert read_token() == "FIXTUREnotArealToken01"
