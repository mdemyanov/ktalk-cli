# talk-api-auth-modes

## Purpose

Governs how `ktalk-cli` resolves the single credential that authorizes a request to
Контур.Толк, which transport carries it, how the client diagnoses an expired or rejected
credential, and how a caller checks the health of the active credential without touching the
local registry. Source: `content/30-requirements/single-auth-mode.md` FR-42…FR-44, which
supersede `content/30-requirements/personal-api-key.md` FR-1…FR-3, FR-5 (credential-selection
branches), and FR-11 (api-key-mode diagnosis) — the personal-API-key credential source and its
`X-Auth-Token` transport are removed, not merely deprioritized. FR-19 of
`content/30-requirements/rooms-calendar-scheduling.md` is merged here (SA decision,
ADR-021-spec §1) — `auth-status` diagnoses the same credential this capability resolves, not a
second contract.

## Requirements

### Requirement: Session token is the only credential source

The client SHALL resolve exactly one active credential from, in this order: a session token from
the environment (`KTALK_SESSION_TOKEN`), a session token previously written to the local token
file (`~/.config/ktalk-mcp/token` by default, `token_file.py`). A personal API key
(`KTALK_PERSONAL_API_KEY`) SHALL NOT be read as a credential source under any condition. If
neither the environment variable nor the file yields a value, the client SHALL raise a
configuration error naming `KTALK_SESSION_TOKEN` and the token-file command, before any network
call — the error message SHALL NOT mention `KTALK_PERSONAL_API_KEY`. Every request SHALL carry the
`sessionToken` query parameter; no request SHALL carry an `X-Auth-Token` header.

#### Scenario: Only the session token resolves, regardless of the legacy variable

- **WHEN** `KTALK_PERSONAL_API_KEY` is set to any value and `KTALK_SESSION_TOKEN` is also set
- **THEN** the client SHALL use the session token's value exclusively — no request SHALL carry
  `X-Auth-Token`, and `KTALK_PERSONAL_API_KEY`'s value SHALL NOT be used as a credential in any
  request

#### Scenario: Session env var takes priority over the token file

- **WHEN** `KTALK_SESSION_TOKEN` is set and a token file exists on disk with a different value
- **THEN** the client SHALL use the environment variable's value, not the file's

#### Scenario: Token file is the fallback of last resort

- **WHEN** `KTALK_SESSION_TOKEN` is not set and a token file exists
- **THEN** the client SHALL use the file's value as the session token, without requiring the
  caller to re-export an environment variable each session

#### Scenario: No session credential anywhere is a configuration error, not a network error

- **WHEN** neither `KTALK_SESSION_TOKEN` nor the token file yields a value, regardless of whether
  `KTALK_PERSONAL_API_KEY` is set
- **THEN** the client SHALL fail before any network call, with a message naming
  `KTALK_SESSION_TOKEN` and the token-file command as the two ways to resolve it, and SHALL NOT
  mention `KTALK_PERSONAL_API_KEY`

### Requirement: Presence of the removed personal-key variable is never silent

If `KTALK_PERSONAL_API_KEY` is present in the environment, the client SHALL print exactly one
warning to stderr per command invocation stating that the personal-key mode has been removed and
the variable is not used, then proceed on the session credential if one resolves. The warning
SHALL NOT block the command and SHALL NOT be repeated per outgoing HTTP request within the same
invocation (a multi-request command such as `sync` still prints exactly one line). The variable's
value SHALL NOT appear in the warning text, in full or as a partial match (tail or otherwise).

#### Scenario: The warning fires once per invocation, not once per request

- **WHEN** `KTALK_PERSONAL_API_KEY` is set and the invoked command issues more than one HTTP
  request (for example `sync` with pagination)
- **THEN** exactly one warning line SHALL appear on stderr for the whole invocation, and the
  command SHALL complete normally on the session credential

#### Scenario: No session credential and the legacy variable set still yields the configuration error, plus the warning

- **WHEN** `KTALK_PERSONAL_API_KEY` is set and no session credential resolves
- **THEN** the client SHALL still print the one-time warning, and SHALL still fail with the
  configuration error of the previous requirement — the warning does not substitute for having a
  working credential

#### Scenario: Absence of the variable produces no warning

- **WHEN** `KTALK_PERSONAL_API_KEY` is not set
- **THEN** no warning about it SHALL be printed

#### Scenario: The warning never carries the variable's value

- **WHEN** `KTALK_PERSONAL_API_KEY` is set to a value containing a secret
- **THEN** the printed warning SHALL NOT contain that value, in full or as a partial (tail) match

### Requirement: 401 and 403 are distinct diagnoses

A `401` response SHALL be reported as an expired-or-invalid session token, naming the session
token as the value to refresh. A `403` response SHALL be reported as a permissions gap, not a
credential problem, and SHALL NOT suggest refreshing the token — it SHALL state explicitly that
the token itself is not the problem. An unparsable or empty error body (observed for most `403`
bodies) SHALL still produce a readable message, never a raw traceback.

#### Scenario: 401 names the session token as the value to refresh

- **WHEN** the API returns `401`
- **THEN** the message SHALL instruct the caller to refresh the session token (environment
  variable or token file), not any other variable

#### Scenario: 403 never suggests refreshing a valid token

