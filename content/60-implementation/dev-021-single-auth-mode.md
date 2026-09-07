---
title: "DEV-021: единственный режим авторизации — снятие персонального API-ключа"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# DEV-021: реализация ADR-025 (issue #10, issue #11)

Реализация по 11 красным тестам QA-author (`tests/test_fr42_single_credential_source.py`,
`tests/test_fr43_legacy_key_removal_warning.py`, `tests/test_fr44_auth_status_accepted_rejected.py`)
поверх [ADR-025](../00-project/adr/ADR-025-single-auth-mode.md) и его
[companion-спеки](../40-architecture/ADR-025-single-auth-mode-spec.md).

## Файлы

| Файл | Что |
|---|---|
| `src/ktalk_cli/config.py` | `AuthMode`, `Settings.ktalk_personal_api_key`, `.auth_mode` удалены; `.auth_credential` — единственная точка отказа (`KTalkConfigError`); `redact_secrets` маскирует `Settings().ktalk_session_token` + `os.environ.get("KTALK_PERSONAL_API_KEY")` напрямую; новая `warn_if_legacy_key_present()` |
| `src/ktalk_cli/auth.py` | `AuthContext(credential)` (без `mode`), `.resolve(*, session_token)`; `SCOPE_LABELS`, `KTalkScopeError`-ветка и `full_participants_apikey` удалены; `classify_response(response)` — session-текст без параметра `mode`; `AuthStatus(alive, note)` |
| `src/ktalk_cli/endpoints.py` | `OPERATION_PROFILES: dict[str, EndpointProfile \| None]` (плоская), `EndpointProfile.required_scope` снят; `get_participants_report` удалён из таблицы |
| `src/ktalk_cli/client.py` | `__init__`/`from_settings` без `personal_api_key`; `_profile_for` — один текст отказа; `_classify(response)`; `list_recordings`/`list_archive` без api-key-веток; `get_full_participants` — только оркестрация; `get_participants_report` удалён; `_auth_status_apikey` удалён, `_auth_status_session` ловит `ValueError` отдельно от `KTalkAuthError` |
| `src/ktalk_cli/cli.py` | `warn_if_legacy_key_present()` — первая строка `main()` |
| `src/ktalk_cli/cli_sync.py` | `_fetch_recordings` — только `skip_pages`; `cmd_auth_status`: `data={alive,note}`, `return 0 if status.alive else 1` (оба режима вывода) |
| `src/ktalk_cli/pagination.py` | `token_pages` удалена (единственный потребитель снят вместе с api-key-пагинацией `cli_sync.py`) |
| `src/ktalk_cli/download.py` | `build_download_url`, `DEFAULT_QUALITY`, api-key-ветка удалены; единственный путь — `_resolve_session_quality` |
| `src/ktalk_cli/calendar_reader.py`, `contacts.py`, `meeting_scheduling.py`, `rooms.py` | `client._classify(response, profile.required_scope)` → `client._classify(response)` |
| `README.md` | раздел «Авторизация» переписан на единственный режим, названа цена (ручное обновление токена); `list-archive` помечена постоянно недоступной; `## API` сужен до session-путей |

`pyproject.toml` **не тронут** — прямое указание координатора перекрывает пункт брифа
ADR-025-spec «Версия: `pyproject.toml` → 3.0.0 — часть этой задачи Dev»: версия и
релизный коммит — отдельная задача по санкции владельца. Расхождение брифа с явной
инструкцией координатора решено в пользу инструкции, о чём этот абзац и есть доклад.

