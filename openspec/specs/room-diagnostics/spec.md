# room-diagnostics

## Purpose

Governs reading a room's configuration by name: the field set returned, and the fact (established
after `rooms-calendar-scheduling.md` FR-17 was written) that this read has a write side effect.
Source: `content/30-requirements/rooms-calendar-scheduling.md` FR-17,
[ADR-006](../../../content/00-project/adr/ADR-006-get-room-side-effect.md).

## Requirements

### Requirement: Room read returns the documented field set

Reading a room by name, in session mode, SHALL return an object carrying at least the 18 fields
confirmed by live probing: `roomName`, `sessionHalls`, `stageConferenceId`, `moderators`,
`anonymousModerators`, `allowAnonymous`, `anonymousAccessExpirationDate`,
`anonymousAccessModifiedDate`, `audioPolicy`, `videoPolicy`, `screenSharePolicy`, `isModerator`,
`conferenceId`, `sipSettings`, `onlineUsers`, `simultaneousTranslation`, `chatChannelSettings`,
`maskingSettings`.

#### Scenario: Reading an existing room returns all 18 documented fields

- **WHEN** a room is read by name in session mode
- **THEN** the result SHALL carry all 18 documented fields, present even when their value is
  `null`, not omitted

### Requirement: The server does not signal "room not found" — reading an unseen name has a write side effect

`content/30-requirements/rooms-calendar-scheduling.md` FR-17's original acceptance criterion — that
a caller reading a nonexistent room name gets an explicit "not found" message — is **disproved by
measurement**, not implemented: the server returns `200` for any room name, including a
guaranteed-fresh random one, and never returns `404`. This capability's contract follows the
measured fact (ADR-006), not the original hypothesis: this operation SHALL be treated as a
read-with-a-write-side-effect, not a pure read. A room name not previously seen by the circuit
SHALL be persisted as a side effect of the first read. This operation SHALL NOT be used to probe
whether a name is free — the act of checking creates occupancy.

#### Scenario: An unseen room name is created, not reported as absent

- **WHEN** a room name that has never been read before is requested
- **THEN** the server SHALL respond `200` with a room object (not `404`), and that name SHALL
  subsequently exist as a persisted room — the caller SHALL NOT receive a "room not found" message,
  because the server has none to give