- **WHEN** the API returns `403`
- **THEN** the message SHALL state the session lacks permission for the operation and SHALL
  explicitly say the token itself is not the problem

#### Scenario: Unparsable error body still yields a readable message

- **WHEN** the response body is empty or not valid JSON (the common case for `403`)
- **THEN** the caller SHALL receive a readable message, not an unhandled parse error or a raw
  stack trace

### Requirement: Endpoint profile is keyed by operation; a missing profile fails before the network call

Every operation's path SHALL be looked up from a single table (`OPERATION_PROFILES`) keyed by
operation name, not branched inline per method. An operation with no profile entry for the
session credential SHALL be rejected before any network request, with a message naming the
operation and stating it is unavailable — never a bare `401`/`403` from a blind attempt. This
covers operations that, before the personal-key mode was removed, had no working path under the
session token at all (for example the archive listing) — removing the key does not give them a
new path; it removes the only mode any client of this capability ever had for them.

#### Scenario: An operation with no working path is rejected before the network, not silently broken

- **WHEN** an operation's profile table has no entry that resolves under the session credential
  (for example the archive listing, which never had a session-token path)
- **THEN** the client SHALL reject the call before issuing any HTTP request, naming the operation
  and stating it is not available

#### Scenario: List and detail operations use the internal, undocumented paths

- **WHEN** list-of-recordings or detail-of-recording operations are invoked
- **THEN** they SHALL use the internal, undocumented paths (`/api/recordings`,
  `/api/recordings/{key}`) — the documented `Domain` paths, reachable only under the removed
  personal-key transport, are not a fallback

### Requirement: Credential resolution and diagnosis do not require the local registry

Checking the health of the active credential (`ktalk auth-status`) SHALL perform the diagnosis and
print its result even when the registry database file is unreachable (missing path, unreadable
directory, a `--db` pointing nowhere). A failure that originates in the diagnosis itself (network,
`401`/`403`) SHALL remain reported as an authorization diagnosis, never re-labeled as a database
error. No other CLI command's registry requirement SHALL change as a result.

#### Scenario: auth-status succeeds with an unreachable registry path

- **WHEN** `ktalk auth-status` runs with a `--db` path that does not exist
- **THEN** the command SHALL still perform the authorization diagnosis and print its result,
  not fail with a database-open error

#### Scenario: A diagnosis failure is never mislabeled as a database failure

- **WHEN** the diagnosis itself fails (network error, `401`, `403`)
- **THEN** the reported error SHALL describe the authorization failure, not the registry

#### Scenario: Every other registry-dependent command is unaffected

- **WHEN** any command other than `auth-status` (`sync`, `list`, `dashboard`, `show`, `mark-*`,
  `export`, `migrate`, `set-vault-id`) is run
- **THEN** it SHALL still require a reachable registry file exactly as before this capability

### Requirement: Auth-status diagnosis distinguishes an accepted session token from a rejected one

The diagnosis SHALL perform a live, minimal probe request and report whether the contour accepted
or rejected the credential — it SHALL NOT fabricate an outcome and SHALL NOT skip the network
call. `alive` in the `--json` response SHALL reflect the probe's outcome, not merely the presence
of a variable or file. When the probe is rejected as an invalid or expired credential, `alive`
SHALL NOT be `true` and `note` SHALL NOT claim the credential is valid. The rejection SHALL be
observable through both channels a caller may read it by: the `alive` field in the response body,
and the process's exit code — one channel carrying the signal while the other does not is not a
compliant implementation of this requirement.

#### Scenario: Probe accepted

- **WHEN** the probe request succeeds
- **THEN** `alive` SHALL be `true` and the command's exit code SHALL be `0`

#### Scenario: Probe rejected as invalid or expired (reproducible on a fixture, no live contour required)

- **WHEN** the probe request returns `401`
- **THEN** `alive` SHALL NOT be `true`, `note` SHALL NOT state the credential is valid, and the
  command's exit code SHALL NOT be `0`

#### Scenario: Unparsable probe response still yields an honest, non-blocking result

- **WHEN** the probe response body is empty or not valid JSON
- **THEN** the diagnosis SHALL report a readable result that does not claim validity, not a raw
  parse error or stack trace

### Requirement: The session token and the removed personal-key variable never appear in output

`KTALK_SESSION_TOKEN`'s value SHALL NOT appear, in full, in an exception message, a log line, or
CLI stdout/stderr (including `--json` output), across a representative set of failure paths — a
client-raised auth error, a generic network exception, and both text and JSON CLI error output.
`KTALK_PERSONAL_API_KEY`'s value SHALL NOT appear in the one-time removal warning either, under
the same masking barrier.

#### Scenario: Secret absent from client-raised and generic exceptions

- **WHEN** a request fails with a `401`/`403` classified by this client, or with an unrelated
  network exception
- **THEN** the session token's value SHALL NOT appear anywhere in the exception's string
  representation

#### Scenario: Secret absent from CLI stderr in both output modes

- **WHEN** a CLI command fails while the session credential is set, in plain-text mode or with
  `--json`
- **THEN** the printed error SHALL NOT contain the credential value

#### Scenario: The removal warning never leaks the legacy variable's value

- **WHEN** `KTALK_PERSONAL_API_KEY` is set to a value containing a secret and the one-time removal
  warning is printed
- **THEN** the warning text SHALL NOT contain that value, in full or as a partial match