`content/40-architecture/security-review-personal-api-key.md` уже нёс отметку о снятии
режима на момент начала задачи (пункт #22 companion-спеки) — правка не понадобилась.

## Три операции без session-пути — проверено, не принято на слово

- `list_archive` — профиль `None`, единственная запись в таблице; `KTalkClient._profile_for`
  отказывает до сети, `client.py::list_archive` не достижим. CLI-команда `list-archive`
  осталась вызываемой (`cli_meetings_read.py` не менялся) — отказывает на каждый вызов текстом
  «недоступна: рабочего пути под сессионным токеном нет», код возврата 1, ноль HTTP-запросов
  (`tests/test_cli_content.py::test_list_archive_refuses_before_network_call`).
- `get_participants_full` — профиль `None` в таблице (запись оставлена как документация
  отсутствия пути), но `KTalkClient.get_full_participants` не проверяет профиль вовсе —
  session-ветка (`get_recording` + `get_conference`) безусловна, `full_participants_apikey`
  и её вызов удалены.
- `get_participants_report` — метод `KTalkClient.get_participants_report` и запись таблицы
  удалены целиком; `grep -rn "get_participants_report" src/ tests/` — пусто, подтверждён
  мёртвый код без вызывающей стороны (CLI-команды не было).

## Тесты, закреплявшие снятый режим — что сделано

QA-author не трогал существующие файлы (red line роли). Правка — эта задача:

- **Удалены целиком** (закрывали ровно снятую ветку, не сценарий): `test_ac_fr1_1/1_2/2_1/2_2/
  3_2/6_2`, `test_ac_nfr2_*` (`test_auth_modes.py`); `test_ac_fr5_1/1b`,
  `test_diagnostics_403_empty_body_...`, `test_ac_fr11_1/2`, `test_auth_status_apikey_*`
  (`test_diagnostics.py`); `test_nfr7_*_apikey_mode_refuses_before_network_call` (`test_calendar.py`,
  `test_meeting_cancel.py`, `test_meeting_scheduling.py`, `test_rooms.py`); `test_ac_10_4`,
  `test_ac_10_5_secret_not_in_apikey_refusal_message` (`test_search_contacts.py`);
  `test_build_download_url_quotes_space_correctly`, `test_ac_fr7_2_...`,
  `test_r3_apikey_mode_does_not_validate_quality_against_available_list` (`test_download.py`);
  `test_ac_fr9_2_archive_reads_beyond_single_page` (`test_pagination.py`);
  `test_personal_api_key_wins_over_file` (`test_token_file.py` — координатор указал явно).
- **Мигрированы** (сценарий остаётся, форма вызова меняется `personal_api_key=` →
  `session_token=`, `.auth_mode` → `.auth_credential`, `dict[AuthMode, ...]` → плоский):
  `test_ac_fr5_2/2b/3` (`test_diagnostics.py`), `test_ac_fr11_3` (убран мёртвый после удаления
  поля ассерт `status.scopes is None`), `test_auth_status_network_error_is_not_reported_as_dead_key`,
  `test_secret_not_in_auth_error_message`/`test_secret_not_in_generic_exception_str_or_repr`
  (`test_secret_masking.py`), `test_settings_reads_token_file_when_env_empty`
  (`test_token_file.py`), `test_settings_requires_session_token` (`test_config.py`),
  `test_operation_profiles_*` (`test_auth_modes.py`, `test_meeting_cancel.py`,
  `test_search_contacts.py` — итерация по плоской таблице вместо `dict[AuthMode, ...]`).
- **`test_reconciliation.py`** (4 функции, не в исходном списке координатора — обнаружено
  прогоном): фикстуры были в форме api-key-пагинации (`entities`/`nextPageToken`) без
  `KTALK_SESSION_TOKEN` — переведены на session-форму (`recordings`) + добавлена вторая,
  пустая, страница (`pagination.skip_pages` продолжает после ЛЮБОЙ непустой страницы,
  не только полной, — до сих пор так работало и под сессией; под api-key `nextPageToken:
  null` останавливал обход за один запрос, отсюда расхождение стало видно только сейчас).
- **`test_cli_content.py::test_list_archive_json_valid`** переименован в
  `test_list_archive_refuses_before_network_call` — прежний ассерт (`rc == 0`, пустой список)
  проверял поведение снятого режима; новый проверяет ADR-025 п.4 буквально.
- Найдено сверх списка координатора (19 файлов): `test_calendar.py`, `test_download.py`,
  `test_meeting_cancel.py`, `test_meeting_scheduling.py`, `test_rooms.py` — каждый нёс ровно
  один `test_nfr7_*_apikey_mode_refuses_before_network_call`, не отражённый в исходном
  перечне. Список координатора был неполон, не неверен — расхождение фактическое, не спор
  о корректности теста.

## Замер до/после

```
uv run pytest tests/test_fr42_single_credential_source.py \
  tests/test_fr43_legacy_key_removal_warning.py \
  tests/test_fr44_auth_status_accepted_rejected.py -q
  → до:    10 failed, 4 passed  (координатор ожидал 11 красных — фактически 10;
           test_fr44_3_probe_rejected_note_does_not_claim_validity уже проходил на
           сегодняшнем коде, расхождение зафиксировано координатору отдельным сообщением)
  → после: 14 passed

uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8
  → 591 passed, 20 failed, 11 errors — все 20+11 вне периметра этой задачи:
    test_formatters.py (2 функции), test_fr47_missing_fields_completeness.py (3),
    test_fr48_doctor_summary_diagnostics.py (14 + 11 error) — ADR-026/другой эпик,
    команда `doctor` не реализована; ни один не ссылается на AuthMode/PERSONAL_API_KEY
    иначе как defensive `monkeypatch.delenv` (проверено grep'ом построчно).

bash scripts/check.sh --fast
  → изначально ✗ (check-hooks-path.sh: core.hooksPath общий на все worktree репозитория
    задан в АБСОЛЮТНОЙ форме, указывает на .githooks ГЛАВНОГО дерева — задокументированный
    в самом гейте случай, ADR-081 Д7/SA-097 §3.7, ремонт назван текстом ошибки:
    `bash scripts/install-hooks.sh`, переустанавливает ключ в относительной форме).
    После `bash scripts/install-hooks.sh` (не git-merge/archive/push/task-close —
    легитимная переустановка конфигурации по прямому указанию самого гейта) — ✓ passed.
    Инфраструктурная находка, не код этой задачи; затрагивает shared `.git/config`
    репозитория, применимо ко всем worktree.
```

## Объём (замер координатора)

`grep -rn "PERSONAL_API_KEY" src/ tests/ README.md | wc -l` → 93 (было 126 на входе задачи).
Остаток — `content/` (не чистится, правило трёх домов) плюс докстринги/комментарии тестов,
исторически объясняющие миграцию (`personal_api_key=` → `session_token=`), и однократное
предупреждение FR-43 (называет переменную текстом, не значением).

## Что НЕ реализовывалось (по границам ADR-025)

- Каскад пяти capability-спек, противоречащих факту снятия режима (`recording-data-access`,
  `room-diagnostics` и три описательных) — явно отложен ADR-025 п.6, отдельная задача SA.
- Удаление CLI-подкоманды `list-archive` — решение SA (ADR-025 «Альтернативы»): громкий
  отказ до сети дешевле и информативнее исчезновения команды.
- Публикация 3.0.0 в PyPI и правка `pyproject.toml` — отдельная задача релиза, санкция
  владельца, явно выведена из этой задачи координатором.
