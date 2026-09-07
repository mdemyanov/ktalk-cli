"""AT-design: скачивание видеофайла записи (FR-7).

Покрывает: FR-7 AC-2 (кодирование имени качества, `900p` <-> `900 p`), AC-3 (ошибка при
незапрошенном качестве — читаемое сообщение со списком доступных), AC-4 (потоковая
передача). FR-7 AC-1 (session-режим, реальный поток скачивания) — ручная проверка на
боевом домене, зондом проверено только наличие поля `qualities[].fileUrl` (см. at-design.md).

Красные по замыслу: модуль `ktalk_cli.download` не существует.

Примечание об импортах: `QualityNotFoundError` — рабочее имя исключения (не зафиксировано
дословно ни в одной спеке); Dev волен назвать иначе — assert проверяет наличие текста
доступных качеств в сообщении, не точный класс исключения, кроме этого одного теста.
Сигнатура `build_download_url(recording_key, quality)` и `download_recording_file(client,
recording_key, target_path, quality)` — по client-modules-spec §3/ADR-003-spec бриф Dev п.5
(«build_download_url с URL-квотированием и нормализацией имени качества»); порядок
позиционных аргументов — по тексту спек, вызовы в тестах позиционные, чтобы не зависеть
от точных имён kwarg.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


# `build_download_url` (FR-7 AC-2, кодирование имени качества под снятым режимом
# ключа) удалена ADR-025 как мёртвый код — единственный (session) путь всегда
# берёт готовую ссылку из `qualities[].fileUrl`, URL не строится вручную.


async def test_ac_fr7_3_unknown_quality_gives_readable_message_with_available_list(
    httpx_mock: HTTPXMock, base_url, tmp_path
):
    """AC FR-7/3: запрошено качество, которого нет в списке доступных -> понятное
    сообщение с перечнем доступных качеств, а не необработанное исключение."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.download import download_recording_file

    httpx_mock.add_response(json=_fixture_json("recording-detail-with-qualities.json"))

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(Exception) as exc_info:
            await download_recording_file(client, "REC-DL-001", str(tmp_path / "out.mp4"), "4k")

    text = str(exc_info.value)
    assert "240p" in text or "900p" in text


async def test_download_refuses_to_follow_dangling_symlink_at_target_path(
    httpx_mock: HTTPXMock, base_url, tmp_path
):
    """Security review SEC-001: `target.exists()` следует за симлинками и возвращает
    `False` для «оборванного» симлинка (указывающего на несуществующий путь) — наивный
    `target.open("wb")` писал бы СКВОЗЬ такой симлинк в произвольное место, куда он
    указывает, минуя guard `overwrite=False`. `os.O_CREAT | os.O_EXCL` должен отказать
    атомарно вместо того, чтобы молча создать файл по месту назначения симлинка."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.download import download_recording_file

    httpx_mock.add_response(json=_fixture_json("recording-detail-with-qualities.json"))
    httpx_mock.add_response(content=b"payload")

    outside = tmp_path / "outside" / "evil_destination.bin"
    outside.parent.mkdir()
    target = tmp_path / "out.bin"
    target.symlink_to(outside)  # оборванный симлинк: outside ещё не существует

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(FileExistsError):
            await download_recording_file(client, "REC-DL-001", str(target), "900p")

    assert not outside.exists()


# Code review Р3 (epic-capability-pairing, DEV-003): «под api-key `download_
# recording_file` не валидирует качество» — сам предмет снят ADR-025 вместе с
# api-key-веткой `download.py`; единственный (session) путь всегда сверяет
# запрошенное качество со списком `qualities[]` (см. test_ac_fr7_3 выше).


async def test_ac_fr7_4_download_streams_to_disk_without_full_content_response(
    httpx_mock: HTTPXMock, base_url, tmp_path
):
    """AC FR-7/4: содержимое передаётся потоково — файл на диске корректен и полон для
    payload'а, который не помещался бы в один буфер разумного размера. Тест — достижимый
    автоматический прокси за «без буферизации целиком в памяти» (integration на моке,
    per ADR-003-spec test-pyramid); полная гарантия — предмет ревью реализации."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.download import download_recording_file

    payload = b"x" * (5 * 1024 * 1024)  # 5 MiB синтетический файл
    httpx_mock.add_response(json=_fixture_json("recording-detail-with-qualities.json"))
    httpx_mock.add_response(content=payload)

    target = tmp_path / "out.bin"
    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        result = await download_recording_file(client, "REC-DL-001", str(target), "900p")

    assert target.read_bytes() == payload
    assert result["bytes"] == len(payload)
