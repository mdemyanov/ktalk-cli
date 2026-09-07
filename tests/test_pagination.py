"""AT-design: нормализация ответов и пагинация (FR-14, FR-9 AC-2).

Покрывает: FR-14 (AC-1, AC-2, AC-3 — включая регрессионный сценарий "top=1000 не должен
достигать сети" и "цикл не должен обрываться после первой страницы"), FR-9 (AC-2 — полное
вычитывание окна дат за пределами одной страницы), плюс boundary cases из ADR-003-spec:
пустая последняя страница vs короткая-но-непустая, nextPageToken: null vs отсутствующее
поле, полная последняя страница -> один лишний запрос по дизайну.

Красные по замыслу: `ktalk_cli.pagination` (модуль ещё не существует), клэмп top<=100 в
`_fetch_recordings`/`ktalk sync`, `client.list_archive(...)`, нормализаторы
`normalize_list_session`/`normalize_list_apikey` в `ktalk_cli.client`.

Примечание об импортах: сигнатура `skip_pages(fetch, page_size)` в тесте
`test_skip_pages_full_last_page_makes_one_extra_request` — рабочая гипотеза по
пседокоду client-modules-spec.md §5 (raw_fetch(skip, top) -> {"recordings": [...]});
если Dev спроектирует другой контракт вызова, это локальная правка теста, суть
проверяемого поведения (одна лишняя пустая страница на полной последней странице)
не меняется.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from pytest_httpx import HTTPXMock

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


# --- paginate_pages: чистая термination-логика (пседокод client-modules-spec §5) --------


async def test_paginate_pages_empty_first_page_returns_zero_pages():
    """Boundary: 0 записей в окне -> paginate_pages не должен упасть, вернуть 0 страниц."""
    from ktalk_cli.pagination import paginate_pages

    calls = []

    async def fetch_page(cursor):
        calls.append(cursor)
        return [], None

    pages = [p async for p in paginate_pages(fetch_page)]
    assert pages == []
    assert calls == [None]


async def test_paginate_pages_stops_on_falsy_cursor_after_yielding_items():
    """Условие остановки — items пуст ИЛИ next_cursor ложный, оба варианта проверяются."""
    from ktalk_cli.pagination import paginate_pages

    async def fetch_page(cursor):
        if cursor is None:
            return [{"id": "a"}], "next-1"
        return [{"id": "b"}], None

    pages = [p async for p in paginate_pages(fetch_page)]
    assert pages == [[{"id": "a"}], [{"id": "b"}]]


async def test_skip_pages_full_last_page_makes_one_extra_empty_request():
    """Edge case client-modules-spec: len(items) == page_size на последней реальной
    странице -> адаптер skip_pages делает ОДИН лишний запрос (страница пустая), по
    дизайну — тест подтверждает, что лишний запрос происходит и цикл корректно
    завершается (не бесконечный, не off-by-one)."""
    from ktalk_cli.pagination import paginate_pages, skip_pages

    calls = []

    async def raw_fetch(skip, top):
        calls.append(skip)
        if skip == 0:
            return {"recordings": [{"id": "a"}, {"id": "b"}]}
        return {"recordings": []}

    fetch_page = skip_pages(raw_fetch, page_size=2)
    pages = [p async for p in paginate_pages(fetch_page)]

    assert calls == [0, 2]
    assert pages == [[{"id": "a"}, {"id": "b"}]]


# --- FR-14: границы top и пагинация через skip (регрессия дефекта прода) ----------------


def test_ac_fr14_1_sync_never_sends_top_over_100(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock
):
    """AC FR-14/1: значение количества элементов на страницу никогда не выходит за
    границы 1-100 — регрессия дефекта top=1000 (зонд Ф-2, HTTP 400)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    rc = main(["--db", str(db), "sync", "--days", "7", "--json"])
    assert rc == 0

    request = httpx_mock.get_request()
    qs = parse_qs(urlparse(str(request.url)).query)
    assert 1 <= int(qs["top"][0]) <= 100


