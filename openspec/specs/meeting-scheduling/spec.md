# meeting-scheduling

## Purpose

Governs creating a single meeting: the preview/confirm split that keeps creation from being a
one-shot side effect of an ordinary tool call, the fields that must never carry a silent default,
the fields that must never appear in the request body at all, and the one locally-verifiable form
of the `timezone` field. Source: `content/30-requirements/rooms-calendar-scheduling.md` FR-13,
FR-40, NFR-9. Cancelling or editing an existing meeting is a separate requirement
(`ktalk-plugin-meetings.md` FR-34, a file migrating to the plugin repository) and is out of scope
of this capability even though its implementation lives in the same package module — see the Dev
report for this pairing task. The completeness of the missing-fields rejection (as opposed to
whether a given field takes a silent default) is sourced from
`content/30-requirements/cli-diagnostics-completeness.md` FR-47.

## Requirements

### Requirement: Preview performs no write network call; confirmation requires a separate step referencing it

Previewing meeting parameters SHALL perform zero write requests (`POST`/`PUT`/`PATCH`/`DELETE`) to
the Толк API — this is a structural property (the preview path is never given a network client
capable of issuing them), not a behavioral promise that could be bypassed. The body a preview
describes SHALL be identical to the body actually sent when the same parameters are later
confirmed. A single call carrying every meeting parameter, however it is decorated (including any
"I confirm" flag among its ordinary parameters), SHALL NOT itself create a meeting — confirmation
SHALL require a separate call referencing a specific prior preview.

#### Scenario: Preview issues no write request

- **WHEN** meeting parameters are submitted in preview mode
- **THEN** zero write requests SHALL be issued, and the caller SHALL receive a human-readable
  description of what would be created

#### Scenario: Preview and confirm agree on the same body

- **WHEN** the same parameters are first previewed and then confirmed
- **THEN** the body sent at confirmation time SHALL match the body the preview described, field for
  field

#### Scenario: A single call cannot both describe and confirm a meeting

- **WHEN** a call carries meeting parameters and any accompanying "confirm" flag as an ordinary
  parameter of that same call, without referencing a prior preview
- **THEN** no meeting SHALL be created — the call SHALL be rejected regardless of which other
  parameters it carries

### Requirement: Fields that determine who is invited or who can access never take a silent default

None of the following SHALL be filled in by the tool when the caller has not supplied it
explicitly: required attendees, room, start/end time, timezone, `allowAnonymous`, `pinCode`,
`enableAutoRecording`. An explicit empty value (an empty attendee list, an explicit "no PIN") is a
valid decision and is not the same as "not supplied" — only the latter is rejected. Rejection SHALL
happen before any network call and SHALL name the specific missing field.

#### Scenario: Each field from the no-silent-default list is individually enforced

- **WHEN** any one of required attendees, room, start, end, timezone, `allowAnonymous`, `pinCode`,
  or `enableAutoRecording` is omitted by the caller
- **THEN** the request SHALL be rejected before any network call, naming that specific field

#### Scenario: An explicit empty value is accepted as a decision, not treated as missing

- **WHEN** the caller explicitly passes an empty attendee list, or explicitly signals "no PIN"
- **THEN** the request SHALL proceed on that basis, not be rejected as if the field were omitted

### Requirement: Every field whose absence independently causes rejection is named together, not one at a time

A rejection triggered by one or more unset fields that would each independently cause
`MissingFieldError` (the fields covered by the no-silent-default rule above, plus the
conditionally required `pinCode` and, when `allowAnonymous` is true,
`anonymousAccessExpirationDate`) SHALL name every such field in that single rejection. The
exception class and the command's exit code SHALL remain unchanged from the single-field case.
This requirement governs the completeness of the field list only — it does not change when the
rejection happens (still before any network call) or what class of error `timezone`'s own format
check raises.

#### Scenario: Two or more unset required fields are named in one rejection

- **WHEN** a preview call omits two or more fields that would each independently cause
  `MissingFieldError`
- **THEN** the rejection SHALL name every one of them, not only the first encountered

#### Scenario: Exactly one unset field still produces today's single-field message

