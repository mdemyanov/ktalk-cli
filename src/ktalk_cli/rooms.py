"""FR-17: чтение комнаты — маппер 18 полей + сетевой вызов вне `client.py` (гейт C13).

Вынесено свободной функцией по тому же приёму, что `auth.py::resolve_chat_channel`
применяет к клиенту, — не новый метод `KTalkClient`.
"""

from __future__ import annotations

from ktalk_cli.auth import quote_path_param
from ktalk_cli.client import KTalkClient
from ktalk_cli.contour_diagnostics import (
    TRANSIENT_ERRORS,
    diagnose_undocumented_failure,
    require_contract_field,
)

ROOM_FIELDS = (
    "roomName",
    "sessionHalls",
    "stageConferenceId",
    "moderators",
    "anonymousModerators",
    "allowAnonymous",
    "anonymousAccessExpirationDate",
    "anonymousAccessModifiedDate",
    "audioPolicy",
    "videoPolicy",
    "screenSharePolicy",
    "isModerator",
    "conferenceId",
    "sipSettings",
    "onlineUsers",
    "simultaneousTranslation",
    "chatChannelSettings",
    "maskingSettings",
)


def map_room(raw: dict) -> dict:
    require_contract_field(raw, "roomName", "get_room")  # якорь контракта
    return {field: raw.get(field) for field in ROOM_FIELDS}


async def get_room(client: KTalkClient, room_name: str) -> dict:
    """Читает конфигурацию комнаты по имени.

    ПОБОЧНЫЙ ЭФФЕКТ (ADR-006): сервер не различает существующее и ранее не
    встречавшееся имя — оба дают 200 с идентичной по форме заготовкой (Ф-45).
    Вызов с именем, которое в этом контуре ещё не читалось, создаёт объект
    комнаты (Ф-49); отменить средствами проекта нельзя (инструмента удаления
    нет). НЕ использовать эту операцию для проверки занятости/свободности
    имени — сам факт проверки создаёт занятость.
    """
    profile = client._profile_for("get_room")  # noqa: SLF001
    path = profile.path_template.format(room_name=quote_path_param(room_name))
    try:
        response = await client._client.get(path)  # noqa: SLF001
        client._classify(response)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "get_room", exc)
        raise  # недостижимо: diagnose_undocumented_failure всегда поднимает исключение
    return map_room(response.json())
