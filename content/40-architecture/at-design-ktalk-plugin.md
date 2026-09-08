---
title: "AT-design: плагин ktalk в произвольном проекте"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# AT-design: плагин ktalk в произвольном проекте

Тест-дизайн и failing stubs для волны 3 (0.7.0). Источник AC —
[ktalk-plugin.md](../30-requirements/ktalk-plugin.md) (FR-20…FR-25, NFR-11…NFR-16).
Архитектурный контекст — [ktalk-plugin-spec.md](ktalk-plugin-spec.md) (SA-003:
формат `.ktalk.toml`, discovery, маршрутизация, контракт деградации) и
[ADR-013-central-transcript-store-spec.md](ADR-013-central-transcript-store-spec.md)
(SA-002: корень хранилища, приоритет разрешения пути, контракт конкурентного
доступа, контракт миграции). [ADR-012-plugin-boundary.md](../00-project/adr/ADR-012-plugin-boundary.md)
задаёт границы (§2а: CLI приоритетен, MCP вторичен) — используется для отсечения
того, что тестируется в этом пакете, от того, что живёт в отдельном
git-репозитории плагина (недостижимо для `pytest` этого репозитория).

## Как читать таблицу

Тот же формат, что [at-design-rooms-calendar.md](at-design-rooms-calendar.md):
`unit`/`integration`/`manual` по типу, статус `red (stub)`/`green (guard)`/
`manual only`. Отдельная колонка «Модуль» — рабочее имя, которое Dev волен
переименовать (одна правка импорта на тест, не переписывание сценария).

## Покрытие AC

### FR-20 — Discovery `.ktalk.toml` (`tests/test_host_config.py`, новый модуль `host_config.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-20 AC-1 | Конфиг есть -> пути берутся из него, не из констант | `load_host_config(path).registry["db_path"]`/`.directories`/`.routing` читаются из TOML | unit | `test_ac_fr20_1_config_present_registry_db_path_is_read_from_file`, `test_ac_fr20_1_config_present_routing_and_directories_read_from_file` | red (stub) |
| FR-20 AC-2 | Конфига нет вовсе -> тихий машинный дефолт, не ошибка | `discover_host_config()` возвращает `None`, не поднимает исключение | integration | `test_ac_fr20_2_no_config_file_discovery_returns_none_without_raising` | red (stub) |
| FR-20 AC-2 (boundary) | Пустой валидный TOML эквивалентен «конфига нет» по каждому ключу | `.registry.get("db_path") is None`, `.directories == {}` | unit | `test_ac_fr20_2_empty_valid_toml_equivalent_to_no_config_per_key` | red (stub) |
| FR-20 AC-3 | Малформенный TOML-синтаксис -> именованная ошибка, не тихий откат | `HostConfigError`, путь файла в тексте | unit | `test_ac_fr20_3_malformed_toml_syntax_raises_host_config_error_naming_file` | red (stub) |
| FR-20 AC-3 (boundary) | Неизвестный top-level ключ (опечатка `[routng]`) -> ошибка, не тихое игнорирование | `HostConfigError` | unit | `test_ac_fr20_3_unknown_top_level_key_raises_host_config_error` | red (stub) |
| FR-20 AC-3 (boundary) | `integrations.qmd` не bool -> ошибка | `HostConfigError` | unit | `test_ac_fr20_3_non_bool_integrations_qmd_raises_host_config_error` | red (stub) |
| FR-20 AC-3 (boundary) | Значение `routing.*` не строка -> ошибка | `HostConfigError` | unit | `test_ac_fr20_3_non_string_routing_value_raises_host_config_error` | red (stub) |
| FR-20 AC-3 (доп.) | `discover_host_config` не глотает `HostConfigError` малформенного файла молчаливым откатом на дефолт | исключение доходит до вызывающей стороны | unit | `test_ac_fr20_3_malformed_file_does_not_silently_fall_back_to_default` | red (stub) |
| Discovery §1 | `${CLAUDE_PROJECT_DIR}` задан -> строго по этому корню, читает конфиг | `discover_host_config()` находит файл ровно по `$CLAUDE_PROJECT_DIR/.ktalk.toml` | integration | `test_discovery_claude_project_dir_set_reads_config_at_exact_root` | red (stub) |
| Discovery §1 (boundary) | `${CLAUDE_PROJECT_DIR}` задан, файла там нет -> `None`, обхода вверх НЕТ (даже если у родителя есть конфиг) | `discover_host_config() is None`, несмотря на валидный конфиг родителя | integration | `test_discovery_claude_project_dir_set_but_file_absent_returns_none_no_walkup` | red (stub) |
| Discovery §2 | Голый CLI (нет `${CLAUDE_PROJECT_DIR}`) -> обход вверх от cwd находит ближайший конфиг | вложенная иерархия каталогов, `db_path` из найденного файла | integration | `test_discovery_bare_cli_walks_up_from_cwd_to_nearest_config` | red (stub) |
| Discovery §2 (boundary) | Обход останавливается на границе `.git` — конфиг каталога-предка чужого репо не подхватывается | `discover_host_config() is None`, хотя у предка есть валидный конфиг | integration | `test_discovery_bare_cli_stops_at_git_boundary_before_ancestor_config` | red (stub) |
| Discovery §2 (boundary) | Нет `.git` и нет конфига до корня ФС -> `None`, не зависает | — | integration | `test_discovery_bare_cli_stops_at_filesystem_root_if_no_git_and_no_config` | red (stub) |
| Discovery §2 (boundary) | Конфиг лежит ровно в каталоге с `.git` (граница) -> используется | — | integration | `test_discovery_bare_cli_config_at_git_boundary_itself_is_used` | red (stub) |
| Discovery §4 | Нет слияния конфигов уровней — ближайший найденный побеждает целиком, ключи родителя не подмешиваются | `directories.get("people") is None`, хотя у предка ключ объявлен | integration | `test_discovery_no_merge_of_two_levels_nearest_wins_entirely` | red (stub) |

