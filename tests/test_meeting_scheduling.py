"""AT-design: FR-13 — оркестрация предпросмотра/создания (`ktalk_cli.meeting_scheduling`).

Покрывает: предпросмотр не делает сетевых записей (ключевая AC волны — перехват
исходящих запросов, ноль записывающих вызовов), совпадение состава/значений полей
предпросмотра и реального тела создания, отсутствие авто-retry на сетевую ошибку
(ровно одна попытка записи), fail-closed api-key для `create_meeting` (NFR-7).

Красные по замыслу: `ktalk_cli.meeting_scheduling` не существует.
"""

from __future__ import annotations

import inspect
import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

# Дублирует FULL_KWARGS из test_meeting_body.py осознанно: `tests/` не пакет
# (нет `__init__.py`), кросс-модульный импорт между stub-файлами ненадёжен.
FULL_KWARGS = {
    "subject": "Синтетическая встреча",
    "start": "2026-08-15T10:00:00+03:00",
    "end": "2026-08-15T11:00:00+03:00",
    "timezone": "GMT+3",
    "room_name": "test-room-alpha",
    "required_attendee_keys": ["1001", "1002"],
    "description": "Синтетическое описание",
    "enable_auto_recording": True,
    "pin_code": "1234",
    "allow_anonymous": False,
}


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


def _store():
    from ktalk_cli.confirmation import ConfirmationStore

    return ConfirmationStore()


# --- Предпросмотр: ключевая AC волны — ноль сетевых записывающих вызовов ---------------


def test_preview_service_has_no_network_client_parameter():
    """`PreviewService.preview` физически не получает `KTalkClient` — структурная
    невозможность сетевого эффекта, не только поведенческая (ADR-005-spec §Компоненты)."""
    from ktalk_cli.meeting_scheduling import PreviewService

    params = set(inspect.signature(PreviewService.preview).parameters) - {"self"}
    assert "client" not in params


def test_ac_fr13_1_preview_performs_zero_network_calls(httpx_mock: HTTPXMock):
    """AC FR-13/1: режим предпросмотра не выполняет ни одного сетевого запроса
    (POST/PUT/PATCH/DELETE и вообще никакого) к API Толка."""
    from ktalk_cli.meeting_scheduling import PreviewService

    service = PreviewService(_store())
    body, confirmation_id = service.preview(**FULL_KWARGS)

    assert isinstance(body, dict)
    assert isinstance(confirmation_id, str)
    assert httpx_mock.get_requests() == []


# --- AC-2: предпросмотр и реальное создание дают одно и то же тело ---------------------


async def test_ac_fr13_2_preview_body_matches_body_sent_at_create(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import PreviewService, create_meeting

    service = PreviewService(_store())
    body, _confirmation_id = service.preview(**FULL_KWARGS)

    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, body)

    request = httpx_mock.get_request()
    assert request.method == "POST"
    import json as _json

    sent_body = _json.loads(request.content)
    assert sent_body == body


