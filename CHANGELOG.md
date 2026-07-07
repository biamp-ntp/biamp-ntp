# Changelog

## 0.2.0 — 2026-07-07

### Changed
- **Response-driven reply framing with a pacing floor.** `command()` now
  reads until a complete reply line arrives (`+OK`, `-ERR:...`, or a value)
  instead of sleeping a fixed settle window and draining, and spaces
  commands on one connection by `pace=` (default 50 ms). The pacing exists
  because real hardware chokes on full-rate pipelining: a live Nexia PM
  prepends an undocumented `-ERR:# 0x16` line to each reply and falls
  progressively behind, desynchronizing reply attribution. A `-ERR:#` line
  is treated as a timing complaint — the client prefers the line that
  follows it, and returns the complaint itself only if nothing else arrives
  (a real error is never swallowed). Stragglers left on the wire by a prior
  exchange are flushed before each send. A default `scan` of instances
  1–200 drops from ~80 s to ~18 s (measured live on a Nexia PM; RTT-bound
  with `pace=0` on firmware you've verified). `settle=` is retained but now
  only paces the one-off banner drain at connect.
- **Full telnet IAC handling.** `_strip_iac` now handles the whole grammar:
  `IAC IAC` escaped data bytes, `IAC SB … IAC SE` subnegotiation blocks,
  2-byte commands (NOP/GA), and sequences left incomplete at the buffer
  tail — previously any `0xFF` was assumed to start a 3-byte triple.

### Added
- `BiampNTP.recall_preset(n)` — system-wide preset recall
  (`RECALL 0 PRESET <n>`), plus `inc()` / `dec()` for relative adjustment.
- CLI subcommands: `recall`, `inc`, `dec`.
- `protocol.PRESET` constant.
- I/O test suite (`tests/test_client_io.py`) against an in-process fake
  telnet server: framing across split TCP segments, IAC interleaved with
  replies (including mid-triple splits), echo-on and echo-off parsing,
  the silent-drop reconnect/retry path, timeout bounds, command-rate
  regression guard, pace-floor enforcement, wire-format assertions for the
  new verbs, and a `-ERR:# 0x16` regression suite (busy line before a value,
  before a real error, standing alone, and repeated across many commands
  without attribution drift).
- README: explicit telnet-only scope note; recall/inc/dec examples.

### Internal
- Reply extraction factored into `BiampNTP._extract_reply` (pure, unit-tested);
  `_reply`/settle-based `_drain` framing removed from the command path.

## 0.1.0 — 2026-07-05

Initial release: dependency-free client + CLI (`devid`, `scan`, `get`,
`set`, `raw`), instance-ID discovery, IAC triple stripping, thread-safe
`command()` with reconnect-retry.