### FR-23 — Приоритет разрешения пути реестра, четвёртый источник (`tests/test_config.py`, расширение `config.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-23 AC-1 | Все четыре источника заданы -> `--db` | `resolve_db_path(flag, host_config=...)` — регрессия существующего порядка | unit | `test_ac_fr23_1_all_four_sources_given_flag_wins` | red (stub, `TypeError` — сигнатура ещё не принимает `host_config`) |
| FR-23 AC-2 | `--db` не задан, заданы env и конфиг хозяина -> `KTALK_REGISTRY_DB` | — | unit | `test_ac_fr23_2_flag_absent_env_and_host_config_given_env_wins` | red (stub) |
| FR-23 AC-3 | Только конфиг хозяина задаёт путь -> он, не машинный дефолт | путь конфига, не `95_TRANSCRIPTS/.registry.db` | unit | `test_ac_fr23_3_only_host_config_given_host_config_wins_over_machine_default` | red (stub) |
| FR-22 AC-1 (регрессия сюда же) | Ни один из четырёх источников не задан -> машинный дефолт, не относительный `95_TRANSCRIPTS/.registry.db` | `not resolved.is_relative_to(Path.cwd())` | unit | `test_resolve_db_path_none_of_the_four_sources_falls_through_to_machine_default` | red (stub) |
| FR-23 AC-4 (ktalk-mcp-ds6) | Относительный `db_path` джойнится с `host_config.path.parent`, не с cwd | `resolve_db_path(None, host_config=...)` — cwd намеренно другой каталог | unit | `test_fr23_ac4_relative_db_path_joins_against_host_config_dir_not_cwd` | red (stub) |
| FR-23 AC-5 (ktalk-mcp-ds6) | Абсолютный `db_path` — как есть, каталог `.ktalk.toml` не участвует | `resolved == absolute_db`, `not resolved` внутри каталога конфига | unit | `test_fr23_ac5_absolute_db_path_ignores_host_config_dir_even_when_path_set` | **green** (уже верно сегодня — абсолютная ветка не трогает `host_config.path`) |
| FR-23 AC-4 (masked failure, ADR-013-spec edge case) | `host_config.path is None` + относительный `db_path` -> исключение, не тихий откат на cwd | `pytest.raises(Exception)` | unit | `test_fr23_ac4_host_config_path_none_with_relative_db_path_raises_not_silent_cwd_fallback` | red (stub) |
| FR-23 AC-4 / NFR-14 AC-2 (поток данных п.4) | `warn_if_sync_dir` применяется к итоговому джойненному пути, не к голому относительному `db_path` | маркер `Dropbox` в каталоге конфига, не в самом `db_path` — предупреждение обязано появиться | unit | `test_fr23_ac4_warn_if_sync_dir_applies_to_final_joined_path_not_bare_relative_value` | red (stub) |
| FR-23 AC-4 (интеграция, discovery-режим 2 — обход вверх) | Буквальное воспроизведение симптома: `cd .../95_TRANSCRIPTS && ktalk dashboard` из отчёта владельца | `main(["dashboard", "--json"])`, `rc == 0`, cwd — подкаталог хранилища | integration | `test_fr23_ac4_bare_cli_relative_db_path_from_subdirectory_reproduces_dashboard_symptom` (`tests/test_cli_host_config_wiring.py`) | red (stub) |
| FR-23 AC-4 (интеграция, discovery-режим 1 — `CLAUDE_PROJECT_DIR`) | Относительный `db_path` резолвится от `CLAUDE_PROJECT_DIR`, cwd — не предок и не потомок проекта | `main(["list", "--json"])`, `rc == 0` | integration | `test_fr23_ac4_explicit_claude_project_dir_relative_db_path_ignores_unrelated_cwd` (`tests/test_cli_host_config_wiring.py`) | red (stub) |