async def test_create_meeting_posts_to_api_calendar_path(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-007: путь с префиксом `/api` — согласован с `get_room`/`get_calendar`,
    прежняя запись без `/api` была ошибкой прочтения источника (mainpart), не
    намеренным решением."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(status_code=200, json={"id": "MEET-0001"})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, {"subject": "X"})

    request = httpx_mock.get_request()
    assert request.url.path == "/api/calendar"


# --- AC-6: нет авто-retry на сетевую ошибку ---------------------------------------------


async def test_ac_fr13_6_network_failure_does_not_trigger_automatic_retry(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """AC FR-13/6: сетевая ошибка/таймаут при создании -> инструмент не повторяет
    сам POST автоматически — ровно один фактический вызов на запись. ADR-007 п.3
    добавляет один контрольный GET (диагностика), тоже проваливается -> исходная
    сетевая ошибка, не `ContourDriftError` (edge case контракта QA-author)."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(httpx.ConnectError):
            await create_meeting(client, {"subject": "X"})

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[0].url.path == "/api/calendar"
    assert requests[1].url.path == "/api/recordings"


async def test_create_meeting_404_with_working_control_raises_contour_drift_error(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Edge case контракта QA-author: POST /api/calendar -> 404, контроль
    list_recordings(top=1) -> 200 -> `ContourDriftError`, не `KTalkNotFoundError`
    (ADR-007 п.3)."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contour_diagnostics import ContourDriftError
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=404,
        text="not found",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(ContourDriftError):
            await create_meeting(client, {"subject": "X"})


async def test_create_meeting_logs_4xx_body_without_changing_user_message(
    httpx_mock: HTTPXMock, base_url, session_token, caplog
):
    """Тело ответа на 4xx попадает в лог до классификации, само сообщение
    исключения (`KTalkNotFoundError`) не меняется — лог дополняет, не заменяет
    (ADR-007 п.3)."""
    import logging

    from ktalk_cli.client import KTalkClient, KTalkNotFoundError
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=404,
        text="устройство роутинга: путь не смаршрутизирован",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=500,
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with caplog.at_level(logging.WARNING):
            with pytest.raises(KTalkNotFoundError) as exc_info:
                await create_meeting(client, {"subject": "X"})

    assert str(exc_info.value) == "Ресурс не найден."
    assert "устройство роутинга: путь не смаршрутизирован" in caplog.text


# --- ADR-009 §6: заголовки вместо query на мутирующей операции session-режима ----------


async def test_adr009_create_meeting_sends_headers_without_session_token_in_query(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-009 §6 (пересматривает ADR-008 §1): `mutating=True` -> заголовки
    `Authorization: Session <token>` + `X-Platform: web` отправляются ВМЕСТО
    query-параметра `sessionToken` — единственная известная рабочая
    конфигурация (снимок DevTools)."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(status_code=200, json={"id": "MEET-0001"})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, {"subject": "X"})

    request = httpx_mock.get_request()
    assert request.headers.get("Authorization") == f"Session {session_token}"
    assert request.headers.get("X-Platform") == "web"
    assert "sessionToken" not in request.url.params
    assert session_token not in request.url.query.decode()


async def test_adr009_read_paths_of_same_client_keep_session_token_in_query_after_create_meeting(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-009 §6 / регресс ADR-003: `copy_remove_param` над `httpx.Request` не
    трогает `client._client.params` — read-путь того же клиента после
    `create_meeting` по-прежнему несёт `sessionToken` в query."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(status_code=200, json={"id": "MEET-0001"})
    httpx_mock.add_response(status_code=200, json={"recordings": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, {"subject": "X"})
        await client.list_recordings(top=1)

    requests = httpx_mock.get_requests()
    assert requests[0].url.path == "/api/calendar"
    assert "sessionToken" not in requests[0].url.params

    assert requests[1].url.path == "/api/recordings"
    assert requests[1].url.params.get("sessionToken") == session_token


async def test_adr009_401_error_message_does_not_leak_session_token(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """NFR-10: токен не попадает в текст исключения ни в одной ветке — заголовок
    `Authorization` несёт токен транспортно, но не должен всплывать в сообщении
    об ошибке, которое доходит до вывода CLI/MCP."""
    from ktalk_cli.client import KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=401,
        text="токен невалиден для этого пути",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkWriteAuthMismatchError) as exc_info:
            await create_meeting(client, {"subject": "X"})

    assert session_token not in str(exc_info.value)
    assert session_token not in (exc_info.value.response_body or "")


async def test_adr008_401_with_working_control_raises_write_auth_mismatch_not_contour_drift(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-008: POST /api/calendar -> 401, контроль list_recordings(top=1) -> 200 —
    `KTalkWriteAuthMismatchError`, не `ContourDriftError` (правка ADR-007 п.3)."""
    from ktalk_cli.client import KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=401,
        text="токен невалиден для этого пути",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkWriteAuthMismatchError) as exc_info:
            await create_meeting(client, {"subject": "X"})

    assert exc_info.value.response_body == "токен невалиден для этого пути"
    assert session_token not in str(exc_info.value)


async def test_dev008_empty_response_body_attached_as_empty_string_not_absent(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """DEV-008: тело пустое — это факт контура, не то же самое, что «тело не
    прикреплено» (transport-уровня ошибка, где ответа вовсе не было)."""
    from ktalk_cli.client import KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=401,
        text="",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkWriteAuthMismatchError) as exc_info:
            await create_meeting(client, {"subject": "X"})

    assert hasattr(exc_info.value, "response_body")
    assert exc_info.value.response_body == ""


async def test_dev007_control_call_does_not_inherit_cookie_from_failed_post(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """DEV-007: `client.list_recordings(top=1)` (контроль ADR-004) обязан быть
    независим от отказа, который он проверяет. `httpx.AsyncClient` без явной
    зачистки копит `Set-Cookie` между запросами одного инстанса — POST на
    `/api/calendar`, вернувший 401 вместе с cookie, поставил бы под сомнение
    независимость контроля, если бы эта cookie улетела в следующий GET на том же
    клиенте. Ровно этим объяснялась воспроизведённая расходимость: `auth-status`
    (свежий клиент, без cookie) видел `alive: True`, а контроль внутри уже
    отработавшего клиента иногда — нет."""
    from ktalk_cli.client import KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=401,
        headers={"Set-Cookie": "sid=stale-web-session; Path=/"},
        text="",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkWriteAuthMismatchError):
            await create_meeting(client, {"subject": "X"})

    requests = httpx_mock.get_requests()
    control_request = next(r for r in requests if r.url.path == "/api/recordings")
    assert "cookie" not in control_request.headers


# NFR-7 (fail-closed api-key на `create_meeting`) снято ADR-025 вместе с режимом:
# плоская таблица несёт один (session) профиль, api-key-ветку сравнивать не с чем.
