"""AT-design: FR-18 — чтение календаря (`ktalk_cli.calendar_reader`, расширение
`tools_meetings.py`).

Покрывает все AC FR-18 (нет заблокированных): окно <=7 дней (AC-1), окно >7 дней без
потерь/дублей (AC-2), отсутствие `start` отклоняется до сети (AC-3), потолок 100 на
сегмент даёт предупреждение (AC-4), фильтр `roomName` передаётся как есть (AC-5),
`query` не входит в публичный интерфейс (AC-6), текст не утверждает "ваш календарь"
(AC-7). Плюс: `split_window` boundary cases и решающая таблица `_fetch_segment`
(rooms-calendar-spec §5.3/§5.5), NFR-7 (fail-closed api-key).

Красные по замыслу: `ktalk_cli.calendar_reader` не существует.

ADR-022 (снятие MCP-слоя): MCP-инструментные проверки AC-3/AC-6 (`ktalk_list_calendar` как
инструмент) удалены вместе с `server.py` — сам факт (`start` обязателен, `query` не в схеме)
остаётся верным на уровне чистых функций `calendar_reader`/`client`, но больше не проверяется
здесь отдельным тестом (нет MCP-инструмента, для которого проверять регистрацию/схему).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


def _item(item_id: str, start: str = "2026-08-15T10:00:00+03:00") -> dict:
    """Синтетический элемент календаря — минимум для теста дедупа/потолка, не полный
    20-польный маппер (тот проверяется отдельно на фикстуре)."""
    return {"id": item_id, "roomName": "test-room-alpha", "start": start, "subject": "Синт."}


# --- split_window (чистая функция, §5.3) -----------------------------------------------


def test_split_window_exactly_7_days_gives_one_segment():
    from ktalk_cli.calendar_reader import split_window

    segments = split_window(date(2026, 8, 1), date(2026, 8, 7))
    assert segments == [(date(2026, 8, 1), date(2026, 8, 7))]


def test_split_window_8_days_gives_two_segments_7_plus_1():
    from ktalk_cli.calendar_reader import split_window

    segments = split_window(date(2026, 8, 1), date(2026, 8, 8))
    assert len(segments) == 2
    assert segments[0] == (date(2026, 8, 1), date(2026, 8, 7))
    assert segments[1] == (date(2026, 8, 8), date(2026, 8, 8))


def test_split_window_14_days_gives_two_segments_of_7():
    from ktalk_cli.calendar_reader import split_window

    segments = split_window(date(2026, 8, 1), date(2026, 8, 14))
    assert len(segments) == 2
    assert segments[0] == (date(2026, 8, 1), date(2026, 8, 7))
    assert segments[1] == (date(2026, 8, 8), date(2026, 8, 14))


def test_split_window_single_day_start_equals_end():
    from ktalk_cli.calendar_reader import split_window

    segments = split_window(date(2026, 8, 1), date(2026, 8, 1))
    assert segments == [(date(2026, 8, 1), date(2026, 8, 1))]


def test_split_window_segments_are_contiguous_no_gap_no_overlap():
    from ktalk_cli.calendar_reader import split_window

    segments = split_window(date(2026, 8, 1), date(2026, 8, 20))
    for (_, seg_end), (next_start, _) in zip(segments, segments[1:]):
        assert (next_start - seg_end).days == 1


# --- map_calendar_item (чистая функция, §5.4) -------------------------------------------


def test_calendar_item_fields_constant_has_20_documented_fields():
    from ktalk_cli.calendar_reader import CALENDAR_ITEM_FIELDS

    assert len(CALENDAR_ITEM_FIELDS) == 20


def test_map_calendar_item_preserves_undocumented_but_contractual_fields():
    """`meetId`/`urlParams` — вне документированной EmailCalendarItem, но часть
    контракта этой волны (ADR-004 п.3) — не отбрасываются."""
    from ktalk_cli.calendar_reader import map_calendar_item

    raw = _fixture_json("calendar-item-session.json")
    mapped = map_calendar_item(raw)

    assert mapped["meetId"] == "MEET-0001"
    assert mapped["urlParams"] == "?token=synthetic"


def test_map_calendar_item_tolerates_absent_documented_but_never_seen_fields():
    """Элемент без `recurrence`/`isCancelled`/`isAllDayEvent`/`externalMeeting`/
    `isPrivate`/`onlineUsersCount` — валиден, не ошибка маппера."""
    from ktalk_cli.calendar_reader import map_calendar_item

    raw = _fixture_json("calendar-item-session.json")
    for absent in (
        "recurrence",
        "isCancelled",
        "isAllDayEvent",
        "externalMeeting",
        "isPrivate",
        "onlineUsersCount",
    ):
        assert absent not in raw  # фикстура сама по себе не содержит их
    map_calendar_item(raw)  # не должно поднимать исключение


def test_map_calendar_item_missing_anchor_raises_contour_drift():
    from ktalk_cli.calendar_reader import map_calendar_item
    from ktalk_cli.contour_diagnostics import ContourDriftError

    with pytest.raises(ContourDriftError):
        map_calendar_item({"start": "2026-08-15T10:00:00+03:00"})  # roomName отсутствует


# --- AC-1 / AC-2: окно <=7 дней и >7 дней ------------------------------------------------


async def test_ac_fr18_1_window_within_7_days_returns_all_items_single_segment(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient

    httpx_mock.add_response(json={"items": [_item("E1"), _item("E2"), _item("E3")]})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))

    assert {i["id"] for i in result.items} == {"E1", "E2", "E3"}
    assert len(httpx_mock.get_requests()) == 1


async def test_ac_fr18_2_window_over_7_days_covers_full_period_without_loss_or_dup(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Окно 10 дней -> 2 сегмента (7+3): все элементы обоих сегментов присутствуют,
    без потерь и без дублей на стыке."""
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient

    segment1_items = [_item(f"E{i}") for i in range(1, 6)]  # E1..E5
    segment2_items = [_item(f"E{i}") for i in range(6, 9)]  # E6..E8
    httpx_mock.add_response(json={"items": segment1_items})
    httpx_mock.add_response(json={"items": segment2_items})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 10))

    ids = [i["id"] for i in result.items]
    assert len(ids) == 8
    assert len(set(ids)) == 8  # без дублей
    assert set(ids) == {f"E{i}" for i in range(1, 9)}  # без потерь
    assert len(httpx_mock.get_requests()) == 2