### FR-21 — Работа без vault-раскладки (`tests/test_fr21_no_vault_layout.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-21 AC-1 | `list`/`show`/`mark-*`/`dashboard`/`export` работают в чистом проекте без `.ktalk.toml`/vault-каталогов | `rc == 0` на 5 командах, `95_TRANSCRIPTS`/`20_MEETINGS` не в stderr, каталоги не создаются | integration | `test_ac_fr21_1_list_show_mark_dashboard_export_work_without_ktalk_toml_or_vault_dirs` | **green** (уже верно сегодня — единственная зависимость этих команд от layout — явный `--db`) |
| FR-21 AC-1 (доп.) | `export` пишет зеркало рядом с БД без vault-каталогов рядом | `registry.md` создаётся | integration | `test_ac_fr21_1_export_mirror_written_relative_to_db_path_not_requiring_vault_dirs` | **green** |
| FR-21 AC-2 | MCP read-инструмент регистрируется/работает независимо от отсутствия host-раскладки | `ktalk_get_transcript` в `list_tools()` из проекта без конфига | integration | `test_ac_fr21_2_mcp_read_tool_json_output_shape_unaffected_by_absence_of_host_layout` | **green** |

Все три теста этой секции — регрессионные снимки (`green (guard)`): поведение уже
корректно сегодня (команды реестра адресуют только `--db`, MCP read-инструменты не
читают файлы хозяина вовсе), но раньше это явно не было зафиксировано тестом —
регрессия в discovery-коде (FR-20/FR-23), который появится следующим, теперь имеет
барьер.

