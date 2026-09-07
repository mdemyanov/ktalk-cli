"""AT-design: FR-48/NFR-23 — `ktalk doctor`, сводная диагностика окружения.

Покрывает `openspec/specs/host-project-config-discovery/spec.md`, требования
«ktalk doctor surfaces this capability's discovery outcome unchanged» (3 сценария) и
«ktalk doctor aggregates independently owned facts into one report without a write
call» (3 сценария). Источник — `content/30-requirements/cli-diagnostics-completeness.md`
FR-48, NFR-23, issue #14. Схема JSON-ответа (`version`/`token_file`/`auth`/`workspace`/
`host_config`, `ok`, `failed_items`) — интерфейсный контракт, предложенный SA
(`content/40-architecture/ADR-026-diagnostics-and-refusal-completeness-spec.md` §2,
псевдокод `cmd_doctor`), не внутренняя деталь: это ровно то, что читает промт-слой
плагина через `--json`.

Красные по замыслу: `ktalk doctor` в дереве не существует вовсе (`grep -rniE
"doctor" src/ktalk_cli/*.py` не даёт совпадений в командах) — `main(["doctor", ...])`
падает на `SystemExit(2)` argparse ("invalid choice"), не на ассерте, до тех пор пока
Dev не зарегистрирует подкоманду. Это стабильно диагностируемая, единственная
причина падения для КАЖДОГО теста этого файла на сегодняшнем коде — как только
`doctor` зарегистрирован, тесты начинают падать (или проходить) по своей
индивидуальной причине.
"""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

UNAVAILABLE_DB = "/nonexistent/path/does-not-exist/registry.db"


def _write_valid_host_config(path) -> None:
    (path / ".ktalk.toml").write_text(
        '[registry]\ndb_path = "custom.db"\n', encoding="utf-8"
    )


