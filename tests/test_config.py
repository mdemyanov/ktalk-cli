from pathlib import Path

import pytest


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "test-token-123")
    monkeypatch.setenv("KTALK_BASE_URL", "https://custom.ktalk.ru")

    from ktalk_cli.config import Settings

    settings = Settings()
    assert settings.ktalk_session_token == "test-token-123"
    assert settings.ktalk_base_url == "https://custom.ktalk.ru"


def test_settings_default_base_url(monkeypatch):
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "test-token-123")
    monkeypatch.delenv("KTALK_BASE_URL", raising=False)

    from ktalk_cli.config import Settings

    settings = Settings()
    assert settings.ktalk_base_url == "https://your-domain.ktalk.ru"


def test_settings_requires_session_token(monkeypatch):
    """ADR-025: `ktalk_session_token` остаётся Optional на уровне модели — Settings()
    не падает сама по себе. Ошибка конфигурации (KTalkConfigError) откладывается до
    обращения к `.auth_credential`, единственной оставшейся точке отказа (`.auth_mode`
    снят ADR-025 целиком вместе с `AuthMode`, не сужен до одного значения)."""
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_BASE_URL", raising=False)

    from ktalk_cli.config import KTalkConfigError, Settings

    settings = Settings()  # не поднимает исключение
    with pytest.raises(KTalkConfigError):
        _ = settings.auth_credential


def test_resolve_db_path_default(monkeypatch, tmp_path):
    """Обновлено волной 3 (ADR-013): старый относительный дефолт
    `95_TRANSCRIPTS/.registry.db` (ADR-002) заменён машинным дефолтом вне cwd.
    `DEFAULT_DB_PATH` как отдельная константа больше не существует — единственный
    источник дефолта теперь `store.resolve_store_root()`, здесь сверяется прямое
    делегирование. `$HOME` подменяется `tmp_path`, чтобы не задеть реальный
    домашний каталог машины, на которой запускаются тесты (см.
    content/60-implementation/ dev-заметку по DEV-001 волны 3)."""
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from ktalk_cli.config import resolve_db_path
    from ktalk_cli.store import resolve_store_root

    assert resolve_db_path() == resolve_store_root() / "registry.db"


def test_resolve_db_path_env(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_cli.config import resolve_db_path

    assert resolve_db_path() == Path("/tmp/from-env.db")


def test_resolve_db_path_flag_wins(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_cli.config import resolve_db_path

    assert resolve_db_path("/tmp/from-flag.db") == Path("/tmp/from-flag.db")


# --- FR-23 AC-1..3: приоритет расширен четвёртым источником (host_config,
# SA-003/ktalk-plugin-spec.md) между KTALK_REGISTRY_DB и машинным дефолтом
# (ADR-013 §3). resolve_db_path принимает уже распарсенный HostConfig | None —
# discovery не выполняет сам (host_config.py — отдельный модуль).


def _host_config_with_db_path(db_path: str):
    """Строит минимальный HostConfig с заданным registry.db_path.

    Реальная форма HostConfig (dataclass/pydantic) — решение Dev
    (ktalk-plugin-spec.md, «Реализовать»). Стаб полагается только на то, что
    `resolve_db_path` умеет прочитать атрибут `registry.db_path` (или
    эквивалент) из объекта, возвращаемого `host_config.load_host_config`.
    """
    from ktalk_cli.host_config import HostConfig

    return HostConfig(registry={"db_path": db_path})


def test_ac_fr23_1_all_four_sources_given_flag_wins(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_cli.config import resolve_db_path

    host_config = _host_config_with_db_path("/tmp/from-host-config.db")
    assert resolve_db_path("/tmp/from-flag.db", host_config=host_config) == Path(
        "/tmp/from-flag.db"
    )


def test_ac_fr23_2_flag_absent_env_and_host_config_given_env_wins(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_cli.config import resolve_db_path

    host_config = _host_config_with_db_path("/tmp/from-host-config.db")
    assert resolve_db_path(None, host_config=host_config) == Path("/tmp/from-env.db")


def test_ac_fr23_3_only_host_config_given_host_config_wins_over_machine_default(
    monkeypatch,
):
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    from ktalk_cli.config import resolve_db_path

    host_config = _host_config_with_db_path("/tmp/from-host-config.db")
    resolved = resolve_db_path(None, host_config=host_config)
    assert resolved == Path("/tmp/from-host-config.db")
    assert resolved != Path("95_TRANSCRIPTS/.registry.db")  # не старый дефолт


def test_resolve_db_path_none_of_the_four_sources_falls_through_to_machine_default(
    monkeypatch,
):
    """FR-22 AC-1: без --db/env/конфига хозяина — машинный дефолт, не
    95_TRANSCRIPTS/.registry.db (профиль изменений ktalk-plugin.md).
    Машинный дефолт сам — ответственность `store.resolve_store_root` (FR-22),
    здесь только фиксируется, что resolve_db_path больше не возвращает
    относительный дефолт cwd, когда ни один из четырёх источников не задан."""
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    from ktalk_cli.config import resolve_db_path

    resolved = resolve_db_path(None, host_config=None)
    assert not resolved.is_relative_to(Path.cwd()), (
        "TODO: FR-22 AC-1 — машинный дефолт вне cwd, не 95_TRANSCRIPTS/.registry.db"
    )
