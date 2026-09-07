"""AT-design: ADR-011 — отмена встречи (`POST /api/calendar/{id}/cancel`).

Покрывает контракт с QA-author ADR-011-spec: привязка подтверждения к тройке
(операция, id, reason) — не к голому телу (критический AC-11-1: подтверждение
для одной встречи не проходит для другой при том же `reason`); квотирование
`{id}` с `+`/`/`/`=` (Ф-56, регресс SEC-001 на новом типе идентификатора);
транспорт mutating (заголовки, отсутствие query, ADR-009); отсутствие
авто-retry; предпросмотр без единого сетевого вызова (перехват
`httpx.AsyncClient.send`); `update_meeting` вне периметра -> управляемый отказ,
не `KeyError`. (Проверка «отсутствие мутирующего MCP-инструмента для отмены»
удалена ADR-022 вместе с MCP-слоем целиком — вопрос снят фактом отсутствия
самого MCP-сервера, не только инструмента.)

Расположение сетевого шага `cancel_meeting` — решение Dev (ADR-011-spec §3).
Здесь он импортируется из `ktalk_cli.meeting_scheduling` (симметрично
`create_meeting`); `ktalk_cli.meeting_cancel` держит чистые функции
(`build_cancel_confirmation_payload`, `CancelPreviewService`). См.
«Допущения» в at-design-contacts-and-cancel.md — если Dev выберет другое
расположение, правка одной строки импорта на тест.

Красные по замыслу: `ktalk_cli.meeting_cancel` не существует, `cancel_meeting`
не существует в `ktalk_cli.meeting_scheduling`.
"""

from __future__ import annotations

import inspect
import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

# Синтетический base64 Exchange-подобный id, несущий все три символа Ф-56
# одновременно (+, /, =) — не боевой id владельца (правило анонимизации).
SYNTHETIC_ID_WITH_SPECIAL_CHARS = "AAAA+BBBB/CCCC=="
SIMPLE_ID = "synthetic-id-0001"


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


def _store():
    from ktalk_cli.confirmation import ConfirmationStore

    return ConfirmationStore()


# --- build_cancel_confirmation_payload: предмет хеша, не тело запроса --------------------


def test_build_cancel_confirmation_payload_shape():
    from ktalk_cli.meeting_cancel import build_cancel_confirmation_payload

    payload = build_cancel_confirmation_payload(id=SIMPLE_ID, reason="встреча переносится")

    assert payload == {
        "operation": "cancel_meeting",
        "id": SIMPLE_ID,
        "reason": "встреча переносится",
    }


def test_build_cancel_confirmation_payload_default_reason_is_empty_string():
    from ktalk_cli.meeting_cancel import build_cancel_confirmation_payload

    payload = build_cancel_confirmation_payload(id=SIMPLE_ID)

    assert payload["reason"] == ""


# --- CancelPreviewService: ноль сети, структурная невозможность --------------------------


def test_cancel_preview_service_has_no_network_client_parameter():
    from ktalk_cli.meeting_cancel import CancelPreviewService

    params = set(inspect.signature(CancelPreviewService.preview).parameters) - {"self"}
    assert "client" not in params


def test_cancel_preview_performs_zero_network_calls(httpx_mock: HTTPXMock):
    """Доказано перехватом транспорта (`httpx_mock.get_requests()`), не чтением
    кода — тот же приём, что `test_ac_fr13_1_preview_performs_zero_network_calls`
    для создания."""
    from ktalk_cli.meeting_cancel import CancelPreviewService

    service = CancelPreviewService(_store())
    payload, confirmation_id = service.preview(id=SIMPLE_ID, reason="x")

    assert isinstance(payload, dict)
    assert isinstance(confirmation_id, str)
    assert httpx_mock.get_requests() == []


def test_cancel_preview_two_issues_of_same_payload_give_different_confirmation_ids():
    from ktalk_cli.meeting_cancel import CancelPreviewService

    service = CancelPreviewService(_store())

    _payload1, id1 = service.preview(id=SIMPLE_ID, reason="x")
    _payload2, id2 = service.preview(id=SIMPLE_ID, reason="x")

    assert id1 != id2


def test_cancel_match_false_for_unknown_confirmation_id():
    from ktalk_cli.meeting_body import canonical_body_hash
    from ktalk_cli.meeting_cancel import build_cancel_confirmation_payload

    store = _store()
    payload = build_cancel_confirmation_payload(id=SIMPLE_ID, reason="x")
    payload_hash = canonical_body_hash(payload)

    assert store.match("never-issued-id-invented-by-caller", payload_hash) is False


# --- AC-11-1: привязка хеша к id — критический тест ---------------------------------------


