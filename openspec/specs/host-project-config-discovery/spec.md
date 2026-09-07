# host-project-config-discovery

## Purpose

Governs how the package discovers a host project's layout (`.ktalk.toml`) on its own, without the
plugin substituting values into it, how it behaves when no such file exists, how it fails when the
file is malformed, and how the registry-path priority order is extended without disturbing the
three sources that already existed. Source: `content/30-requirements/ktalk-plugin.md` FR-20,
FR-21, FR-23, FR-24, FR-25.

## Requirements

### Requirement: Config discovery order — explicit override, then `CLAUDE_PROJECT_DIR`, then upward walk

Discovery SHALL try, in order: an explicit `project_dir` override, then `CLAUDE_PROJECT_DIR` from
the environment (searched at exactly that root, no upward walk), then — only for a bare CLI
invocation with neither of those — an upward walk from the current working directory to the first
`.ktalk.toml` found, stopping at the first directory containing `.git` (the project boundary) or
at the filesystem root. Finding no file at any of these SHALL yield "no host config", not an
error.

This capability also governs how its own discovery outcome is surfaced through the `ktalk doctor`
aggregated report (`content/30-requirements/cli-diagnostics-completeness.md` FR-48, NFR-23): the
config-discovery outcome (found-with-path / absent / malformed-with-cause) is the one item of that
report this capability owns. The report's other items — package version, session-token file,
credential liveness, workspace address — are owned by other capabilities (`talk-api-auth-modes` for
credential liveness) or by none of the package's eight capabilities today; `doctor` reads and
surfaces them without this capability redefining their truth.

#### Scenario: An explicit override or `CLAUDE_PROJECT_DIR` is searched at its own root only

- **WHEN** `project_dir` is passed explicitly, or `CLAUDE_PROJECT_DIR` is set
- **THEN** discovery SHALL look for `.ktalk.toml` exactly at that root and SHALL NOT walk upward
  past it

#### Scenario: A bare CLI invocation walks upward, bounded by the project's `.git`

- **WHEN** neither an explicit override nor `CLAUDE_PROJECT_DIR` is present
- **THEN** discovery SHALL walk from the current working directory upward until it finds
  `.ktalk.toml`, or a directory containing `.git`, or the filesystem root — whichever comes first

### Requirement: Absence of a host config file is a normal branch, not an error

A project with no `.ktalk.toml` at all SHALL NOT raise an error during discovery — it SHALL fall
through to the machine default (the `centralized-machine-storage` capability). Registry commands
and MCP tools that do not depend on vault-specific layout SHALL work unmodified in such a project.

#### Scenario: No config file present falls through cleanly

- **WHEN** discovery finds no `.ktalk.toml` anywhere on its search path
- **THEN** it SHALL return "no host config" rather than raising, and the caller SHALL proceed on
  the machine default

#### Scenario: Layout-independent commands and tools work without any host config

- **WHEN** `sync`/`list`/`show`/`mark-*`/`dashboard`/`export`, or an MCP tool reading a
  recording/transcript/summary, runs in a project with no `.ktalk.toml` and none of the
  vault-like directories
- **THEN** it SHALL complete on the machine-default path, without requiring any host-specific
  directory to exist

### Requirement: A malformed config file fails with the file name and the specific cause

A `.ktalk.toml` present but failing to parse as TOML, declaring an unknown top-level section, or
failing a field's type check (for example a non-string `directories`/`routing` value, a
non-boolean `integrations.qmd`) SHALL raise an error naming that exact file path and the specific
cause. This SHALL NOT be swallowed into a generic message, and SHALL NOT silently fall back to the
machine default as if the file were absent — a present-but-broken file is a distinct outcome from
no file at all.

#### Scenario: Invalid TOML syntax names the file

- **WHEN** the file exists but is not valid TOML
- **THEN** the error SHALL name the file path and describe the syntax problem, not a generic
  parsing failure

#### Scenario: An unknown top-level section is rejected by name

- **WHEN** the file declares a top-level key outside `registry`, `directories`, `routing`,
  `integrations`
- **THEN** the error SHALL name the file, the unrecognized section(s), and the accepted set

#### Scenario: A wrong-typed field fails with the field's own name

- **WHEN** a field that must be a string (a `directories`/`routing` value, `registry.db_path`) or
  boolean (`integrations.qmd`) has the wrong type
- **THEN** the error SHALL name the file and the specific field, not fall back to a default value
  for that field

### Requirement: Registry path priority extends the existing three-source order without reordering it

The pre-existing priority (`--db` flag > `KTALK_REGISTRY_DB` environment variable > default) SHALL
keep its relative order; a host-config-declared path SHALL be inserted between the environment
variable and the default, not ahead of either existing source.

#### Scenario: `--db` still wins over everything else

- **WHEN** `--db`, `KTALK_REGISTRY_DB`, and a host-config path are all set
- **THEN** `--db` SHALL be the path used

#### Scenario: The environment variable still wins over the host config

- **WHEN** `--db` is absent but `KTALK_REGISTRY_DB` and a host-config path are both set
- **THEN** `KTALK_REGISTRY_DB` SHALL be the path used

