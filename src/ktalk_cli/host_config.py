"""Discovery, парсинг и валидация `.ktalk.toml` — конфигурации проекта-хозяина.

SA-003 (`content/40-architecture/ktalk-plugin-spec.md`), FR-20. Отдельный модуль
от `registry.py` (грандфазер заморожен на 562 строках). Не пишет файлы и не
создаёт каталоги — только читает и валидирует (границы спеки).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_KNOWN_TOP_LEVEL_KEYS = {"registry", "directories", "routing", "integrations"}
_CONFIG_FILE_NAME = ".ktalk.toml"


class HostConfigError(Exception):
    """`.ktalk.toml` не парсится TOML-синтаксисом или проваливает валидацию схемы.

    Именует конкретный файл и причину — процесс останавливается на этом шаге, не
    продолжает работу на дефолте молча (ktalk-plugin-spec.md, «Поведение при
    малформенном файле»).
    """


@dataclass
class HostConfig:
    """Распарсенный и провалидированный `.ktalk.toml`.

    Каждая секция — `dict`-подобная с `.get(...)`; отсутствующий ключ означает
    «не объявлен», не «объявлен пустым» (FR-20 AC-2/AC-3, FR-24 деградация).
    """

    registry: dict = field(default_factory=dict)
    directories: dict = field(default_factory=dict)
    routing: dict = field(default_factory=dict)
    integrations: dict = field(default_factory=dict)
    # FR-48: путь найденного файла — `doctor` и `config show` обязаны называть
    # один и тот же путь одним значением, не пересчитывать его дважды.
    path: Path | None = field(default=None)


def _validate_string_map(section_name: str, section: dict, path: Path) -> None:
    for key, value in section.items():
        if not isinstance(value, str):
            raise HostConfigError(
                f"{path}: {section_name}.{key} должен быть строкой, получено {type(value).__name__}"
            )


def load_host_config(path: str | Path) -> HostConfig:
    """Парсит и валидирует `.ktalk.toml` по указанному пути.

    Пустой/отсутствующий-по-ключам файл — валиден (FR-20 AC-2, boundary): каждая
    секция трактуется как отсутствующая по отдельности, не как ошибка.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HostConfigError(f"{path}: не удалось прочитать файл: {exc}") from exc

    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise HostConfigError(f"{path}: некорректный TOML-синтаксис: {exc}") from exc

    unknown = set(data.keys()) - _KNOWN_TOP_LEVEL_KEYS
    if unknown:
        raise HostConfigError(
            f"{path}: неизвестные секции {sorted(unknown)} "
            f"(ожидаются только {sorted(_KNOWN_TOP_LEVEL_KEYS)})"
        )

    registry = data.get("registry", {})
    directories = data.get("directories", {})
    routing = data.get("routing", {})
    integrations = data.get("integrations", {})

    for name, section in (
        ("registry", registry),
        ("directories", directories),
        ("routing", routing),
        ("integrations", integrations),
    ):
        if not isinstance(section, dict):
            raise HostConfigError(f"{path}: секция [{name}] должна быть таблицей")

    if "db_path" in registry and not isinstance(registry["db_path"], str):
        raise HostConfigError(f"{path}: registry.db_path должен быть строкой")
    _validate_string_map("directories", directories, path)
    _validate_string_map("routing", routing, path)
    if "qmd" in integrations and not isinstance(integrations["qmd"], bool):
        raise HostConfigError(f"{path}: integrations.qmd должен быть булевым")

    return HostConfig(
        registry=registry,
        directories=directories,
        routing=routing,
        integrations=integrations,
        path=Path(path),
    )


def discover_host_config(project_dir: str | Path | None = None) -> HostConfig | None:
    """Ищет и загружает `.ktalk.toml` (ktalk-plugin-spec.md, «Discovery»).

    1. `project_dir` (явный оверрайд, тот же контракт, что и `${CLAUDE_PROJECT_DIR}`)
       или `${CLAUDE_PROJECT_DIR}`, если задан, — конфиг ищется РОВНО по этому
       корню, обхода вверх нет.
    2. Иначе (голый CLI) — обход вверх от `cwd` до первого найденного
       `.ktalk.toml`, либо до первого каталога с `.git` (граница проекта), либо
       до корня файловой системы.
    3. Ничего не найдено -> `None`, не ошибка (FR-20 AC-2). Малформенный
       найденный файл -> `HostConfigError` доходит до вызывающей стороны, не
       гасится тихим откатом (FR-20 AC-3).
    """
    if project_dir is not None:
        root = Path(project_dir)
        candidate = root / _CONFIG_FILE_NAME
        return load_host_config(candidate) if candidate.is_file() else None

    claude_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if claude_project_dir:
        candidate = Path(claude_project_dir) / _CONFIG_FILE_NAME
        return load_host_config(candidate) if candidate.is_file() else None

    current = Path.cwd()
    while True:
        candidate = current / _CONFIG_FILE_NAME
        if candidate.is_file():
            return load_host_config(candidate)
        if (current / ".git").exists():
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent
