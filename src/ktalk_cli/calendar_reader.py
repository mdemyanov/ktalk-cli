"""FR-18: чтение календаря — сегментация 7-дневного окна, маппер 20 полей, дедуп на
стыках (rooms-calendar-spec §5). Свободные функции вне `client.py` (гейт C13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ktalk_cli.client import KTalkClient, KTalkError
from ktalk_cli.contour_diagnostics import (
    TRANSIENT_ERRORS,
    diagnose_undocumented_failure,
    require_contract_field,
)

CALENDAR_ITEM_FIELDS = (
    "busyType",
    "calendarSource",
    "description",
    "end",
    "id",
    "isRecurring",
    "location",
    "locationAttendee",
    "meetId",
    "onlineMeetingUrl",
    "onlineUsers",
    "optionalAttendees",
    "organizer",
    "requiredAttendees",
    "room",
    "roomName",
    "start",
    "stream",
    "subject",
    "urlParams",
)

# Ф-26, дословный каталог известных 400 — обычная валидационная ошибка вызывающего
# или сегментации, не сигнал дрейфа контура (не тратит лишний сетевой вызов на
# корреляцию).
KNOWN_400_TEXTS = frozenset(
    {
        "Дата начала является обязательной для заполнения",
        "Должна быть задана или дата окончания, или количество запрашиваемых элементов; "
        "Должна быть задана или дата окончания, или количество запрашиваемых элементов",
        "Период запроса не должен превышать 7 дней",
        "Дата окончания должна быть больше даты начала",
        "The field Take must be between 1 and 1000.",
    }
)

_PAGE_SIZE = 100


def split_window(start: date, end: date, *, max_days: int = 7) -> list[tuple[date, date]]:
    """Непересекающиеся сегменты <=`max_days` дней без пропусков и без перекрытия:
    следующий сегмент начинается на день позже конца предыдущего."""
    if start > end:
        # ADR-017 п.6: отказ до сети — единственная общая точка входа CLI/MCP.
        raise KTalkError("Дата начала окна не может быть позже даты конца.")
    segments: list[tuple[date, date]] = []
    seg_start = start
    while seg_start <= end:
        seg_end = min(seg_start + timedelta(days=max_days - 1), end)
        segments.append((seg_start, seg_end))
        seg_start = seg_end + timedelta(days=1)
    return segments


def map_calendar_item(raw: dict) -> dict:
    require_contract_field(raw, "roomName", "get_calendar")
    require_contract_field(raw, "start", "get_calendar")
    return {f: raw.get(f) for f in CALENDAR_ITEM_FIELDS}


def _is_known_400(text: str) -> bool:
    if text in KNOWN_400_TEXTS:
        return True
    return text.startswith("The value '") and text.endswith("is not valid for Start.")


@dataclass
class CalendarReadResult:
    items: list[dict] = field(default_factory=list)
    incomplete_segments: list[tuple[date, date]] = field(default_factory=list)


async def _fetch_segment(
    client: KTalkClient, seg_start: date, seg_end: date, room_name: str | None
) -> tuple[list[dict], bool]:
    profile = client._profile_for("get_calendar")  # noqa: SLF001
    # ADR-017 п.1-2: сервер держит `end` полуоткрытой ([start 00:00, end 00:00),
    # Ф-60 RES-004) — сегментация (`split_window`) оперирует включительными датами,
    # компенсация исключающей границы сервера — обязанность этого тонкого слоя.
    # Голая дата +1 день, не явное время конца суток (не зависит от часового базиса,
    # Ф-62 — см. ADR-017 п.2/7).
    params: dict = {
        "start": seg_start.isoformat(),
        "end": (seg_end + timedelta(days=1)).isoformat(),
        "take": _PAGE_SIZE,
    }
    if room_name is not None:
        params["roomName"] = room_name

    try:
        response = await client._client.get(profile.path_template, params=params)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "get_calendar", exc)
        raise  # недостижимо

    if response.status_code == 400:
        text = response.text
        if _is_known_400(text):
            raise KTalkError(text)  # валидационная ошибка вызывающего/сегментации
        await diagnose_undocumented_failure(client, "get_calendar", KTalkError(text))
        raise AssertionError("недостижимо")  # diagnose_undocumented_failure всегда поднимает

    try:
        client._classify(response)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "get_calendar", exc)
        raise  # недостижимо

    payload = response.json()
    if "items" not in payload:
        from ktalk_cli.contour_diagnostics import ContourDriftError

        raise ContourDriftError("get_calendar", "поле «items» отсутствует в ответе 200.")
    items = payload["items"]
    return items, len(items) >= _PAGE_SIZE


async def get_calendar_window(
    client: KTalkClient, start: date, end: date, *, room_name: str | None = None
) -> CalendarReadResult:
    result = CalendarReadResult()
    seen: set[str | tuple] = set()
    for seg_start, seg_end in split_window(start, end):
        items, incomplete = await _fetch_segment(client, seg_start, seg_end, room_name)
        if incomplete:
            result.incomplete_segments.append((seg_start, seg_end))
        for raw in items:
            key = raw.get("id") or (raw.get("meetId"), raw.get("start"))
            if key in seen:
                continue
            seen.add(key)
            result.items.append(map_calendar_item(raw))
    return result
