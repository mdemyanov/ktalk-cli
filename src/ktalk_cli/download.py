"""Потоковая запись видеофайла записи на диск (FR-7).

ADR-025: единственный (сессионный) путь — ссылка уже готова в `qualities[].fileUrl`
деталей записи. Api-key-путь (`build_download_url`, `DEFAULT_QUALITY`) удалён как
мёртвый код вместе со снятием режима ключа.

Политика записи на диск — базовый безопасный минимум (SA сознательно оставил её
открытой, полное ревью — DevSecOps): пишем только по явно переданному пути, не
угадываем и не создаём файлы в неожиданных местах, отказываем при попытке
перезаписать существующий файл без явного `overwrite=True`.
"""

from __future__ import annotations

import os
from pathlib import Path


class QualityNotFoundError(Exception):
    """Запрошенное качество недоступно для этой записи (FR-7 AC-3)."""


def _normalize_quality(quality: str) -> str:
    """`900p` и `900 p` -> одна и та же каноническая форма без пробела."""
    return quality.replace(" ", "").lower()


def _resolve_session_quality(qualities: list[dict], quality: str | None) -> tuple[str, str]:
    if not qualities:
        raise QualityNotFoundError("У записи нет доступных качеств скачивания.")
    by_normalized = {_normalize_quality(q.get("name", "")): q for q in qualities}
    wanted = _normalize_quality(quality) if quality else next(iter(by_normalized))
    match = by_normalized.get(wanted)
    if match is None:
        available = ", ".join(q.get("name", "?") for q in qualities)
        raise QualityNotFoundError(
            f"Качество «{quality}» недоступно для этой записи. Доступные: {available}."
        )
    return match.get("name", wanted), match["fileUrl"]


async def download_recording_file(
    client,
    recording_key: str,
    target_path: str,
    quality: str | None = None,
    *,
    overwrite: bool = False,
) -> dict:
    """Скачивает файл записи потоково, без буферизации целиком в памяти (FR-7 AC-4)."""
    detail = await client.get_recording(recording_key)
    resolved_quality, url = _resolve_session_quality(detail.get("qualities") or [], quality)

    target = Path(target_path)
    if target.exists() and not overwrite:
        # Быстрый отказ до сетевого вызова — сохраняет прежнее поведение/сообщение.
        raise FileExistsError(
            f"Файл уже существует: {target}. Укажите overwrite=True для перезаписи."
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    async with client.stream("GET", url) as response:
        client.check_response(response)
        # Security review SEC-001: `target.exists()` выше следует за симлинками и
        # возвращает False для «оборванного» симлинка (указывающего на
        # несуществующий путь) — наивный `target.open("wb")` в этом случае писал бы
        # СКВОЗЬ симлинк в произвольное место, куда указывает ссылка. Между
        # проверкой и записью есть и обычное TOCTOU-окно (сетевой вызов между ними).
        # `os.O_EXCL` с `os.O_CREAT` атомарно отказывает и на гонке, и на висящем
        # симлинке (POSIX). При `overwrite=True` поведение не меняется — перезапись
        # была осознанно запрошена вызывающим.
        flags = os.O_WRONLY | os.O_CREAT | (0 if overwrite else os.O_EXCL)
        try:
            fd = os.open(target, flags, 0o644)
        except FileExistsError as exc:
            raise FileExistsError(
                f"Файл уже существует: {target}. Укажите overwrite=True для перезаписи."
            ) from exc
        with os.fdopen(fd, "wb") as fh:
            async for chunk in response.aiter_bytes():
                fh.write(chunk)
                total += len(chunk)

    return {"path": str(target), "bytes": total, "quality": resolved_quality}
