"""AT-design: сверка идентификаторов перед первым api-key sync (FR-15).

Покрывает: FR-15 AC-1 (механика сравнения множеств id — фикстуры, часть автоматическая;
обязательный ручной прогон на боевом домене — отдельно, at-design.md), AC-2 (расхождение
блокирует боевую синхронизацию без осознанного решения оператора), AC-3 (полное
совпадение -> обычная синхронизация может выполняться).

Красные по замыслу: модуль `ktalk_cli.reconciliation` (`compare_id_sets`) не существует;
флаг `ktalk sync --dry-run` в этой (api-key-guard) роли не существует.

ВАЖНО (флаг QA-author, не догадка Dev): требование не фиксирует, ЧЕРЕЗ ЧТО именно
оператор "осознанно подтверждает" переход к боевой синхронизации после совпадения
(AC-3 помечена BA как ручная проверка целиком) — тесты AC-2/AC-3 ниже фиксируют
поведение `--dry-run` как gate по exit-коду (0 = совпадение/можно продолжать,
не-0 = расхождение/заблокировано), по аналогии с уже принятым в проекте паттерном
`show --json` (rc=1 при ошибке, тест `test_show_missing_returns_error`). Если SA/Dev
спроектируют другой UX подтверждения (например, отдельный флаг
`--confirm-reconciled`), это ожидаемая правка сценария теста, а не самого AC.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from pytest_httpx import HTTPXMock

# Дата внутри окна --days (см. Ф-15): захардкоженная дата протухает со временем.
_INSIDE_WINDOW = (date.today() - timedelta(days=1)).isoformat()


def test_ac_fr15_1_compare_id_sets_full_match():
    """AC FR-15/1 (механика): совпадение id между api-key-ответом и реестром -> нет
    расхождений."""
    from ktalk_cli.reconciliation import compare_id_sets

    fetched = ["A", "B", "C"]
    existing = ["A", "B", "C"]
    result = compare_id_sets(fetched, existing)

    assert result["only_in_fetched"] == set()
    assert result["only_in_existing"] == set()
    assert result["common"] == {"A", "B", "C"}


def test_ac_fr15_1b_compare_id_sets_detects_mismatch():
    """AC FR-15/1 (механика): расхождение id -> обнаруживается явно по обеим сторонам."""
    from ktalk_cli.reconciliation import compare_id_sets

    fetched = ["A", "B", "X"]
    existing = ["A", "B", "C"]
    result = compare_id_sets(fetched, existing)

    assert result["only_in_fetched"] == {"X"}
    assert result["only_in_existing"] == {"C"}


def test_ac_fr15_2_dry_run_mismatch_blocks_sync_without_confirmation(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock
):
    """AC FR-15/2: сухой прогон обнаружил расхождение -> боевая синхронизация в
    api-key-режиме не выполняется автоматически без осознанного решения оператора
    (--dry-run сигнализирует расхождение через ненулевой код возврата)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    from ktalk_cli.registry import Registry

    db = tmp_path / "r.db"
    with Registry(db) as reg:
        reg.upsert_recording(
            {"recording_id": "OLD-1", "name": "Существующая запись", "date": _INSIDE_WINDOW},
            now=_INSIDE_WINDOW,
        )

    httpx_mock.add_response(
        json={
            "recordings": [
                {"id": "NEW-1", "key": "NEW-1", "title": "Другая запись",
                 "createdDate": f"{_INSIDE_WINDOW}T00:00:00Z", "duration": 60,
                 "participantsCount": 0, "participants": []},
            ],
        }
    )
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    rc = main(["--db", str(db), "sync", "--days", "7", "--dry-run", "--json"])
    assert rc != 0

    with Registry(db) as reg:
        # Dev-фикс стаба: оригинальная проверка `list_recordings() == []` противоречила
        # собственному сетапу теста (OLD-1 предзаписан строкой выше в этом же файле БД) —
        # dry-run "ничего не пишет" означает, что реестр остаётся НЕИЗМЕННЫМ (как
        # `migrate --dry-run`), а не тайно опустошается. Root cause подтверждён
        # systematic-debugging, см. отчёт Dev.
        assert [r["recording_id"] for r in reg.list_recordings()] == ["OLD-1"]


def test_ac_fr15_3_dry_run_full_match_allows_proceeding(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock
):
    """AC FR-15/3: сухой прогон подтвердил полное совпадение id -> сигнал "можно
    продолжать" (нулевой код возврата), обычная синхронизация может выполняться."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    from ktalk_cli.registry import Registry

    db = tmp_path / "r.db"
    with Registry(db) as reg:
        reg.upsert_recording(
            {"recording_id": "SAME-1", "name": "Существующая запись", "date": _INSIDE_WINDOW},
            now=_INSIDE_WINDOW,
        )

    httpx_mock.add_response(
        json={
            "recordings": [
                {"id": "SAME-1", "key": "SAME-1", "title": "Существующая запись",
                 "createdDate": f"{_INSIDE_WINDOW}T00:00:00Z", "duration": 60,
                 "participantsCount": 0, "participants": []},
            ],
        }
    )
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    rc = main(["--db", str(db), "sync", "--days", "7", "--dry-run", "--json"])
    assert rc == 0


def test_dry_run_on_empty_registry_reports_no_data_not_silent_ok(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Edge case client-modules-spec: `ktalk sync --dry-run` на пустом реестре (первый
    sync вообще) — сверивать не с чем; должен явно сообщить об этом, не молчаливый OK."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    httpx_mock.add_response(
        json={
            "recordings": [
                {"id": "FIRST-1", "key": "FIRST-1", "title": "Первая запись",
                 "createdDate": f"{_INSIDE_WINDOW}T00:00:00Z", "duration": 60,
                 "participantsCount": 0, "participants": []},
            ],
        }
    )
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    rc = main(["--db", str(db), "sync", "--days", "7", "--dry-run", "--json"])
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    text = json.dumps(out, ensure_ascii=False)
    assert "нет данных" in text or "пуст" in text.lower()


def test_dry_run_compares_same_window_not_whole_registry(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock
):
    """FR-15 регрессия: реестр хранит всю историю, API отдаёт только окно --days.

    Сравнение окна со всей историей давало бы ложное расхождение на каждой
    записи старше окна — предохранитель, срабатывающий всегда, бесполезен.
    """
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    from ktalk_cli.registry import Registry

    long_ago = (date.today() - timedelta(days=300)).isoformat()
    db = tmp_path / "r.db"
    with Registry(db) as reg:
        # Историческая запись вне окна — она НЕ должна считаться расхождением.
        reg.upsert_recording(
            {"recording_id": "ANCIENT-1", "name": "Древняя", "date": long_ago},
            now=long_ago,
        )
        reg.upsert_recording(
            {"recording_id": "SAME-1", "name": "Внутри окна", "date": _INSIDE_WINDOW},
            now=_INSIDE_WINDOW,
        )

    httpx_mock.add_response(
        json={
            "recordings": [
                {"id": "SAME-1", "key": "SAME-1", "title": "Внутри окна",
                 "createdDate": f"{_INSIDE_WINDOW}T00:00:00Z", "duration": 60,
                 "participantsCount": 0, "participants": []},
            ],
        }
    )
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    rc = main(["--db", str(db), "sync", "--days", "7", "--dry-run", "--json"])
    assert rc == 0, "историческая запись вне окна не является расхождением"