def test_ac_11_1_confirmation_issued_for_id_a_does_not_match_id_b_same_reason():
    """Ключевая гарантия ADR-011 п.2: подтверждение, выданное для одной
    встречи, не проходит для другой при том же `reason` — голый хеш тела
    `{"reason": reason}` без `id` совпал бы всегда (особенно при
    `reason=""`, единственном наблюдённом образце). Хеш обязан быть построен
    над `{"operation", "id", "reason"}`, не над одним `reason`."""
    from ktalk_cli.meeting_body import canonical_body_hash
    from ktalk_cli.meeting_cancel import build_cancel_confirmation_payload

    store = _store()
    payload_a = build_cancel_confirmation_payload(id="meeting-A", reason="x")
    confirmation_id_a = store.issue(canonical_body_hash(payload_a))

    payload_b = build_cancel_confirmation_payload(id="meeting-B", reason="x")
    hash_b = canonical_body_hash(payload_b)

    assert store.match(confirmation_id_a, hash_b) is False


def test_ac_11_1_via_cancel_preview_service_end_to_end():
    """Тот же сценарий на уровне `CancelPreviewService` целиком (не только
    компоновщика), чтобы поймать регресс, если Dev захешировал бы что-то
    иное внутри `preview`, чем `build_cancel_confirmation_payload`."""
    from ktalk_cli.meeting_body import canonical_body_hash
    from ktalk_cli.meeting_cancel import CancelPreviewService, build_cancel_confirmation_payload

    store = _store()
    service = CancelPreviewService(store)

    _payload_a, confirmation_id_a = service.preview(id="meeting-A", reason="x")
    hash_b = canonical_body_hash(build_cancel_confirmation_payload(id="meeting-B", reason="x"))

    assert store.match(confirmation_id_a, hash_b) is False


# --- AC-11-2: квотирование {id} с +, /, = --------------------------------------------------


