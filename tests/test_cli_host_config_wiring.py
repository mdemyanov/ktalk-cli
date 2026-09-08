"""Security review SEC-003, MAJ-01/MAJ-02: `main()` не подключал `.ktalk.toml` к
`resolve_db_path` (третий источник приоритета FR-23 мёртв в проде) и не сужал окно
мутации `umask` вокруг открытия `Registry` (MAJ-02, see tests/test_store.py).

Отчёт: content/40-architecture/security-review-ktalk-plugin.md, разделы MAJ-01/MAJ-02.
"""

from __future__ import annotations

import json
import stat


def _seed(db_path):
    from ktalk_cli.registry import Registry

    with Registry(db_path) as reg:
        reg.upsert_recording(
            {"recording_id": "wired", "name": "Wired via host_config", "date": "2026-01-01"},
            now="2026-01-01",
        )


# --- MAJ-01: третий источник приоритета FR-23 действует в проде --------------------


def test_maj01_host_config_db_path_wired_into_cli_main(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    db_path = project / "custom-registry.db"
    _seed(db_path)
    (project / ".ktalk.toml").write_text(
        f'[registry]\ndb_path = "{db_path}"\n', encoding="utf-8"
    )

    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(project)

    from ktalk_cli.cli import main

    rc = main(["list", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ids = {r["recording_id"] for r in out["recordings"]}
    assert "wired" in ids, (
        "TODO: MAJ-01 — main() обязан резолвить путь БД через discover_host_config()"
    )


def test_maj01_explicit_db_flag_still_wins_over_host_config(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".ktalk.toml").write_text(
        '[registry]\ndb_path = "should-not-be-used.db"\n', encoding="utf-8"
    )
    explicit_db = tmp_path / "explicit.db"
    _seed(explicit_db)

    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(project)

    from ktalk_cli.cli import main

    rc = main(["--db", str(explicit_db), "list", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ids = {r["recording_id"] for r in out["recordings"]}
    assert "wired" in ids
    assert not (project / "should-not-be-used.db").exists()


def test_maj01_registry_free_command_does_not_trigger_host_config_discovery(
    tmp_path, monkeypatch, capsys
):
    """`_REGISTRY_FREE_COMMANDS` не открывают БД — discovery пути тоже не должен
    их задевать: malformed `.ktalk.toml` не должен ломать свободную команду,
    которая сама не читает конфиг."""
    (tmp_path / ".ktalk.toml").write_text("not valid toml [[[", encoding="utf-8")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "test-token")

    from ktalk_cli.cli import main

    main(["auth-status"])
    captured = capsys.readouterr()
    assert ".ktalk.toml" not in captured.err, (
        "TODO: MAJ-01 — discovery не должен вызываться для _REGISTRY_FREE_COMMANDS"
    )


# --- MAJ-02: окно мутации umask сужено до открытия Registry ------------------------


def test_maj02_umask_restored_after_registry_command_returns(tmp_path, monkeypatch):
    import os

    project = tmp_path / "project"
    project.mkdir()
    db_path = project / "registry.db"
    _seed(db_path)

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(project)

    old_umask = os.umask(0o022)
    os.umask(old_umask)  # только считать исходное значение

    from ktalk_cli.cli import main

    rc = main(["--db", str(db_path), "list", "--json"])
    assert rc == 0

    after = os.umask(old_umask)
    os.umask(after)
    assert after == old_umask, (
        "TODO: MAJ-02 — umask обязан быть восстановлен сразу после открытия Registry, "
        f"ожидалось {oct(old_umask)}, получено {oct(after)}"
    )


def test_maj02_file_written_after_registry_closes_uses_ambient_umask_not_0o077(
    tmp_path, monkeypatch
):
    """Воспроизведение (а) из отчёта: файл, записанный тем же процессом ПОСЛЕ
    открытия Registry (например, export -> registry.md), не должен незапланированно
    унаследовать 0600 только потому, что где-то раньше резолвился машинный дефолт —
    после сужения окна umask восстанавливается сразу после Registry."""
    import os

    project = tmp_path / "project"
    project.mkdir()
    db_path = project / "registry.db"
    _seed(db_path)

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(project)

    old_umask = os.umask(0o022)
    os.umask(old_umask)

    from ktalk_cli.cli import main

    rc = main(["--db", str(db_path), "export"])
    assert rc == 0

    mirror = project / "registry.md"
    assert mirror.exists()
    mode = stat.S_IMODE(mirror.stat().st_mode)
    assert mode != 0o600, (
        "TODO: MAJ-02 — файл, записанный после закрытия Registry, не обязан "
        f"наследовать ограничение хранилища; получено {oct(mode)}"
    )


# --- MAJ-03: export пишет зеркало рядом с БД из .ktalk.toml, а не рядом с дефолтом ---


def test_fr23_ac4_bare_cli_relative_db_path_from_subdirectory_reproduces_dashboard_symptom(
    tmp_path, monkeypatch, capsys
):
    """Discovery-режим 2 (обход вверх от cwd, SA-003) + FR-23 AC-4 (ktalk-mcp-ds6):
    буквальное воспроизведение отчёта владельца — `cd .../95_TRANSCRIPTS && ktalk
    dashboard` падал `unable to open database file`, потому что относительный
    db_path резолвился от cwd вместо каталога найденного .ktalk.toml (обход
    находит конфиг в родителе, а не в cwd самом). `dashboard` — команда из
    исходного отчёта, не заменена на `list` намеренно."""
    project = tmp_path / "naumen-cto"
    project.mkdir()
    (project / ".git").mkdir()
    db_path = project / "95_TRANSCRIPTS" / ".registry.db"
    db_path.parent.mkdir(parents=True)
    _seed(db_path)
    (project / ".ktalk.toml").write_text(
        '[registry]\ndb_path = "95_TRANSCRIPTS/.registry.db"\n', encoding="utf-8"
    )

    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(db_path.parent)  # ровно подкаталог хранилища из отчёта

    from ktalk_cli.cli import main

    rc = main(["dashboard", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ids = {r["recording_id"] for r in out["new"]}
    assert "wired" in ids, (
        "TODO: FR-23 AC-4 — относительный db_path обязан резолвиться от "
        "каталога .ktalk.toml (host_config.path.parent), не от cwd вызова"
    )


def test_fr23_ac4_explicit_claude_project_dir_relative_db_path_ignores_unrelated_cwd(
    tmp_path, monkeypatch, capsys
):
    """Discovery-режим 1 (явный CLAUDE_PROJECT_DIR, SA-003) + FR-23 AC-4: cwd —
    каталог, не являющийся ни проектом, ни его предком/потомком (обход вверх в
    этом режиме не выполняется вовсе, discovery ищет ровно по CLAUDE_PROJECT_DIR).
    Относительный db_path обязан резолвиться от CLAUDE_PROJECT_DIR, не от этого
    произвольного cwd."""
    project = tmp_path / "project"
    project.mkdir()
    db_path = project / "store" / "registry.db"
    db_path.parent.mkdir(parents=True)
    _seed(db_path)
    (project / ".ktalk.toml").write_text(
        '[registry]\ndb_path = "store/registry.db"\n', encoding="utf-8"
    )
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()

    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.chdir(unrelated_cwd)

    from ktalk_cli.cli import main

    rc = main(["list", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ids = {r["recording_id"] for r in out["recordings"]}
    assert "wired" in ids, (
        "TODO: FR-23 AC-4 — discovery-режим 1: относительный db_path обязан "
        "резолвиться от CLAUDE_PROJECT_DIR, не от cwd"
    )


def test_maj03_export_mirror_follows_host_config_db_path(tmp_path, monkeypatch, capsys):
    """`_cmd_export` резолвил путь БД повторно и БЕЗ host_config: реестр читался из
    `.ktalk.toml`, а `registry.md` уезжал к машинному дефолту (`store.resolve_store_root`).
    Регрессия: без `--db` зеркало обязано лечь рядом с настроенной БД."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    db_path = project / "archive" / "registry.db"
    db_path.parent.mkdir()
    _seed(db_path)
    (project / ".ktalk.toml").write_text(
        f'[registry]\ndb_path = "{db_path}"\n', encoding="utf-8"
    )

    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(project)

    from ktalk_cli.cli import main

    rc = main(["export", "--json"])
    assert rc == 0
    written = json.loads(capsys.readouterr().out)["written"]
    assert written == str(db_path.parent / "registry.md"), (
        "export обязан писать зеркало рядом с БД, резолвленной с учётом .ktalk.toml"
    )
