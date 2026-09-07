"""Таблица «операция -> путь» (FR-6) + примитивы подстановки в путь. Вынесено из
`auth.py` (гейт C13 — самая длинная top-level декларация модуля превысила порог
при росте таблицы ADR-010/ADR-011).

ADR-025: таблица схлопнута из «операция -> режим -> профиль|None» в «операция ->
профиль|None» — единственный оставшийся режим авторизации (сессионный токен) не
с чем сравнивать, второе измерение убрано, не сужено до одного значения.

`auth.py` реэкспортирует эти имена — расположение импорта не влияет на
видимость атрибута модуля, тот же приём, что `client.py` уже применяет к
`auth.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

OPERATION_LABELS = {
    "list_archive": "архив",
    "get_room": "чтение комнаты",
    "get_calendar": "чтение календаря",
    "create_meeting": "создание встречи",
    "search_contacts": "поиск контактов",
    "cancel_meeting": "отмена встречи",
}


def quote_path_param(value: object) -> str:
    """SEC-001: квотирует значение перед подстановкой в `path_template.format(...)` —
    без этого "../" в recording_key/conference_key меняет фактический путь запроса
    (например, "../admin" схлопывает /api/recordings/../admin в /api/admin)."""
    return quote(str(value), safe="")


@dataclass(frozen=True)
class EndpointProfile:
    """Путь одной операции (ADR-025: `required_scope` снят — scope был понятием
    режима ключа, у сессии его нет и не будет)."""

    path_template: str
    mutating: bool = False  # ADR-008: session-режим шлёт доп. Authorization-заголовок


# Таблица «операция -> путь» (FR-6, схлопнута ADR-025). Отсутствие записи или
# значение None — управляемый отказ до сети, не голый 401/403.
OPERATION_PROFILES: dict[str, EndpointProfile | None] = {
    "list_recordings": EndpointProfile("/api/recordings"),
    "get_recording": EndpointProfile("/api/recordings/{key}"),
    "get_transcript": EndpointProfile("/api/recordings/{key}/transcript"),
    "get_summary": EndpointProfile("/api/recordings/v2/{key}/summary"),
    "get_summary_by_type": EndpointProfile("/api/recordings/{key}/summary/{summary_type}"),
    # ADR-003/ADR-025: архив никогда не имел рабочего пути под сессией (замер,
    # personal-api-key.md FR-6/FR-9) — снятие ключа не даёт ему нового пути, оно
    # снимает единственный режим, в котором путь у него вообще был.
    "list_archive": None,
    "get_conference": EndpointProfile("/api/conferencesHistory/{key}"),
    # Session-режим дообогащает дуальным источником (get_recording + get_conference),
    # не через выделенный путь — см. KTalkClient.get_full_participants. Профиля нет
    # намеренно: оркестрация решается на уровне метода, не таблицы.
    "get_participants_full": None,
    # FR-17: внутренний путь, вне спеки, регистронезависим (постановка §5, живой GET).
    "get_room": EndpointProfile("/api/rooms/{room_name}"),
    # FR-18: внутренний путь, вне спеки, подтверждён исчерпывающе под session
    # (Ф-17–Ф-31 RES-003).
    "get_calendar": EndpointProfile("/api/calendar"),
    "create_meeting": EndpointProfile(
        # ГИПОТЕЗА (mainpart-ktalk-mcp.md:192-193, RES-003 Ф-38, не проверено живым POST):
        # путь с префиксом /api — mainpart документирует base_url = f"{space_url}/api" и
        # использует /calendar относительно него; предыдущая запись без /api была ошибкой
        # прочтения этого источника (ADR-007), не проверенным решением. Следующий боевой
        # POST под новой санкцией владельца — единственная проверка.
        # ГИПОТЕЗА (ADR-008, DEV-005 §5, не проверено живым POST): запись может требовать
        # доп. заголовок Authorization: Session <token> — mutating=True добавляет его
        # поверх query, не вместо. Следующий боевой POST — единственная проверка.
        "/api/calendar",
        mutating=True,
    ),
    # ADR-010 §1: путь наблюдён живым HAR (RES-003 §5, Ф-53), read-операция.
    "search_contacts": EndpointProfile("/api/contacts"),
    # ADR-011 §1: симметрично create_meeting — Ф-50, mutating=True, тот же транспорт,
    # что ADR-009 подтвердил живым POST создания.
    "cancel_meeting": EndpointProfile("/api/calendar/{id}/cancel", mutating=True),
}