def test_fr48_1_doctor_is_registry_free_ignores_unreachable_db(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """NFR-23/FR-48: `doctor` не открывает реестр — тот же приём, что уже
    закрывает FR-19 для `auth-status` (`test_fr19_auth_status.py`)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0001")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    rc = main(["--db", UNAVAILABLE_DB, "doctor", "--json"])

    captured = capsys.readouterr()
    assert "unable to open database file" not in (captured.out + captured.err)
    assert rc == 0


def test_fr48_2_all_preconditions_satisfied_exit_zero_with_five_items(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Every satisfied-or-inapplicable precondition yields exit code
    zero» + FR-48 AC1 («ответ содержит все пять пунктов состава»)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0002")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    _write_valid_host_config(tmp_path)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    rc = main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert rc == 0
    for item in ("version", "token_file", "auth", "workspace", "host_config"):
        assert item in data, f"отсутствует пункт состава: {item}"


def test_fr48_3_aggregated_values_agree_with_dedicated_commands(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Aggregated values agree with each item's own dedicated command»:
    значения `doctor` совпадают с `--version`/`token status`/`auth-status`/
    `config show`, вызванными по отдельности на том же окружении."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0003")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    _write_valid_host_config(tmp_path)
    # Две независимые пробные сессии: одна для doctor, одна для отдельного auth-status.
    httpx_mock.add_response(json={"recordings": []})
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli import __version__
    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    main(["doctor", "--json"])
    doctor_data = json.loads(capsys.readouterr().out)

    main(["token", "status", "--json"])
    token_data = json.loads(capsys.readouterr().out)

    main(["auth-status", "--json"])
    auth_data = json.loads(capsys.readouterr().out)

    main(["config", "show", "--json"])
    config_data = json.loads(capsys.readouterr().out)

    assert doctor_data["version"]["installed"] == __version__
    assert doctor_data["token_file"]["present"] == token_data["present"]
    assert doctor_data["token_file"]["mode"] == token_data["mode"]
    assert doctor_data["auth"]["alive"] == auth_data["alive"]
    assert doctor_data["host_config"]["path"] == config_data["path"]


def test_fr48_4_absent_host_config_is_not_a_failure(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «An absent config is reported as a normal branch inside doctor,
    not a failure» — нет `.ktalk.toml` нигде на пути поиска -> не входит в
    `failed_items`, код возврата не страдает по этой причине."""
    monkeypatch.chdir(tmp_path)  # ни .ktalk.toml, ни .git
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0004")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    rc = main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["host_config"]["status"] == "absent"
    assert "host_config" not in data.get("failed_items", ["host_config"])
    assert rc == 0


def test_fr48_5_malformed_host_config_is_genuine_failure_named_by_cause(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «A malformed config names its cause inside doctor» — присутствующий,
    но невалидный `.ktalk.toml`: провал НАСТОЯЩИЙ, называет причину, попадает в
    `failed_items`, код возврата ненулевой."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0005")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    config_path = tmp_path / ".ktalk.toml"
    config_path.write_text("not valid toml [[[", encoding="utf-8")
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    rc = main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["host_config"]["status"] == "malformed"
    assert str(config_path) in data["host_config"].get("reason", "")
    assert "host_config" in data["failed_items"]
    assert rc != 0


def test_fr48_6_expect_min_version_unmet_is_failure(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0006")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    rc = main(["doctor", "--json", "--expect-min-version", "999.0.0"])
    data = json.loads(capsys.readouterr().out)

    assert data["version"]["meets_expectation"] is False
    assert "version" in data["failed_items"]
    assert rc != 0


def test_fr48_7_no_expect_min_version_flag_meets_expectation_is_null_not_a_failure(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0007")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    rc = main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["version"]["meets_expectation"] is None
    assert "version" not in data.get("failed_items", [])
    assert rc == 0


def test_fr48_8_absent_token_file_is_declared_failure_even_when_auth_alive(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Найденный SA след (ADR-026 «Последствия», негативный эффект): оператор с
    ТОЛЬКО `KTALK_SESSION_TOKEN` (без `ktalk token set`) получает ненулевой код по
    `token_file.usable=False`, хотя `auth.alive=True` в том же ответе. Тест
    фиксирует это как ОБЪЯВЛЕННОЕ поведение, не баг — Dev не имеет права
    «поправить» его молча (композитная логика отклонена ADR-026 «Альтернативы»)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0008")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main

    rc = main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["auth"]["alive"] is True
    assert data["token_file"]["usable"] is False
    assert "token_file" in data["failed_items"]
    assert rc != 0


def test_fr48_9_no_credential_auth_item_false_without_any_network_call(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Edge case companion-спеки §«Edge cases»: ни env, ни файл не дают credential
    -> `auth.alive=False` с текстом ошибки конфигурации, БЕЗ единого сетевого
    вызова (мок без зарегистрированного маршрута — падение мока = падение теста,
    если код всё же попытался дойти до сети)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)

    from ktalk_cli.cli import main

    rc = main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["auth"]["alive"] is False
    assert httpx_mock.get_requests() == []
    assert rc != 0


def test_fr48_10_single_network_call_shared_with_auth_status_not_duplicated(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """FR-48 AC4: `doctor` делает ТОТ ЖЕ единственный сетевой вызов, что
    `auth-status`, не два независимых обращения на один и тот же факт."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0010")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    main(["doctor", "--json"])
    capsys.readouterr()

    assert len(httpx_mock.get_requests()) == 1


def test_fr48_11_no_write_call_and_registry_untouched(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """FR-48/NFR-23: `doctor` не мутирует реестр — файл `--db` не должен появиться
    на диске после вызова (регистрируется как `_REGISTRY_FREE_COMMANDS`, реестр
    вовсе не открывается)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0011")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    db_path = tmp_path / "r.db"
    rc = main(["--db", str(db_path), "doctor", "--json"])
    capsys.readouterr()

    assert rc == 0
    assert not db_path.exists()
    for request in httpx_mock.get_requests():
        assert request.method == "GET"


def test_fr48_12_nonzero_exit_independent_of_json_flag(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «Any genuine failure yields a non-zero exit code, independent of
    --json parsing» — регрессия: код возврата ненулевой даже когда вызывающий не
    просит `--json` вовсе (не парсит тело)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)

    from ktalk_cli.cli import main

    rc = main(["doctor"])  # без --json

    assert rc != 0


def test_fr48_13_human_readable_output_names_failed_item_by_key(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """NFR-23 AC3: провалившийся пункт назван по имени в человекочитаемом выводе,
    не только числом провалов."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)

    from ktalk_cli.cli import main

    main(["doctor"])
    out = capsys.readouterr().out

    assert "auth" in out


def test_fr48_14_found_host_config_path_agrees_with_config_show(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock, capsys
):
    """Scenario «A found config's path agrees with config show» — оба называют
    один и тот же путь файла как источник резолвленной конфигурации."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("KTALK_TOKEN_FILE", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-doctor-0014")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    config_path = tmp_path / ".ktalk.toml"
    _write_valid_host_config(tmp_path)
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.cli import main
    from ktalk_cli.token_file import write_token

    write_token("okDOCTORtoken0123456")

    main(["doctor", "--json"])
    doctor_data = json.loads(capsys.readouterr().out)

    main(["config", "show", "--json"])
    config_data = json.loads(capsys.readouterr().out)

    assert doctor_data["host_config"]["status"] == "found"
    assert doctor_data["host_config"]["path"] == str(config_path)
    assert config_data["path"] == str(config_path)
