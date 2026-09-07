---
title: Требования
---

Требования и acceptance-критерии. Пишет `/nauta:ba`, проверяет
`/nauta:pipelines:ba-acceptance` перед закрытием эпика.

| Требование | Фаза | Статус |
|------------|------|--------|
| [Персональный API-ключ и расширение возможностей](personal-api-key.md) | Production | Superseded |
| [Единственный режим авторизации — сессионный токен](single-auth-mode.md) | Production | Draft |
| [Комнаты, календарь и планирование встреч](rooms-calendar-scheduling.md) | Production | Draft |
| [Наблюдаемость момента последней синхронизации реестра](registry-sync-observability.md) | Production | Draft |
| [Обнаружимость подмены транскрипта под конкуренцией](transcript-identity-observability.md) | Production | Draft |
| [Полное перечисление недостающих полей и сводная диагностика окружения](cli-diagnostics-completeness.md) | Production | Draft |
| [Плагин ktalk в произвольном проекте](ktalk-plugin.md) | Pilot | Draft |
| [Онбординг плагина ktalk](ktalk-plugin-onboarding.md) | — | Переехало в `ktalk-plugin` |
| [Промт-поверхность плагина ktalk](ktalk-plugin-meetings.md) | — | Переехало в `ktalk-plugin` |
| [Калибровка промта анализа](ktalk-plugin-analysis-calibration.md) | — | Переехало в `ktalk-plugin` |
| [Канал дефектов промта](ktalk-prompt-defect-channel.md) | — | Переехало в `ktalk-plugin` |

Функциональность v0.1–v0.4 разрабатывалась по спекам в
[docs/superpowers/specs/](../../docs/superpowers/specs/) до подключения контура. Ретроспективно
их не переписываем — новые фичи начинаются здесь.
