# registry-sync-window

## Purpose

Governs how `ktalk sync` bounds a single page request, continues across pages, restricts results
to a client-side date window (because the server does not honor date filters), and exposes the
moment of the last completed sync to read-only consumers without requiring a mutating `sync` call
to observe it. Source: `content/30-requirements/personal-api-key.md` FR-14, FR-16; the last-sync
observability requirement — `content/30-requirements/registry-sync-observability.md` FR-41.

## Requirements

### Requirement: Page size never leaves the server's accepted range

Every list request issued during sync SHALL request between 1 and 100 items per page, regardless
of the caller's configured batch size — the server rejects `top`/`take` values above 100
(`ValidationError`). This SHALL hold for every paginated list surface sync touches (recordings,
participants, archive), not only the top-level recordings list.

#### Scenario: An oversized requested page size is clamped, not sent as-is

- **WHEN** a caller configures a page size larger than 100
- **THEN** every actual request SHALL carry a page-size parameter within `[1, 100]`

### Requirement: Pagination continues until an empty page, independent of a next-page field

The client SHALL continue fetching pages by advancing its own cursor (`skip` for the offset-based
surfaces, the server's `nextPageToken` where the surface provides one) until a page comes back
empty, rather than trusting a next-page-token field that a surface may not populate at all (the
plain recordings list never returns one). A window covering more than one page's worth of records
SHALL yield every record in the window, not only the first page.

#### Scenario: Pagination does not stop after the first page when no next-page field is present

- **WHEN** a list surface returns records without a next-page-token field
- **THEN** the client SHALL keep requesting subsequent pages by advancing `skip`, stopping only on
  an empty page

#### Scenario: A window spanning more than 100 records yields all of them

- **WHEN** a `--days N` window covers more than 100 records
- **THEN** the registry SHALL end up with every record in that window, not just the first 100

### Requirement: The sync date window is enforced by the client, not the server

The server SHALL NOT be trusted to honor `startFrom`/`startTo` — the client SHALL discard records
outside the requested `--days` window itself, after receiving each page, relying on the confirmed
descending sort order to stop fetching further pages once one page contains a record past the
window's threshold. A record whose date field is empty or unparsable SHALL be kept, not silently
dropped, because an unparsable date is not evidence the record is out of the window.

#### Scenario: Records past the window threshold are discarded by the client, not by server filtering

- **WHEN** the domain holds records outside the requested `--days` window
- **THEN** the client SHALL exclude them from the result regardless of what `startFrom`/`startTo`
  values were actually honored by the server

#### Scenario: A page containing a past-threshold record stops further page fetches

- **WHEN** a fetched page contains at least one record older than the window threshold
- **THEN** the client SHALL stop requesting further pages without additional network calls beyond
  that page

#### Scenario: A record without a parseable date is not dropped silently

- **WHEN** a record's date field is empty or fails to parse
- **THEN** the record SHALL be kept in the result, not discarded as if it were out of the window

### Requirement: The last sync moment is exposed by a reading command, not only recorded internally

At least one documented reading command's `--json` output SHALL carry the moment of the most
recently completed sync, without requiring a mutating `sync` call to obtain it — the moment is
already recorded internally (the `meta` table) but SHALL also be reachable through a read path, so
a consumer can distinguish "nothing pending" from "stale, unsynced data" without triggering
`sync`'s own side effect of aging `new` records past the retention window into `skipped`. When no
sync has ever completed, the exposed value SHALL be an explicit absent-state marker, not a
silently omitted field. Reading the exposed value, any number of times, SHALL NOT change any
recording's status.

#### Scenario: A reading command surfaces the last completed sync moment

- **WHEN** a reading command's `--json` output is requested after at least one completed sync
- **THEN** the response SHALL carry the moment of that sync, matching the value the sync run
  recorded

#### Scenario: An unsynced registry states absence explicitly

- **WHEN** a reading command's `--json` output is requested before any sync has ever completed
- **THEN** the response SHALL mark the sync moment as explicitly absent, not omit the field
  silently

#### Scenario: Reading the sync moment never mutates registry data

- **WHEN** any reading command that exposes the sync moment is invoked, any number of times
- **THEN** no recording's status SHALL change as a side effect of that call