async def test_dedup_at_segment_boundary_same_id_in_two_adjacent_segments(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Событие ровно на границе двух сегментов, вернувшееся сервером в обоих ответах,
    остаётся ровно один раз в результате (rooms-calendar-spec «Дедуп на стыках»)."""
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient

    boundary = _item("EVT-BOUNDARY", start="2026-08-07T23:00:00+03:00")
    httpx_mock.add_response(json={"items": [_item("E1"), boundary]})
    httpx_mock.add_response(json={"items": [boundary, _item("E2")]})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 10))

    ids = [i["id"] for i in result.items]
    assert ids.count("EVT-BOUNDARY") == 1
    assert set(ids) == {"E1", "EVT-BOUNDARY", "E2"}


# --- AC-4: потолок 100 на сегмент --------------------------------------------------------


async def test_ac_fr18_4_segment_with_exactly_100_items_flags_incomplete(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Сегмент, вернувший ровно 100 элементов (фактический потолок Ф-21), не тихо
    усекается, а помечается предупреждением о возможной неполноте."""
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient

    items = [_item(f"E{i}") for i in range(100)]
    httpx_mock.add_response(json={"items": items})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))

    assert len(result.items) == 100
    assert len(result.incomplete_segments) == 1


async def test_segment_with_fewer_than_100_items_does_not_flag_incomplete(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient

    httpx_mock.add_response(json={"items": [_item("E1")]})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))

    assert result.incomplete_segments == []


# --- AC-5: фильтр roomName передаётся как есть -------------------------------------------


async def test_ac_fr18_5_room_name_filter_passed_through_to_server(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient

    httpx_mock.add_response(json={"items": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await get_calendar_window(
            client, date(2026, 8, 1), date(2026, 8, 7), room_name="test-room-alpha"
        )

    request = httpx_mock.get_request()
    assert "roomName=test-room-alpha" in str(request.url)


# --- AC-7: текст не утверждает "ваш календарь" --------------------------------------------


def test_ac_fr18_7_calendar_formatter_does_not_claim_personal_calendar():
    """Формулировка нейтральна ("запланированные встречи, видимые активной
    авторизации") до подтверждения принадлежности выдачи (Ф-30, открытый вопрос)."""
    from ktalk_cli.formatters import format_calendar

    text = format_calendar({"items": [_item("E1")], "incomplete_segments": []}).lower()
    assert "ваш календарь" not in text
    assert "личный календарь" not in text
    assert "my calendar" not in text
    assert "your calendar" not in text


# --- §5.5 решающая таблица `_fetch_segment` -----------------------------------------------


async def test_fetch_segment_200_items_absent_raises_contour_drift_without_correlation(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """200, `items` отсутствует -> ContourDriftError сразу, без лишнего сетевого
    вызова на корреляцию (форма контракта уже сломана, права/сеть ни при чём)."""
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contour_diagnostics import ContourDriftError

    httpx_mock.add_response(json={"unexpectedShape": True})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(ContourDriftError):
            await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))

    assert len(httpx_mock.get_requests()) == 1  # без контрольного вызова


async def test_fetch_segment_known_400_text_gives_plain_error_without_correlation(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """400 с текстом из каталога Ф-26 -> обычная валидационная ошибка, без лишнего
    сетевого вызова на корреляцию.

    ADR-017 п.6: `start > end` теперь отклоняется в `split_window` до сети (см.
    `test_fr39_calendar_inclusive_end.py::test_ac5_...`) — этот тест переключён на
    валидный `start < end` и другой известный 400-текст каталога Ф-26, чтобы
    по-прежнему бить в сеть и проверять решающую таблицу `_fetch_segment`."""
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient, KTalkError
    from ktalk_cli.contour_diagnostics import ContourDriftError

    httpx_mock.add_response(
        status_code=400, text="Период запроса не должен превышать 7 дней"
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkError) as exc_info:
            await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))
        assert not isinstance(exc_info.value, ContourDriftError)

    assert len(httpx_mock.get_requests()) == 1


async def test_fetch_segment_unknown_400_text_triggers_correlation_and_drift(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """400 с текстом ВНЕ каталога Ф-26 -> сигнал дрейфа, запускает корреляцию."""
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contour_diagnostics import ContourDriftError

    httpx_mock.add_response(status_code=400, text="Совершенно незнакомый текст ошибки")
    httpx_mock.add_response(json={"recordings": []})  # control call

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(ContourDriftError):
            await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))

    assert len(httpx_mock.get_requests()) == 2


def test_known_400_texts_catalog_matches_f26_dословно():
    from ktalk_cli.calendar_reader import KNOWN_400_TEXTS

    assert "Дата начала является обязательной для заполнения" in KNOWN_400_TEXTS
    assert "Период запроса не должен превышать 7 дней" in KNOWN_400_TEXTS
    assert "Дата окончания должна быть больше даты начала" in KNOWN_400_TEXTS
    assert "The field Take must be between 1 and 1000." in KNOWN_400_TEXTS


# NFR-7 (fail-closed api-key на `get_calendar`) снято ADR-025 вместе с режимом:
# `get_calendar` имеет ровно один (session) профиль в плоской таблице — сравнивать
# с api-key-веткой больше не с чем, тест закрывал ровно снятое сравнение.


async def test_fetch_segment_network_error_triggers_correlation_and_drift(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.calendar_reader import get_calendar_window
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contour_diagnostics import ContourDriftError

    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    httpx_mock.add_response(json={"recordings": []})  # control call

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(ContourDriftError):
            await get_calendar_window(client, date(2026, 8, 1), date(2026, 8, 7))
