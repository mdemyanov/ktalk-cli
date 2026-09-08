# ktalk-cli — API Контур.Толк

Справочник вынесен из корневого `CLAUDE.md`: грузится только при работе под `src/`.

## Контракт API
- OpenAPI спецификация (справочник, **есть расхождения с реальностью**): `talk.public.api-api-2.json`
- Base URL: https://your-domain.ktalk.ru
- **Режим авторизации один — сессионный токен** ([ADR-025](content/00-project/adr/ADR-025-single-auth-mode.md)
  снял двухрежимность [ADR-003](content/00-project/adr/ADR-003-auth-modes.md) в 3.0.0):
  `sessionToken=` в query при чтении, заголовок `Authorization: Session <token>` при записи
  (`meeting_scheduling.py`). `X-Auth-Token` не шлётся ни одним запросом. `KTALK_PERSONAL_API_KEY`
  не читается ни на одном шаге: заданная, она даёт однократное предупреждение в stderr
  (`config.py:181-187`) и больше ничего.
- **Порядок источников токена, он же ловушка эксплуатации** — первый непустой выигрывает:
  `KTALK_SESSION_TOKEN` (окружение или `.env` рабочего каталога) > `~/.config/ktalk-mcp/token`
  (`token_file.py`, DEV-018). Файл читается валидатором `Settings` **только когда переменная
  пуста** (`config.py:111-130`) — поэтому переменная переживает `ktalk token set` и делает
  ротацию токена невидимой: `auth-status` печатает `alive: false` на свежезаписанный рабочий
  файл. Разведение — `env -u KTALK_SESSION_TOKEN ktalk auth-status` против обычного вызова;
  процедура — [OPS-003](content/70-operations/OPS-003-env-var-shadows-token-file.md). Права
  шире `0600` — файла как будто нет. Запись — `ktalk token set -`, формат проверяется до записи.
- **Путь есть не у каждой операции** — интеграторский контур (`/api/Domain/*`, `/api/Recordings/*`,
  `/api/ConferenceReports/*`) отдаёт 401/403 по сессии, поэтому пути живут в таблице
  `OPERATION_PROFILES` (`endpoints.py`, реэкспорт через `auth.py`), а не хардкодом в методах.
  Профиль `None` (`list_archive`) — отказ до сети, код возврата 1.
- Пути под сессией: `GET /api/recordings`, `/api/recordings/{id}`, `/api/conferencesHistory/{key}`,
  `/api/recordings/{key}/transcript`, `/api/recordings/v2/{key}/summary`,
  `/api/recordings/{key}/summary/{type}`

### Поведение API, проверенное эмпирически (спеке здесь верить нельзя)
- `top` максимум **100**, не 1000: `400 «The field Top must be between 1 and 100»`.
- `nextPageToken` во внутреннем контуре **не существует** — пагинация только через `skip`.
- `startFrom`/`startTo` **игнорируются**: окно дат обеспечивает клиент (`clip_to_window`),
  обход прекращается на первой странице за порогом. Выдача отсортирована от новых к старым.
- `maxParticipantCount` в списке имеет максимум 10 и дефолт 6 — полный состав участников
  берётся дообогащением по каждой записи, а не из списка.
- Чат требует необъявленный в спеке параметр `channel` (рабочее значение `general`).
- **401 ≠ 403**: 401 — ключ/токен невалиден, 403 — валиден, но не хватает scope. Тело 403
  обычно пустое, диагностика строится на коде ответа и требуемом scope операции.