def test_ac_fr14_2_skip_pagination_continues_past_first_page_to_empty(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock
):
    """AC FR-14/2: клиент продолжает пагинацию через skip до пустой страницы, не
    полагаясь на отсутствующее поле токена следующей страницы — регрессия исходного
    дефекта (цикл ранее обрывался после первой страницы, зонд Ф-3)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    # Дата внутри окна --days: окно считается от сегодня, захардкоженная дата
    # неизбежно уезжает за порог и тест начинает падать со временем (Ф-15).
    inside = (date.today() - timedelta(days=1)).isoformat()
    full_page = {
        "recordings": [
            {"id": f"R{i}", "title": f"Rec {i}", "createdDate": f"{inside}T00:00:00Z",
             "duration": 60}
            for i in range(100)
        ]
    }
    httpx_mock.add_response(json=full_page)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    rc = main(["--db", str(db), "sync", "--days", "7", "--json"])
    assert rc == 0

    requests = httpx_mock.get_requests()
    assert len(requests) == 2  # полная страница + завершающая пустая

    from ktalk_cli.registry import Registry

    with Registry(db) as reg:
        assert len(reg.list_recordings()) == 100


def test_ac_fr14_3_sync_window_over_100_records_all_present_in_registry(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock
):
    """AC FR-14/3: окно дат покрывает больше 100 записей -> в реестре оказываются все
    записи окна, а не только первые 100."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    inside = (date.today() - timedelta(days=1)).isoformat()

    def _page(offset, n):
        return {
            "recordings": [
                {"id": f"R{offset + i}", "title": f"Rec {offset + i}",
                 "createdDate": f"{inside}T00:00:00Z", "duration": 60}
                for i in range(n)
            ]
        }

    httpx_mock.add_response(json=_page(0, 100))
    httpx_mock.add_response(json=_page(100, 100))
    httpx_mock.add_response(json=_page(200, 50))
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    rc = main(["--db", str(db), "sync", "--days", "7", "--json"])
    assert rc == 0

    from ktalk_cli.registry import Registry

    with Registry(db) as reg:
        assert len(reg.list_recordings()) == 250


# FR-9 AC-2 (архив читается полностью за пределами одной страницы, под api-key)
# снято ADR-025 вместе с режимом: `list_archive` никогда не имел рабочего пути под
# сессией (замер, personal-api-key.md FR-6/FR-9) и после снятия ключа не имеет ни
# одного — `test_ac_fr6_3_operation_without_profile_refuses_before_network_call`
# (`test_auth_modes.py`) уже воспроизводит фактическое поведение (отказ до сети).


# --- Нормализация: session-форма и api-key-форма -> единая внутренняя форма -------------


def test_normalize_list_session_sets_cursor_on_full_page():
    """session-форма {"recordings": [...]} без токена страницы: полная страница (len==top)
    -> есть курсор продолжения (не полагается на отсутствующее поле)."""
    from ktalk_cli.client import normalize_list_session

    raw = {"recordings": [{"id": "a"}, {"id": "b"}]}
    page = normalize_list_session(raw, skip=0, top=2)

    assert [item["id"] for item in page.items] == ["a", "b"]
    assert page.cursor is not None


def test_normalize_list_session_no_cursor_on_short_page():
    """Короткая (не полная) страница -> последняя, курсора нет."""
    from ktalk_cli.client import normalize_list_session

    raw = {"recordings": [{"id": "a"}]}
    page = normalize_list_session(raw, skip=0, top=2)

    assert page.cursor is None


def test_normalize_list_session_no_cursor_on_empty_page():
    """Пустая страница (0 записей) — тоже последняя, отдельно от «короткой»."""
    from ktalk_cli.client import normalize_list_session

    page = normalize_list_session({"recordings": []}, skip=200, top=100)
    assert page.items == []
    assert page.cursor is None