async def test_ac_11_2_cancel_meeting_quotes_id_with_plus_slash_equals(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Ф-56: без `quote_path_param` путь молча собьётся — синтетический id
    несёт все три спецсимвола base64 Exchange одновременно."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import cancel_meeting

    httpx_mock.add_response(status_code=200, json={})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await cancel_meeting(client, id=SYNTHETIC_ID_WITH_SPECIAL_CHARS, reason="")

    request = httpx_mock.get_request()
    assert b"%2B" in request.url.raw_path
    assert b"%2F" in request.url.raw_path
    assert b"%3D" in request.url.raw_path
    assert b"AAAA+BBBB/CCCC==" not in request.url.raw_path
    # Опечатка счёта символов в исходном стабе (недостающий один "B"): quote() для
    # "AAAA+BBBB/CCCC==" даёт "AAAA%2BBBBB%2FCCCC%3D%3D" — %2B (эскейп "+") плюс
    # все 4 литеральных "B" дают пять подряд "B" после "%2", не четыре. Зафиксировано
    # в content/60-implementation/dev-010-contacts-and-cancel.md.
    assert request.url.raw_path == b"/api/calendar/AAAA%2BBBBB%2FCCCC%3D%3D/cancel"


async def test_cancel_meeting_posts_to_expected_path(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import cancel_meeting

    httpx_mock.add_response(status_code=200, json={})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await cancel_meeting(client, id=SIMPLE_ID, reason="")

    request = httpx_mock.get_request()
    assert request.url.path == f"/api/calendar/{SIMPLE_ID}/cancel"
    assert request.method == "POST"


# --- AC-11-3/AC-11-4: reason по умолчанию "" / непустой ------------------------------------


async def test_ac_11_3_default_empty_reason_sends_empty_string_in_body(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Ф-50: единственная подтверждённая живым запросом конфигурация."""
    import json as _json

    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import cancel_meeting

    httpx_mock.add_response(status_code=200, json={})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await cancel_meeting(client, id=SIMPLE_ID)

    request = httpx_mock.get_request()
    sent_body = _json.loads(request.content)
    assert sent_body == {"reason": ""}


async def test_ac_11_4_non_empty_reason_included_verbatim_in_payload_and_body(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Путь не проверен живым POST — тест на построение payload/тела, не на
    исход сервера (ADR-011-spec явно запрещает утверждать код ответа)."""
    import json as _json

    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_cancel import build_cancel_confirmation_payload
    from ktalk_cli.meeting_scheduling import cancel_meeting

    reason = "встреча переносится на следующую неделю"
    payload = build_cancel_confirmation_payload(id=SIMPLE_ID, reason=reason)
    assert payload["reason"] == reason

    httpx_mock.add_response(status_code=200, json={})
    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await cancel_meeting(client, id=SIMPLE_ID, reason=reason)

    request = httpx_mock.get_request()
    sent_body = _json.loads(request.content)
    assert sent_body == {"reason": reason}


# --- Транспорт mutating: заголовки, без query (ADR-009) -------------------------------------


async def test_cancel_meeting_sends_mutating_headers_without_session_token_in_query(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import cancel_meeting

    httpx_mock.add_response(status_code=200, json={})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await cancel_meeting(client, id=SIMPLE_ID, reason="")

    request = httpx_mock.get_request()
    assert request.headers.get("Authorization") == f"Session {session_token}"
    assert request.headers.get("X-Platform") == "web"
    assert "sessionToken" not in request.url.params
    assert session_token not in request.url.query.decode()


# --- AC-11-5: отсутствие авто-retry ----------------------------------------------------------


async def test_ac_11_5_network_failure_does_not_trigger_automatic_retry_exactly_one_post_attempt(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Ровно одна попытка мутирующего вызова (`POST .../cancel`); второй
    запрос в паре — контрольный GET диагностики ADR-004
    (`list_recordings(top=1)`), не повтор POST — тот же паттерн, что
    `test_ac_fr13_6_network_failure_does_not_trigger_automatic_retry` для
    создания."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import cancel_meeting

    cancel_path = re.compile(rf"^{re.escape(base_url)}/api/calendar/{SIMPLE_ID}/cancel(\?.*)?$")
    control_path = re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$")
    httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=cancel_path)
    httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=control_path)

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(httpx.ConnectError):
            await cancel_meeting(client, id=SIMPLE_ID, reason="")

    requests = httpx_mock.get_requests()
    post_attempts = [r for r in requests if r.method == "POST"]
    assert len(post_attempts) == 1
    assert post_attempts[0].url.path == f"/api/calendar/{SIMPLE_ID}/cancel"


# NFR-7 (fail-closed api-key на `cancel_meeting`) снято ADR-025 вместе с режимом:
# плоская таблица несёт один (session) профиль, api-key-ветку сравнивать не с чем.


def test_operation_profiles_cancel_meeting_session_mutating():
    from ktalk_cli.auth import OPERATION_PROFILES

    profile = OPERATION_PROFILES["cancel_meeting"]
    assert profile is not None
    assert profile.path_template == "/api/calendar/{id}/cancel"
    assert profile.mutating is True


# --- AC-11-6: update_meeting вне периметра -> управляемый отказ, не KeyError ---------------


async def test_ac_11_6_profile_for_missing_update_meeting_raises_not_available_not_keyerror(
    base_url, session_token
):
    """ADR-011 п.5: `update_meeting` не реализуется этой волной, не входит в
    `OPERATION_PROFILES` вовсе (ключ отсутствует, не значение `None` для
    режима) — существующий общий механизм `_profile_for` уже даёт
    управляемый отказ на полностью отсутствующий ключ, отдельной реализации
    не требует."""
    from ktalk_cli.client import KTalkClient, OperationNotAvailableError

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(OperationNotAvailableError):
            client._profile_for("update_meeting")


def test_update_meeting_has_no_entry_in_operation_profiles():
    from ktalk_cli.auth import OPERATION_PROFILES

    assert "update_meeting" not in OPERATION_PROFILES


# --- Форматтер и секреты ----------------------------------------------------------------------


def test_format_cancel_preview_prints_id_reason_confirmation_id():
    from ktalk_cli.formatters import format_cancel_preview

    text = format_cancel_preview(
        {
            "payload": {"operation": "cancel_meeting", "id": SIMPLE_ID, "reason": "тест"},
            "confirmation_id": "conf-abc-123",
        }
    )

    assert SIMPLE_ID in text
    assert "тест" in text
    assert "conf-abc-123" in text


async def test_secret_not_in_cancel_meeting_error_message(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.meeting_scheduling import cancel_meeting

    cancel_path = re.compile(rf"^{re.escape(base_url)}/api/calendar/{SIMPLE_ID}/cancel(\?.*)?$")
    control_path = re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$")
    httpx_mock.add_response(status_code=401, text="токен невалиден для этого пути", url=cancel_path)
    httpx_mock.add_response(status_code=200, json={"recordings": []}, url=control_path)

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkWriteAuthMismatchError) as exc_info:
            await cancel_meeting(client, id=SIMPLE_ID, reason="")

    assert session_token not in str(exc_info.value)
    assert session_token not in (exc_info.value.response_body or "")


# --- Ф-57: 200 с пустым телом — живой факт боевой отмены 2026-08-19 -------------------------


async def test_cancel_meeting_returns_empty_dict_on_200_with_empty_body(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Боевая отмена 2026-08-19: сервер выполнил операцию и ответил 200 с пустым
    телом. Безусловный `response.json()` падал на `JSONDecodeError`, и CLI печатал
    «исход неизвестен» по успешной операции — худший вид ошибки для необратимого
    действия. Ф-50 фиксировала только код ответа, не наличие тела."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.meeting_scheduling import cancel_meeting

    httpx_mock.add_response(status_code=200, content=b"")

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await cancel_meeting(client, id=SIMPLE_ID, reason="")

    assert result == {}
