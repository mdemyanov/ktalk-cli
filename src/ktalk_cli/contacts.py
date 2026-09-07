"""ADR-010: резолюция участника встречи через справочник контактов
(`GET /api/contacts`) — маппер + сетевой вызов вне `client.py` (гейт C13).

Вынесено свободной функцией по тому же приёму, что `rooms.get_room`. Читающая
операция, не мутирует состояние — не оборачивается корреляционной диагностикой
ADR-004 (тот же класс, что `get_room`).
"""

from __future__ import annotations

from ktalk_cli.auth import _display_name
from ktalk_cli.client import KTalkClient

_TOP = 25


def _map_candidate(raw: dict) -> dict:
    return {
        "key": raw.get("key"),
        "name": _display_name(raw),
        "post": raw.get("post"),
    }


async def search_contacts(client: KTalkClient, query: str) -> list[dict]:
    """Один GET `/api/contacts` -> список кандидатов `{key, name, post}`.

    `top=25`, `fillInMeetingStatus=false`, `includeKiosks=true` — фиксированные
    константы компоновщика запроса (ADR-010-spec §«Интеграционные точки»), не
    параметры вызывающего в этой волне. Автовыбора нет: 0/1/>1 совпадений —
    решение оператора остаётся снаружи (см. `formatters.format_search_contacts`).
    """
    profile = client._profile_for("search_contacts")  # noqa: SLF001
    response = await client._client.get(  # noqa: SLF001
        profile.path_template,
        params={
            "query": query,
            "top": _TOP,
            "fillInMeetingStatus": "false",
            "includeKiosks": "true",
        },
    )
    client._classify(response)  # noqa: SLF001
    raw = response.json()
    return [_map_candidate(c) for c in raw.get("contacts") or []]