def test_normalize_list_apikey_cursor_from_next_page_token():
    """api-key-форма {"entities": [...], "nextPageToken": ...} -> курсор из токена."""
    from ktalk_cli.client import normalize_list_apikey

    raw = {"entities": [{"id": "a"}], "nextPageToken": "tok-2"}
    page = normalize_list_apikey(raw)

    assert [item["id"] for item in page.items] == ["a"]
    assert page.cursor is not None


@pytest.mark.parametrize(
    "raw",
    [
        {"entities": [{"id": "a"}], "nextPageToken": None},
        {"entities": [{"id": "a"}]},
    ],
)
def test_normalize_list_apikey_no_cursor_when_token_null_or_absent(raw):
    """nextPageToken: null явно в JSON против отсутствующего поля вовсе — оба варианта
    эквивалентны «последняя страница»."""
    from ktalk_cli.client import normalize_list_apikey

    page = normalize_list_apikey(raw)
    assert page.cursor is None


# --- Ф-15/Ф-16: окно дат обеспечивает клиент, API startFrom игнорирует -------------


def test_clip_to_window_keeps_records_inside_window():
    from ktalk_cli.pagination import clip_to_window

    items = [
        {"id": "a", "createdDate": "2026-08-13T10:00:00Z"},
        {"id": "b", "createdDate": "2026-08-01T10:00:00Z"},
    ]
    kept, exhausted = clip_to_window(items, "2026-07-14")
    assert [i["id"] for i in kept] == ["a", "b"]
    assert exhausted is False


def test_clip_to_window_drops_older_and_signals_exhausted():
    from ktalk_cli.pagination import clip_to_window

    items = [
        {"id": "a", "createdDate": "2026-08-13T10:00:00Z"},
        {"id": "old", "createdDate": "2026-01-01T10:00:00Z"},
    ]
    kept, exhausted = clip_to_window(items, "2026-07-14")
    assert [i["id"] for i in kept] == ["a"]
    assert exhausted is True, "страница за порогом обязана останавливать обход"


def test_clip_to_window_keeps_records_without_date():
    """Пустая дата — неизвестность, а не «старая запись»: молча терять нельзя."""
    from ktalk_cli.pagination import clip_to_window

    kept, exhausted = clip_to_window([{"id": "x", "createdDate": ""}], "2026-07-14")
    assert [i["id"] for i in kept] == ["x"]
    assert exhausted is False


def test_clip_to_window_without_start_from_is_passthrough():
    from ktalk_cli.pagination import clip_to_window

    items = [{"id": "a", "createdDate": "2020-01-01T00:00:00Z"}]
    assert clip_to_window(items, None) == (items, False)


def test_sync_stops_paginating_once_window_exhausted(tmp_path, capsys, monkeypatch, httpx_mock):
    """Ф-15 регрессия: sync --days не должен затягивать весь домен.

    API игнорирует startFrom, поэтому вторая страница приходит целиком вне окна.
    Клиент обязан отфильтровать её и НЕ запрашивать третью.
    """
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "tok")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    today = date.today()
    inside = (today - timedelta(days=1)).isoformat()
    outside = (today - timedelta(days=400)).isoformat()

    httpx_mock.add_response(
        json={"recordings": [
            {"id": "in-1", "title": "Внутри окна",
             "createdDate": f"{inside}T10:00:00Z", "duration": 60},
        ]}
    )
    httpx_mock.add_response(
        json={"recordings": [
            {"id": "out-1", "title": "Вне окна",
             "createdDate": f"{outside}T10:00:00Z", "duration": 60},
        ]}
    )
    # Третьей страницы быть не должно: если код её запросит, pytest_httpx
    # упадёт на отсутствии зарегистрированного ответа.

    from ktalk_cli.cli import main

    rc = main(["--db", str(tmp_path / "r.db"), "sync", "--days", "7", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["synced"] == 1, "в реестр обязана попасть только запись внутри окна"

    from ktalk_cli.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        assert [r["recording_id"] for r in reg.list_recordings()] == ["in-1"]