### FR-22 / NFR-14 / NFR-15 — Машинный дефолт хранилища, облачная синхронизация, права (`tests/test_store.py`, новый модуль `store.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-22 AC-1 | Дефолт — вне cwd | `not root.is_relative_to(project_cwd)` | integration | `test_ac_fr22_1_store_root_is_not_inside_cwd` | red (stub) |
| — (доп.) | `$XDG_DATA_HOME` задан -> используется | — | unit | `test_store_root_respects_xdg_data_home_when_set` | red (stub) |
| — (boundary, ADR-013-spec) | `$XDG_DATA_HOME=""` (пустая строка) трактуется как «не задано» | путь падает на `$HOME/.local/share`, не на путь `""` | unit | `test_store_root_xdg_data_home_empty_string_falls_back_like_unset` | red (stub) |
| FR-22 AC-2 | Два «проекта» без своего пути адресуют один и тот же файл | два вызова из разных cwd дают равный путь | integration | `test_ac_fr22_2_two_calls_from_different_cwd_resolve_to_same_root` | red (stub) |
| FR-22 AC-3 / NFR-15 | Каталог хранилища создаётся впервые с правами `0700` | `stat.S_IMODE(...) == 0o700` | integration | `test_ac_fr22_3_store_root_created_with_owner_only_permissions` | red (stub) |
| NFR-15 (доп.) | Файл БД реестра — `0600` при первом создании | — | integration | `test_nfr15_registry_db_file_created_with_0600` | red (stub) |
| NFR-14 | Путь внутри `Library/Mobile Documents` (iCloud) детектится | `detect_sync_dir(path) == (True, ...)` | unit | `test_nfr14_detect_sync_dir_true_for_icloud_marker` | red (stub) |
| NFR-14 | Путь внутри `Dropbox` детектится | — | unit | `test_nfr14_detect_sync_dir_true_for_dropbox_marker` | red (stub) |
| NFR-14 | Обычный путь — не детектится | `detect_sync_dir(path) == (False, ...)` | unit | `test_nfr14_detect_sync_dir_false_for_ordinary_path` | red (stub) |
| NFR-14 (boundary) | `MyDropboxBackup/` НЕ должен ложно сработать на маркер `Dropbox` (сегментация по каталогу, не substring) | — | unit | `test_nfr14_detect_sync_dir_no_false_positive_on_marker_as_substring_not_segment` | red (stub) |
| NFR-14 AC-1 | Резолвленный машинный дефолт — вне известных каталогов синхронизации | `detect_sync_dir(resolve_store_root()) == (False, ...)` | integration | `test_ac_fr22_1_nfr14_machine_default_is_never_flagged_as_sync_dir` | red (stub) |
| NFR-14 AC-2 | Явный путь внутри каталога синхронизации -> предупреждение в stderr, не блокировка | текст маркера в stderr/stdout, функция не поднимает исключение | unit | `test_nfr14_2_explicit_path_inside_sync_dir_produces_warning_not_block` | red (stub) |

### NFR-12 — Миграция реестра, явный обратимый шаг (`tests/test_store_migration.py`, новый модуль `store_migration.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| NFR-12 AC-1 | Открытие реестра само по себе не переносит файл | `source.exists()` после обычной операции `Registry(source)` | integration | `test_ac_nfr12_1_opening_registry_alone_does_not_move_or_copy_source_file` | **green** (уже верно — `Registry.__init__` не знает про миграцию) |
| NFR-12 AC-2 | Миграция сохраняет все записи без потерь/изменения значений | значения полей источника == значения полей назначения после `migrate_to_central_store` | integration | `test_ac_nfr12_2_migration_preserves_all_records_without_loss_or_value_change` | red (stub) |
| — (доп., «Контракт команды миграции») | Успех -> источник переименован в backup-суффикс, не удалён | `not source.exists()`, `glob(".registry.db*")` непуст | integration | `test_migration_success_renames_source_to_backup_suffix_not_deleted` | red (stub) |
| — (boundary) | Сверка дампа не совпала -> отказ, источник не тронут, целевой файл удалён (не частичная копия) | `MigrationVerificationError`, `source.exists()`, `not target.exists()` | integration | `test_migration_dump_mismatch_aborts_source_untouched_target_removed` | red (stub) |
| — (boundary, ADR-013-spec edge case) | Повторный вызов при уже существующем целевом файле не должен тихо перезаписать более новые данные | `MigrationTargetExistsError`, запись `c` (добавленная после первой миграции) не пропадает | integration | `test_migration_repeated_call_does_not_silently_overwrite_newer_target_data` | red (stub) |

NFR-12 AC-3 (откат) — **manual only**, см. «Не покрываем» ниже.

### NFR-13 — Конкурентный доступ двух процессов (`tests/test_concurrency.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| NFR-13 AC-1 | Два процесса пишут параллельно -> обе успешны, `PRAGMA integrity_check == 'ok'`, без потерь | реальный `multiprocessing.Process` x2, подсчёт строк после | integration | `test_ac_nfr13_1_two_processes_concurrent_writes_integrity_ok_no_data_loss` | **green** |
| NFR-13 AC-2 | Конфликт на одной записи (`done` vs `skipped` одновременно) -> ровно одно из двух значений | итог `in ("done", "skipped")` | integration | `test_ac_nfr13_2_conflicting_write_to_same_record_yields_exactly_one_deterministic_outcome` | **green** |
| — (контракт теста, ADR-013-spec п.3) | Исчерпание `busy_timeout=5000` -> `sqlite3.OperationalError` с узнаваемым текстом «занято» | держим эксклюзивную блокировку 7с из отдельного процесса, вторая сторона получает распознаваемую ошибку | integration | `test_nfr13_busy_timeout_exhausted_raises_recognizable_operational_error` | **green** |

