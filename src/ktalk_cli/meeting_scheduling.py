"""FR-13 §6.6: предпросмотр (без сети) + создание (ровно одна сетевая попытка).

`create_meeting` — свободная функция вне `client.py` (гейт C13), тем же приёмом,
что `rooms.get_room`/`calendar_reader._fetch_segment`.
"""

from __future__ import annotations

import logging

from ktalk_cli.auth import quote_path_param
from ktalk_cli.client import KTalkClient
from ktalk_cli.confirmation import ConfirmationStore
from ktalk_cli.contour_diagnostics import TRANSIENT_ERRORS, diagnose_undocumented_failure
from ktalk_cli.meeting_body import build_meeting_body, canonical_body_hash

logger = logging.getLogger(__name__)


class PreviewService:
    def __init__(self, store: ConfirmationStore) -> None:
        self._store = store

    def preview(self, **fields: object) -> tuple[dict, str]:
        """`build_meeting_body` -> `canonical_body_hash` -> `store.issue`. Без сети
        физически — не получает `KTalkClient` (структурная невозможность, не
        поведенческая)."""
        body = build_meeting_body(**fields)
        body_hash = canonical_body_hash(body)
        confirmation_id = self._store.issue(body_hash)
        return body, confirmation_id


async def create_meeting(client: KTalkClient, body: dict) -> dict:
    """Ровно одна сетевая попытка `POST /api/calendar`, без retry. ADR-007 п.3:
    оборачивается корреляционной диагностикой ADR-004, тем же приёмом, что
    `calendar_reader._fetch_segment` — сбой недокументированного пути неотличим
    от обычного auth/сетевого сбоя без контрольного вызова.

    ADR-009 §6 (пересматривает ADR-008 §1): на `profile.mutating` (сегодня только
    session-режим этой операции) заголовки `Authorization: Session <token>` +
    `X-Platform: web` отправляются ВМЕСТО query-параметра `sessionToken`, не
    поверх него — единственная известная рабочая конфигурация (снимок DevTools).
    Query вырезается точечно из уже построенного `httpx.Request`
    (`copy_remove_param`) — конструктор клиента (`client._client.params`,
    ADR-003) не трогается, следующий read-путь того же клиента снова несёт
    `sessionToken` в query как обычно. ГИПОТЕЗА до следующего боевого POST. Тело
    ответа 4xx/5xx читается до классификации и прикрепляется к перехваченному
    исключению атрибутом `response_body` (обрезано до 500 символов) — переживает
    прогон независимо от конфигурации `logging`, которой в проекте нет."""
    profile = client._profile_for("create_meeting")  # noqa: SLF001
    headers = (
        {"Authorization": f"Session {client._auth.credential}", "X-Platform": "web"}  # noqa: SLF001
        if profile.mutating
        else None
    )
    request = client._client.build_request(  # noqa: SLF001
        "POST", profile.path_template, json=body, headers=headers
    )
    if profile.mutating:
        request.url = request.url.copy_remove_param("sessionToken")
    try:
        response = await client._client.send(request)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо

    body_text = response.text[:500] if response.status_code >= 400 else None
    if body_text:
        logger.warning("create_meeting: HTTP %s, тело: %s", response.status_code, body_text)

    try:
        client._classify(response)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        # DEV-008: тело пустое ("") — это факт контура, отличный от "тело не
        # прикреплено вовсе" (той ветки, где ответа не было — сетевой сбой выше).
        # `if body_text:` терял этот факт при пустой строке.
        if body_text is not None:
            exc.response_body = body_text  # атрибут читает CLI/MCP на границе вывода
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо
    return response.json()


async def cancel_meeting(client: KTalkClient, *, id: str, reason: str = "") -> dict:
    """Ровно одна сетевая попытка `POST /api/calendar/{id}/cancel`, без retry —
    тот же контракт, что `create_meeting` (ADR-005 п.2). Транспорт (заголовки,
    отсутствие query) — тот же код, что `create_meeting`: `profile.mutating`
    общий признак, не специфичный для операции. `{id}` — обязательный
    `quote_path_param` (Ф-56): `+`/`/`/`=` меняют путь без квотирования."""
    profile = client._profile_for("cancel_meeting")  # noqa: SLF001
    path = profile.path_template.format(id=quote_path_param(id))
    headers = (
        {"Authorization": f"Session {client._auth.credential}", "X-Platform": "web"}  # noqa: SLF001
        if profile.mutating
        else None
    )
    request = client._client.build_request(  # noqa: SLF001
        "POST", path, json={"reason": reason}, headers=headers
    )
    if profile.mutating:
        request.url = request.url.copy_remove_param("sessionToken")
    try:
        response = await client._client.send(request)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "cancel_meeting", exc)
        raise  # недостижимо

    body_text = response.text[:500] if response.status_code >= 400 else None
    try:
        client._classify(response)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        if body_text is not None:
            exc.response_body = body_text
        await diagnose_undocumented_failure(client, "cancel_meeting", exc)
        raise  # недостижимо
    # Ф-57: успешная отмена отвечает 200 с ПУСТЫМ телом — `response.json()` на нём
    # падает, и необратимая выполненная операция докладывалась как «исход неизвестен».
    # Отличие от `create_meeting`, чей ответ несёт объект встречи.
    return response.json() if response.content else {}
