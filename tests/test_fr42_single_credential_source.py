"""AT-design: FR-42 — сессионный токен как единственный источник credential.

Покрывает `openspec/specs/talk-api-auth-modes/spec.md`, требование
«Session token is the only credential source» (4 сценария; сценарии 2 и 3 —
"env var wins over file" / "file is the fallback of last resort" — уже покрыты
`tests/test_token_file.py::test_env_session_token_wins_over_file` и
`::test_settings_reads_token_file_when_env_empty` независимо от снятия ключа, не
дублируются здесь). Источник — `content/30-requirements/single-auth-mode.md` FR-42,
issue #10.

Красные по замыслу: сегодня (`config.py`, `auth.py`, `client.py`) `AuthContext.resolve`
и `KTalkClient.__init__` всё ещё отдают приоритет `KTALK_PERSONAL_API_KEY` над
`KTALK_SESSION_TOKEN`, а `Settings.auth_credential` никогда не поднимает исключение
(поднимает только `.auth_mode`, которое ADR-025 снимает). Тесты ниже написаны против
целевого контракта ADR-025 (`auth_credential` — единственная точка отказа) — падают
`AssertionError`/`pytest.raises`-`DID NOT RAISE`, не `ImportError`: используемые имена
(`Settings`, `KTalkClient.from_settings`, `KTalkConfigError`) уже существуют сегодня.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


def _isolate_from_token_file(monkeypatch, tmp_path):
    """Гарантирует отсутствие третьего источника (файла) — иначе «оба env absent»
    тихо резолвился бы через файл, оставленный предыдущим тестом/зондом."""
    monkeypatch.setenv("KTALK_TOKEN_FILE", str(tmp_path / "no-such-token-file"))


def test_fr42_1_personal_key_alone_raises_same_config_error_as_empty_env(
    monkeypatch, tmp_path
):
    """Spec Scenario «No session credential anywhere is a configuration error...»:
    ключ задан один, сессии и файла нет -> тот же отказ конфигурации, что и при
    полностью пустом окружении (не «работает под ключом», как сегодня)."""
    _isolate_from_token_file(monkeypatch, tmp_path)
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-legacy-0001")
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_cli.config import KTalkConfigError, Settings

    with pytest.raises(KTalkConfigError):
        _ = Settings().auth_credential


def test_fr42_2_personal_key_alone_error_never_mentions_the_variable(
    monkeypatch, tmp_path
):
    """Spec Scenario «No session credential anywhere...»: текст ошибки называет
    `KTALK_SESSION_TOKEN` и команду файла токена, НЕ `KTALK_PERSONAL_API_KEY`."""
    _isolate_from_token_file(monkeypatch, tmp_path)
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-legacy-0001")
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_cli.config import KTalkConfigError, Settings

    with pytest.raises(KTalkConfigError) as exc_info:
        _ = Settings().auth_credential

    message = str(exc_info.value)
    assert "KTALK_SESSION_TOKEN" in message
    assert "KTALK_PERSONAL_API_KEY" not in message


async def test_fr42_3_both_set_request_carries_session_value_not_header_or_key(
    monkeypatch, httpx_mock: HTTPXMock, base_url
):
    """Spec Scenario «Only the session token resolves, regardless of the legacy
    variable»: оба заданы -> запрос несёт `sessionToken` (значение сессии), НЕ несёт
    `X-Auth-Token`, и значение ключа нигде не встречается (заголовки/URL)."""
    monkeypatch.setenv("KTALK_BASE_URL", base_url)
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-legacy-0002")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-active-0002")
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_cli.client import KTalkClient
    from ktalk_cli.config import Settings

    async with KTalkClient.from_settings(Settings()) as client:
        await client.list_recordings()

    request = httpx_mock.get_request()
    assert "sessionToken=sess-active-0002" in str(request.url)
    assert request.headers.get("X-Auth-Token") is None
    assert "pk-legacy-0002" not in str(request.url)
    assert "pk-legacy-0002" not in str(request.headers)


def test_fr42_4_neither_set_error_names_session_token_and_set_command(
    monkeypatch, tmp_path
):
    """Spec Scenario «No session credential anywhere...», ветка «ключ тоже не
    задан» (регрессия по форме сообщения, требование доп. явно называет команду
    `ktalk token set -`, не только переменную)."""
    _isolate_from_token_file(monkeypatch, tmp_path)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_cli.config import KTalkConfigError, Settings

    with pytest.raises(KTalkConfigError) as exc_info:
        _ = Settings().auth_credential

    message = str(exc_info.value)
    assert "KTALK_SESSION_TOKEN" in message
    assert "token set" in message
    assert "KTALK_PERSONAL_API_KEY" not in message