Все три теста этой секции — уже **green** сегодня: ADR-013 §4 прямо заявляет
«новый механизм блокировки не вводится» — задача теста была не создать
функциональность, а **доказать её достаточность** на реальных процессах, чего
раньше не делал ни один тест (постановка, риск 2, не проверено эмпирически). Тесты
остаются в suite как регрессионный барьер: если будущая правка `registry.py`
случайно ослабит WAL/`busy_timeout`, эта тройка покраснеет.

### `ktalk config show` — CLI-контракт (`tests/test_cli_config_show.py`, расширение `cli.py`)

| Сценарий | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|
| JSON отражает распарсенный `.ktalk.toml` | `out["registry"]["db_path"]`/`out["directories"]["people"]` | integration | `test_config_show_json_reflects_ktalk_toml` | red (stub) |
| Конфига нет -> дефолты без ошибки | `rc == 0` | integration | `test_config_show_no_config_file_prints_defaults_without_error` | red (stub) |
| Необъявленный ключ `routing.*` отсутствует в JSON, не `null` | `"committee" not in out["routing"]` | integration | `test_config_show_undeclared_routing_key_absent_from_json_not_null` | red (stub) |
| Малформенный конфиг -> ненулевой код возврата, stderr называет файл | `rc != 0`, путь файла в stderr | integration | `test_config_show_malformed_config_nonzero_exit_and_stderr_names_file` | red (stub) |
| Команда — `_REGISTRY_FREE_COMMANDS` (не требует доступной БД) | `rc == 0` с заведомо недостижимым `--db` | integration | `test_config_show_is_registry_free_command_does_not_require_db` | red (stub) |
| Человекочитаемый вывод по умолчанию — не JSON | `json.loads` на выводе без `--json` поднимает `JSONDecodeError` | integration | `test_config_show_human_readable_without_json_flag` | red (stub) |

### FR-24 — Явная деградация `qmd`/`directories.people`

**Не покрыто автоматически в этом пакете** — см. «Не покрываем» ниже: механизм
пометки живёт в тексте промта skill/agent (плагин), а плагин — отдельный
git-репозиторий (ADR-012 §4), недостижимый для `pytest` этого пакета. Механическая
предпосылка, от которой зависит промт (`ktalk config show --json` отдаёт
отсутствующий ключ как отсутствующий, не `null`), покрыта тестом
`test_config_show_undeclared_routing_key_absent_from_json_not_null` выше — это
необходимое, но не достаточное условие FR-24 AC-1/AC-2.

## Boundary cases (сверх дословных формулировок AC)

- `${CLAUDE_PROJECT_DIR}` задан, но файла нет — обхода вверх нет вообще, даже если
  у родителя есть валидный конфиг (иначе платформенная переменная перестаёт быть
  авторитетной).
- Обход вверх упирается в `.git` ДО нахождения `.ktalk.toml` — граница проекта
  жёсткая, конфиг каталога-предка чужого репозитория не подхватывается.
- Обход вверх находит конфиг ровно в каталоге с `.git` (не выше и не ниже).
- Пустой валидный `.ktalk.toml` (ноль ключей) — не ошибка, каждый ключ трактуется
  как отсутствующий отдельно.
- `$XDG_DATA_HOME=""` (пустая строка) — не то же самое, что «путь равен пустой
  строке»: трактуется как «не задано».
- `MyDropboxBackup/` не должен ложно сработать на маркер `Dropbox` — сегментация
  эвристики по границе каталога, не substring-поиск.
- Повторный вызов команды миграции на уже занятый целевой путь не должен тихо
  перезаписать данные, добавленные в целевой файл после первой миграции (другим
  проектом).
- `--db` указывает на заведомо недостижимый путь — `ktalk config show` всё равно
  отрабатывает (реестр не открывается вовсе для этой команды).
- (ktalk-mcp-ds6) Относительный `db_path` резолвится из подкаталога хранилища,
  не только из корня проекта — воспроизводит буквальный отчёт владельца
  (`cd .../95_TRANSCRIPTS && ktalk dashboard`).