- **WHEN** a preview call omits exactly one such field
- **THEN** the rejection SHALL name that field, unchanged from the pre-existing behavior

#### Scenario: A format error on a present `timezone` is not folded into the missing-fields list

- **WHEN** every required field is present but `timezone` fails its format check
- **THEN** the rejection SHALL remain `TimezoneFormatError`, not be merged into or replaced by the
  missing-fields enumeration

#### Scenario: Aggregating the field list spends no network call and does not change the exit code

- **WHEN** the aggregated rejection is raised
- **THEN** it SHALL still occur before any network call, and the command's exit code SHALL be the
  same value it returned for a single missing field

### Requirement: Recurrence and unconfirmed fields never enter the request body

`isRecurring` and `recurrence` SHALL NOT be present in the created request body in any form — not
as an explicit value, not as an empty or `false` placeholder — because no verified template for
recurrence exists. Fields outside the confirmed 14-field set observed in live traffic
(`optionalUserKeys`, `requiredExternalAttendeesEmails`, `optionExternalAttendeesEmails`,
`simultaneousTranslation`, `customMeetingUrl`, `isAllDayEvent`, `controlledViaExternalSystem`)
SHALL likewise never be present.

#### Scenario: Recurrence fields are structurally absent from every created body

- **WHEN** any request body for meeting creation is inspected
- **THEN** it SHALL NOT contain `isRecurring` or `recurrence` in any form

#### Scenario: Fields outside the confirmed set are structurally absent

- **WHEN** any request body for meeting creation is inspected
- **THEN** it SHALL contain none of the fields outside the confirmed 14-field composition

### Requirement: Exactly one write attempt per confirmed creation, no automatic retry

A confirmed creation SHALL issue exactly one write request. On a network error or timeout during
that attempt, the tool SHALL NOT retry automatically — a second attempt risks creating a duplicate
meeting, and the decision to retry SHALL remain with the operator.

#### Scenario: A network failure during creation does not trigger a retry

- **WHEN** the single write request fails with a network error or timeout
- **THEN** the tool SHALL make exactly one write attempt, not two, and SHALL surface the failure
  to the caller rather than retrying silently

### Requirement: `timezone` accepts only the confirmed `GMT±N` form, rejected locally

The only form of `timezone` confirmed to work against the live server is a fixed offset written as
`GMT±N` (example: `GMT+3`). Seven other plausible forms (IANA name, Windows ID, ISO offset,
abbreviation, bare minutes, RTZ notation, a human-readable localized name) are all rejected by the
server with `CalendarTimeZoneParse`. The tool SHALL replicate this locally, before any network
call: a value not matching `GMT±N` SHALL be rejected with a message naming the required format and
its one confirmed example, not the server's raw error text. Rejecting on format SHALL have the
same effect as rejecting on a missing required field — no write-sanction budget consumed, no
confirmation id issued.

#### Scenario: The one confirmed form passes through unchanged

- **WHEN** `timezone` is given as `GMT+3`
- **THEN** it SHALL be accepted and sent to the server unchanged

#### Scenario: Any of the seven measured-as-rejected forms is refused before the network call

- **WHEN** `timezone` is given as `Europe/Moscow`, `Russian Standard Time`, `+03:00`, `MSK`,
  `180`, `RTZ 2 (MSK)`, or `(UTC+03:00) Москва, Санкт-Петербург`
- **THEN** the tool SHALL reject the call before issuing any network request, in preview or
  confirm

#### Scenario: A format rejection spends no sanction budget and issues no confirmation id

- **WHEN** `timezone` is rejected for its format
- **THEN** no confirmation id SHALL be issued and the write-sanction budget SHALL be unchanged
  by the attempt — identical in effect to rejecting a missing required field

#### Scenario: The rejection message and the CLI help name the required format

- **WHEN** a `timezone` rejection message is shown, or `--help`/the compositor's docstring is read
- **THEN** both SHALL name the format explicitly (`GMT±N`, example `GMT+3`), and the rejection
  message SHALL NOT repeat the server's raw `CalendarTimeZoneParse` text
