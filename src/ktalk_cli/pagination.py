"""Единый асинхронный итератор постраничного чтения (FR-9, FR-14).

`paginate_pages` — форма-независимый движок термination-логики: продолжает, пока
очередная страница непустая И следующий курсор истинный; останавливается на первом
же из двух отрицательных сигналов. Не полагается на конкретное имя поля пагинации
в ответе API — это и закрывает Ф-3 (`/api/recordings` не отдаёт `nextPageToken`).

`skip_pages` — offset-адаптер (session-список записей, архив, FR-9/FR-14): жёстко
клэмпит размер страницы в [1, 100] (закрывает регрессию `top=1000`, зонд Ф-2) и
продолжает по `skip`, пока очередной запрос не вернёт пустую страницу — намеренно
НЕ останавливается на «короткой», но непустой странице: домен ни разу не подтвердил,
что API отдаёт заведомо неполные непоследние страницы, а недоверие отсутствующему
полю (Ф-3) распространяется и на предположение «короткая = последняя».

`clip_to_window` — клиентское окно дат (Ф-15). API игнорирует `startFrom`/`startTo`:
зонд показал побитово одинаковую выдачу с фильтром и без него, а описания этих
параметров у v1 и v2 в спеке вдобавок зеркальны. Поэтому окно `--days` обеспечивает
клиент, а не сервер. Ранняя остановка опирается на `orderMode=byTimeNewFirst`
и проверена на пяти страницах подряд (Ф-16): порядок строго убывающий внутри
страницы и монотонный между страницами.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

Cursor = Any
FetchPage = Callable[[Cursor | None], Awaitable[tuple[list[dict], Cursor | None]]]


def clip_to_window(
    items: list[dict],
    start_from: str | None,
    *,
    date_key: str = "createdDate",
) -> tuple[list[dict], bool]:
    """Оставляет записи не старше `start_from`, сообщая, исчерпано ли окно.

    Возвращает `(kept, exhausted)`. `exhausted=True` означает, что страница
    содержала запись старше порога — при сортировке от новых к старым все
    последующие страницы заведомо вне окна и запрашивать их не нужно.

    Записи без разбираемой даты не отбрасываются: пустой `createdDate` — это
    неизвестность, а не «старая запись», и терять её молча нельзя.
    """
    if not start_from:
        return items, False
    kept: list[dict] = []
    exhausted = False
    for item in items:
        raw = (item.get(date_key) or "")[:10]
        if not raw:
            kept.append(item)
            continue
        if raw < start_from[:10]:
            exhausted = True
            continue
        kept.append(item)
    return kept, exhausted


async def paginate_pages(fetch_page: FetchPage) -> AsyncIterator[list[dict]]:
    """Обходит страницы через `fetch_page(cursor) -> (items, next_cursor)`."""
    cursor: Cursor | None = None
    while True:
        items, next_cursor = await fetch_page(cursor)
        if not items:
            return
        yield items
        if not next_cursor:
            return
        cursor = next_cursor


def skip_pages(
    fetch: Callable[[int, int], Awaitable[dict]],
    page_size: int = 100,
    items_key: str = "recordings",
) -> FetchPage:
    """Строит `fetch_page` для offset-пагинации поверх `fetch(skip, top) -> raw_dict`."""
    page_size = max(1, min(int(page_size), 100))

    async def fetch_page(cursor: int | None) -> tuple[list[dict], int | None]:
        skip = cursor or 0
        raw = await fetch(skip, page_size)
        items = raw.get(items_key) or []
        next_cursor = skip + len(items) if items else None
        return items, next_cursor

    return fetch_page

    return fetch_page