- (ktalk-mcp-ds6) Дискавери-режим 1 (`CLAUDE_PROJECT_DIR`) и режим 2 (обход
  вверх) покрыты join'ом относительного `db_path` по отдельности — происхождение
  `host_config.path` разное, но целевое значение базы join одно и то же
  («Контракт с QA-author» ADR-013-spec).
- (класс «malformed/mistyped input», ktalk-mcp-ds6) N/A для новых тестов этого
  дефекта: неверно типизированный/опечатанный `db_path` (не строка, неизвестная
  секция) уже покрыт FR-20 AC-3 (`tests/test_host_config.py`,
  `test_ac_fr20_3_*`) на слое парсинга/валидации `.ktalk.toml` — до того, как
  `resolve_db_path` вообще видит значение. Join-дефект ds6 живёт строго после
  этого шага (значение уже прошло валидацию типа), дублировать проверку типа
  здесь нечем.

## Error cases

- Малформенный TOML-синтаксис `.ktalk.toml` — `HostConfigError`, называющая файл.
- Неизвестный top-level ключ (опечатка секции) — `HostConfigError`, не тихое
  игнорирование секции.
- Неверный тип значения (`integrations.qmd` не bool, `routing.*` не строка) —
  `HostConfigError`.
- Сверка дампа источник/копия не совпала при миграции — `MigrationVerificationError`,
  источник не тронут, целевой файл удалён (не остаётся частичной копией).
- Повторная миграция на занятый целевой путь — `MigrationTargetExistsError`, не
  тихая перезапись.
- Исчерпание `busy_timeout=5000` — `sqlite3.OperationalError` с узнаваемым текстом
  «занято» (locked/busy), не generic traceback.
- `ktalk config show` на малформенном конфиге — ненулевой код возврата, диагностика
  в stderr, не тихий переход на дефолт.
- (ktalk-mcp-ds6, masked failure) `host_config.path is None` при относительном
  `db_path` — исключение, не тихий откат на резолюцию от cwd (ручная сборка
  `HostConfig`, не через `discover_host_config`; в проде `path` заполняется
  всегда, но контракт вызывающей стороны обязан явно проваливаться, а не
  молчать, если это условие нарушено).

## Не покрываем (вне scope этого пакета)

