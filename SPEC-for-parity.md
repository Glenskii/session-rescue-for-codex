# Session Rescue for Codex, Parity Specification

Source reference: [Session Rescue for Claude](https://github.com/Glenskii/session-rescue-for-claude)
Creator: [Glen E. Grant](https://profile.glenegrant.com)
Codex verification date: 2026-07-18

## Parity matrix

| Capability | Codex implementation |
| --- | --- |
| Cross-store discovery | Native App Server lists active and archived stores; disk evidence scans dated active, flat archived, index, backups, and trash |
| Restore single or bulk | Native `thread/unarchive`, automatic backup, protocol readback |
| Archive single or bulk | Native `thread/archive`, automatic backup, protocol readback |
| Recoverable trash | Full JSONL plus manifest retained before native `thread/delete`; `--restore-trash` verifies SHA-256 |
| Search and filter | Title, prompt, project directory, task ID, source, active/archived |
| Group by project | Working-directory ledger sections |
| Orphan detection | Disk transcripts compared with native protocol and `session_index.jsonl` records |
| Browser GUI | Local `127.0.0.1` standard-library server, per-run request token, no external assets |
| Headless CLI | List, restore, bulk restore, archive, integrity report, custom path, trash recovery |
| In-app help | Linear recovery workflow, safety model, restart requirement |
| Build freshness | Script modification timestamp and `MM-DD-YY` build date |
| Conversational wrapper | `skills/codex-session-rescue/` with native-first safety rules |

## Non-negotiable safety controls

1. Back up the full transcript before every mutation.
2. Use Codex's native protocol for archive, unarchive, and delete state transitions.
3. Refuse mutation when Codex reports a running task.
4. Validate every transcript path under the discovered Codex stores.
5. Write tool-owned manifests and restores atomically.
6. Preserve recoverable trash and verify SHA-256 before restoring it.
7. Never edit Codex databases, indexes, credentials, config, or global state.
8. Bind the GUI only to loopback and make no outbound network calls.
9. Require a full Codex Desktop restart after archive or restore.
10. Report verified outcomes, not optimistic file-operation success.

## Codex-specific mechanism

Codex does not use the Claude tool's `isArchived` flag schema. Controlled testing proved that native archive and unarchive move the byte-identical JSONL transcript between the dated active store and flat archived store. `session_index.jsonl` did not change during those transitions, so the running sidebar can remain stale until Codex Desktop restarts.

The native protocol is therefore authoritative. Direct file movement is used only by explicit recovery-trash restoration after integrity checks, followed by a native scan-and-read verification.
