import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from ktalk_cli.host_config import HostConfig

# ADR-025: имя переменной снятого режима — используется только барьером
# маскирования (redact_secrets) и предупреждением (warn_if_legacy_key_present),
# как credential нигде не читается.
_LEGACY_PERSONAL_API_KEY_VAR = "KTALK_PERSONAL_API_KEY"


class KTalkConfigError(Exception):
    """Ни KTALK_SESSION_TOKEN, ни файл токена не заданы."""


def resolve_db_path(
    cli_db: str | None = None, host_config: "HostConfig | None" = None
) -> Path:
    """Resolve the registry DB path (ADR-013 §3, расширено волной 3):

    `--db` > `KTALK_REGISTRY_DB` > `host_config.registry.db_path` (SA-003,
    discovery выполняется вызывающей стороной — `resolve_db_path` только
    использует уже готовый `HostConfig`) > машинный дефолт централизованного
    хранилища (`store.resolve_store_root`, FR-22).

    Старый относительный дефолт `95_TRANSCRIPTS/.registry.db` (ADR-002) заменён
    машинным дефолтом вне cwd (ADR-013) — единственный оставшийся источник
    относительного пути в этой функции теперь `host_config`, если проект-хозяин
    явно объявляет относительный `registry.db_path`.

    Code review (epic-capability-pairing, Р4): `warn_if_sync_dir` (NFR-14 AC-2)
    обязана применяться к итоговому пути независимо от источника (ADR-013-spec
    §«Поток данных» п.4) — до этой правки вызывалась только в ветке машинного
    дефолта; `--db`/`KTALK_REGISTRY_DB`/конфиг хозяина возвращали путь раньше.
    """
    from ktalk_cli.store import resolve_store_root, warn_if_sync_dir

    if cli_db:
        path = Path(cli_db)
        warn_if_sync_dir(path)
        return path
    env = os.environ.get("KTALK_REGISTRY_DB")
    if env:
        path = Path(env)
        warn_if_sync_dir(path)
        return path
    if host_config is not None:
        configured = host_config.registry.get("db_path")
        if configured:
            path = Path(configured)
            warn_if_sync_dir(path)
            return path

    path = resolve_store_root() / "registry.db"
    warn_if_sync_dir(path)
    return path


class Settings(BaseSettings):
    """KTalk MCP server configuration.

    Environment variables:
        KTALK_BASE_URL: KTalk instance URL (default: https://your-domain.ktalk.ru)
        KTALK_SESSION_TOKEN: Session token from browser cookies

    ADR-025: `KTALK_PERSONAL_API_KEY` снята с модели целиком — не читается ни на
    одном шаге разрешения credential (FR-42). Единственный источник — сессионный
    токен: переменная, затем файл (`_fall_back_to_token_file`). `.auth_credential`
    — единственная точка, где отсутствие обоих источников становится
    `KTalkConfigError`.

    NFR-5 / security review (SEC-001): `ktalk_session_token` объявлен
    `Field(repr=False)` — pydantic по умолчанию печатает значения ВСЕХ полей
    в `repr(settings)`/`str(settings)` (в отличие от `AuthContext`, который уже
    маскирует себя явно), а это ровно тот текст, что мог бы случайно попасть в
    отладочный `print`/`logger.debug(settings)` или в текст будущего `ValidationError`.
    """

    ktalk_base_url: str = "https://your-domain.ktalk.ru"
    ktalk_session_token: str | None = Field(default=None, repr=False)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def _fall_back_to_token_file(self) -> "Settings":
        """Третий источник сессии — файл `~/.config/ktalk-mcp/token` (token_file.py).

        Подставляется здесь, а не в `.auth_credential`, чтобы у файла и у переменной
        окружения была ровно одна точка входа в модель: всё остальное
        (`auth_credential`, барьер маскирования `redact_secrets`) продолжает читать
        одно поле и о существовании файла не знает.

        Порядок источников: `KTALK_SESSION_TOKEN` > файл. Файл читается только
        когда переменная пуста — заданное окружение сильнее лежащего на диске,
        иначе протухший файл молча перебивал бы токен, который оператор передал
        явно.
        """
        if self.ktalk_session_token:
            return self
        from ktalk_cli.token_file import read_token

        token = read_token()
        if token:
            object.__setattr__(self, "ktalk_session_token", token)
        return self

    @property
    def auth_credential(self) -> str:
        if self.ktalk_session_token:
            return self.ktalk_session_token
        raise KTalkConfigError(
            "Не задана KTALK_SESSION_TOKEN, и файла токена нет. Задайте "
            "переменную или выполните `ktalk token set -` (см. README)."
        )


def redact_secrets(text: str) -> str:
    """Барьер маскирования (NFR-5, ADR-003 «SecretRedactor», ранее спроектирован, но не
    вызывался ниоткуда — security review SEC-001).

    Ни `KTalkError`, ни `httpx`-обёртки этого проекта сегодня не строят текст ошибки из
    `request.url`/`request.headers`/`repr(request)` (проверено ревью) — секрет не должен
    появиться в тексте исключения. Это тем не менее последний рубеж на границе CLI: если
    секрет всё же попадёт в текст произвольного, не-`KTalkError`-исключения (например, из
    сторонней зависимости, которая не следует той же дисциплине), значение маскируется
    здесь перед печатью, а не полагается только на дисциплину каждого источника ошибки.

    ADR-025: `KTALK_PERSONAL_API_KEY` снята из модели `Settings` (не credential
    больше), но её значение всё ещё способно попасть в вывод через однократное
    предупреждение (FR-43) — читается здесь напрямую из окружения, единственное
    место кода, всё ещё смотрящее на эту переменную, и ради маскирования, не
    ради credential.
    """
    try:
        settings = Settings()
    except Exception:  # noqa: BLE001 - барьер не должен сам стать новым источником отказа
        settings = None
    if settings is not None and settings.ktalk_session_token:
        text = text.replace(settings.ktalk_session_token, "***REDACTED***")
    legacy_key = os.environ.get(_LEGACY_PERSONAL_API_KEY_VAR)
    if legacy_key:
        text = text.replace(legacy_key, "***REDACTED***")
    return text


def warn_if_legacy_key_present() -> None:
    """FR-43: обнаружение снятой `KTALK_PERSONAL_API_KEY` не проходит молча.

    Печатает на stderr ровно одну статичную строку (не интерполирует значение
    переменной — не полагается только на постфактум-маскирование) и продолжает:
    предупреждение не блокирует команду. Вызывается один раз за процесс, из
    `cli.py::main()` до диспетчеризации команды — масштаб «once per invocation»
    без счётчика/памяти состояния, а не «once per HTTP request».
    """
    if not os.environ.get(_LEGACY_PERSONAL_API_KEY_VAR):
        return
    message = (
        f"Режим персонального API-ключа снят (ADR-025) — {_LEGACY_PERSONAL_API_KEY_VAR} "
        "не используется. Работа продолжается на сессионном токене (см. README)."
    )
    print(redact_secrets(message), file=sys.stderr)