| Сценарий | Почему нельзя автоматизировать в `pytest` этого репозитория |
|---|---|
| FR-24 AC-1/AC-2 (реальная пометка недоступности сопоставления профиля в отчёте обработки встречи) | Механизм пометки — текст промта `agents/ktalk-processor.md` (плагин), который по ADR-012 §4 живёт в **отдельном git-репозитории**, не в этом пакете. `ktalk-plugin-spec.md` сама называет способ проверки — статический grep текста промта на отсутствие захардкоженных путей/на наличие явной пометки — задача QA-author того репозитория, не этого. Здесь покрыта только механическая предпосылка (`config show` отдаёт отсутствующий ключ как отсутствующий) |
| «Каталог объявлен, но физически отсутствует» — отдельная пометка от «не объявлен» | Различение — ответственность промта/агента (`host_config.py` по границам спеки «не пишет файлы и не создаёт каталоги — только читает и валидирует», проверку `os.path.isdir` на стороне кода пакета спека не поручает). Не покрывается здесь тем же аргументом, что и FR-24 выше |
| NFR-12 AC-3 (откат миграции) | Явно ручная проверка по AC — «критерий приёмки — наличие и выполнимость шагов отката, а не автоматизация» (требование дословно). Runbook OPS-001 — задача DevOps, не этого пакета |
| NFR-14 (детекция под РЕАЛЬНОЙ iCloud/Dropbox-синхронизацией) | ADR-013 сама называет это неподтверждённым эмпирически (RES-001 находка 11: `~/Documents` на исследуемой машине не под синхронизацией) — эвристика тестируется как чистая функция над строкой пути (покрыто), боевое поведение под реальным клиентом синхронизации — вне пирамиды, ручная проверка на подходящей машине |
| NFR-11 (полная регрессия живого vault'а `naumen-cto`) | Требует фикстуры, воспроизводящей структуру реального vault'а, которого нет в этом репозитории (`ktalk-mcp` не содержит vault-данных); частично покрыто косвенно через FR-21/FR-23 (приоритет и деградация без layout — обратная сторона того же контракта), прямой сценарий «полный sync -> обработка -> mark-done на живой структуре» — ответственность QA-runner на стороне vault'а, не этого пакета |
| Windows-эквивалент прав `0700`/`0600` (NFR-15) | Требование само оставляет это как «ручная проверка эквивалентного ACL» на не-POSIX платформах; тесты этой волны — POSIX-only (macOS/Linux CI) |

## Допущения, требующие внимания Dev (не баги AC, а решения по контракту вызова)

- **Имена новых модулей** (`host_config.py`, `store.py`, `store_migration.py`) и
  функций (`resolve_store_root`, `detect_sync_dir`, `warn_if_sync_dir`,
  `migrate_to_central_store`, `MigrationVerificationError`,
  `MigrationTargetExistsError`) — рабочие гипотезы этой задачи, согласованные со
  «Компоненты»/«Реализовать» ktalk-plugin-spec.md и ADR-013-central-transcript-store-spec.md
  там, где имя явно названо (`host_config.py`, `resolve_store_root`,
  `detect_sync_dir`, `resolve_db_path(host_config=...)`), и придуманные там, где
  спека оставляет имя на усмотрение Dev (`store_migration.py`,
  `migrate_to_central_store`, обе ошибки миграции, `warn_if_sync_dir`). Замена —
  точечная правка импорта на затронутых тестах, сценарии не меняются.
- **`HostConfig` — форма объекта.** Тесты полагаются только на атрибуты
  `.registry`/`.directories`/`.routing` как `dict`-подобные с `.get(...)`, не на
  конкретный тип (`dataclass` vs `pydantic`) — решение Dev (ktalk-plugin-spec.md,
  «Реализовать»: «на усмотрение Dev, без новой зависимости при dataclass»).
- **`resolve_db_path` сигнатура.** Стаб полагается на именованный параметр
  `host_config: HostConfig | None = None`, добавленный к существующей
  `resolve_db_path(cli_db=None)` — без переименования `cli_db`, чтобы не сломать
  22 существующих зелёных теста, использующих позиционный/безымянный вызов.
- **`_dumps_match` как внутренняя точка инъекции.** Тест
  `test_migration_dump_mismatch_aborts_source_untouched_target_removed`
  монки-патчит `store_migration._dumps_match` — предполагает, что построчная
  сверка дампа вынесена в отдельную вызываемую функцию модуля, а не инлайнена
  внутрь `migrate_to_central_store`. Если Dev выберет другую декомпозицию, тест
  укажет на это явно (`AttributeError` на `setattr`, не тихий пропуск).

## Известные конфликты с существующей регрессионной базой

Не обнаружено. Все 356 тестов, существовавших до этой задачи, остаются зелёными
(`uv run pytest` до и после добавления stubs). Из 49 новых тестов этой задачи 7 —
`green (guard)`: 3×FR-21 (регрессия «уже верно сегодня»), 1×NFR-12 AC-1
(конструктор `Registry` не знает про миграцию — уже так), 3×NFR-13 (WAL +
`busy_timeout` уже достаточны — контракт доказан, не создан заново); не создают
конфликта, служат регрессионным снимком на волну. Остальные 42 — `red (stub)`.

## Сводка объёма stub-файлов

| Файл | Тест-функций | Строк |
|---|---|---|
| `tests/test_host_config.py` (новый) | 16 | 249 |
| `tests/test_config.py` (расширен) | +4 | +73 |
| `tests/test_store.py` (новый) | 12 | 186 |
| `tests/test_store_migration.py` (новый) | 5 | 165 |
| `tests/test_concurrency.py` (новый) | 3 | 162 |
| `tests/test_cli_config_show.py` (новый) | 6 | 111 |
| `tests/test_fr21_no_vault_layout.py` (новый) | 3 | 95 |

Ни один файл не приближается к порогу гейта C13 (`test`, T=600, warn) — самый
длинный новый файл 249 строк.

**Итог прогона на момент написания (до реализации Dev):** `uv run pytest` — 42
failed (red stubs этой задачи), 363 passed (356 существующий регрессионный тест до
этой задачи + 7 новых green-guard). `uv run ruff check tests/ src/` — чист.
`bash scripts/check.sh --fast` — `Errors: 0` (3 pre-existing грандфазер-warning, не
связаны с этой задачей).