#### Scenario: The host config is used only when both flag and environment variable are absent

- **WHEN** neither `--db` nor `KTALK_REGISTRY_DB` is set, but the host config declares a path
- **THEN** that host-config path SHALL be used, not the machine default

### Requirement: `ktalk doctor` surfaces this capability's discovery outcome unchanged

The `doctor` aggregated report SHALL include the host config discovery outcome using the same
three-way vocabulary this capability already defines (found, with the path used; absent, as a
normal branch, not an error; malformed, naming the specific cause) — `doctor` SHALL NOT introduce a
second discovery mechanism or a different vocabulary for this item. The value SHALL agree with what
`ktalk config show` reports for the same project.

#### Scenario: An absent config is reported as a normal branch inside `doctor`, not a failure

- **WHEN** `ktalk doctor` runs in a project with no `.ktalk.toml` anywhere on the search path
- **THEN** the report's config-discovery item SHALL state absence plainly and SHALL NOT be counted
  as a failed precondition

#### Scenario: A malformed config names its cause inside `doctor`

- **WHEN** `ktalk doctor` runs against a `.ktalk.toml` that fails to parse, declares an unknown
  section, or fails a field's type check
- **THEN** the report's config-discovery item SHALL name the specific cause, not a generic failure

#### Scenario: A found config's path agrees with `config show`

- **WHEN** `ktalk doctor` and `ktalk config show` run against the same project with a valid
  `.ktalk.toml`
- **THEN** both SHALL name the same file path as the source of the resolved configuration

### Requirement: `ktalk doctor` aggregates independently owned facts into one report without a write call

`doctor` SHALL run as a single command that performs no write request to Контур.Толк and mutates no
registry state. Its exit code SHALL be non-zero if and only if at least one aggregated precondition
is a genuine failure — an item that is merely inapplicable (for example, no `.ktalk.toml` present)
SHALL NOT by itself make the exit code non-zero. Every aggregated item's value SHALL agree with what
its own dedicated command (`--version`, `token status`, `auth-status`, `config show`) reports for
the same environment; `doctor` SHALL NOT compute a different answer for a fact another surface
already owns.

#### Scenario: Every satisfied-or-inapplicable precondition yields exit code zero

- **WHEN** every aggregated precondition is either satisfied or genuinely inapplicable
- **THEN** `ktalk doctor` SHALL exit 0

#### Scenario: Any genuine failure yields a non-zero exit code, independent of `--json` parsing

- **WHEN** at least one aggregated precondition is a genuine failure (a malformed `.ktalk.toml`, an
  absent or unreadable token file, a credential the live check reports as rejected)
- **THEN** `ktalk doctor` SHALL exit with a non-zero code, and this SHALL hold even for a caller
  that does not parse the `--json` body at all

#### Scenario: Aggregated values agree with each item's own dedicated command

- **WHEN** `ktalk doctor --json` and each of `--version`, `token status`, `auth-status`, `config
  show` run against the same environment
- **THEN** the value each dedicated command reports SHALL match the corresponding item in
  `doctor`'s report

### Requirement: A `qmd`/participant-profile dependency is a declared fact the package exposes, not a step the package performs

The package's role in FR-24's degradation contract is to parse and expose a declared
`integrations.qmd` boolean from `.ktalk.toml` (present, absent, or type-invalid) as part of
`HostConfig`. This capability does **not** implement the participant-to-profile matching step
itself, or its explicit-unavailability marking on the resulting report — that step belongs to the
meeting-processing prompt layer (a different repository, ADR-012 boundary), which reads this
declared value to decide whether to attempt the match at all. The requirement text's framing ("a
processing step reaches profile matching, and marks it unavailable") describes behavior at that
outer layer, not inside `ktalk-cli`.

#### Scenario: An absent `integrations.qmd` key is exposed as "not declared", not defaulted to a guess

- **WHEN** `.ktalk.toml` has no `integrations.qmd` key, or no `[integrations]` section at all
- **THEN** `HostConfig.integrations` SHALL simply lack the key — the caller reading it SHALL be
  able to distinguish "not declared" from an explicit `true`/`false`, not receive a substituted
  default

#### Scenario: A non-boolean `integrations.qmd` fails discovery outright

- **WHEN** `integrations.qmd` is present but not a boolean (for example a string)
- **THEN** discovery SHALL raise the malformed-config error above, naming the field — it SHALL
  NOT be silently coerced or ignored

### Requirement: Authorization secrets are never sourced from or written into host configuration

`KTALK_SESSION_TOKEN` and `KTALK_PERSONAL_API_KEY` SHALL remain environment-level configuration of
the process they run in. Host-config discovery SHALL NOT read either from `.ktalk.toml`, and
nothing in this capability SHALL write either value into any file discovery reads.

#### Scenario: A host config cannot carry a credential

- **WHEN** `.ktalk.toml` is inspected for any field capable of carrying
  `KTALK_SESSION_TOKEN`/`KTALK_PERSONAL_API_KEY`
- **THEN** no such field SHALL exist in the schema `host_config.py` accepts — the schema's known
  sections (`registry`, `directories`, `routing`, `integrations`) carry no secret-shaped field
