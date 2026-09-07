"""Файл session-токена — третий источник авторизации после `KTALK_PERSONAL_API_KEY`
и `KTALK_SESSION_TOKEN` (ADR-003 расширен: приоритет ключ -> env-сессия -> файл).

Зачем файл вообще нужен. Session-токен протухает и обновляется руками; окружение
для этого — плохой носитель: экспорт в `.zshrc` не доходит до MCP-сервера,
запущенного Claude Code, а `.env` привязан к рабочей директории. Файл лежит в
одном месте, переживает перезапуск обоих процессов и обновляется одной командой.

Каталог `ktalk-mcp/`, не `ktalk/`: в `ktalk/` живёт санкция на запись (ADR-016),
у неё другой жизненный цикл и другой владелец решения.

Права шире `0600` читаются как «файла нет» — тот же fail-closed барьер, что у
санкции записи (SEC-006). Это защита не от владельца учётной записи, а от другого
пользователя машины, которому файл стал доступен.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

# Наблюдаемый формат session-токена — одно слово из букв и цифр (боевой токен
# 2026-08-21: 20 символов; прецедент mainpart проверяет `^[A-Za-z0-9]{16,40}$`,
# см. research/mainpart-ktalk-mcp.md §«Авторизация», п.2). Верхняя граница поднята
# до 64 с запасом: узкая граница отвергла бы валидный токен, широкая — пропускает
# ровно то, что и должна отвергать (пути, JSON, куски команд из устаревшего буфера).
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{16,64}$")


def token_path() -> Path:
    """`KTALK_TOKEN_FILE` (полный путь) > `$XDG_CONFIG_HOME/ktalk-mcp/token` >
    `~/.config/ktalk-mcp/token`."""
    override = os.environ.get("KTALK_TOKEN_FILE")
    if override:
        return Path(override)
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or None
    root = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return root / "ktalk-mcp" / "token"


def file_mode() -> str | None:
    """Права файла как `0600` — для диагностики. `None`, если файла нет."""
    try:
        return format(stat.S_IMODE(token_path().stat().st_mode), "04o")
    except OSError:
        return None


def read_token() -> str | None:
    """Значение токена или `None` — если файла нет, он нечитаем, пуст или его
    права шире `0600`. Ни одна из этих причин не является ошибкой: вызывающая
    сторона просто переходит к следующему источнику (или к отказу конфигурации)."""
    path = token_path()
    try:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            return None
        raw = path.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    token = raw.strip()
    return token or None


def status_payload() -> dict:
    """Путь/права/пригодность файла токена одним словарём — единственная точка
    сборки, которую переиспользуют `cli_token.py::_cmd_status` и `cli_doctor.py`
    (ADR-026 spec §2: значение совпадает буквальным переиспользованием кода, не
    соглашением между двумя независимо написанными местами)."""
    mode = file_mode()
    return {
        "path": str(token_path()),
        "present": mode is not None,
        "mode": mode,
        "usable": read_token() is not None,
    }


def write_token(value: str) -> Path:
    """Пишет токен с правами `0600` в каталоге `0700` и возвращает путь.

    `os.replace` поверх временного файла: параллельно читающий процесс видит либо
    старый токен целиком, либо новый целиком, но никогда полупустой файл. Права
    выставляются до переименования — окна, в котором секрет лежит доступным всем,
    не существует.
    """
    token = value.strip()
    if not token:
        raise ValueError("Пустой токен: записывать нечего.")
    if not _TOKEN_RE.match(token):
        # Значение в текст ошибки не попадает: буфер обмена мог содержать чужой
        # секрет. Названы только длина и правило — этого хватает, чтобы понять,
        # что скопировано не то (находка живой проверки 2026-08-21).
        raise ValueError(
            f"Значение длиной {len(token)} символ(ов) не похоже на токен: "
            "ожидается одно слово из букв и цифр, 16-64 символа. "
            "Проверьте, что в буфере результат `copy(JSON.parse(localStorage.session).data.token)`."
        )

    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)

    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    path.chmod(0o600)
    return path
