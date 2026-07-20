---
name: codex-session-rescue
description: Find, inspect, restore, archive, or recoverably trash local Codex tasks through the Session Rescue for Codex utility and native App Server protocol. Use when a Codex task was accidentally archived, disappeared from the sidebar, needs restoration, archived tasks must be listed, task-store integrity must be checked, or old tasks must be managed safely.
---

# Codex Session Rescue

Prefer the bundled `scripts/codex_session_rescue.py` utility. It uses native Codex protocol methods, creates SHA-256 verified transcript backups before mutations, confines paths to Codex stores, and verifies results.

## Workflow

1. Run `python scripts/codex_session_rescue.py --list` from this skill directory.
2. Match the task by title, working directory, prompt preview, and full thread ID.
3. Show the exact task before any archive, bulk restore, or trash action. Obtain confirmation for bulk archive or any trash action.
4. Restore one task with `python scripts/codex_session_rescue.py --restore "THREAD-ID"`.
5. Require `succeeded: 1`, a backup path, and zero failures before reporting success.
6. Tell the user to fully close Codex Desktop and start it again. This is required because the running sidebar can retain stale state after a verified restore.
7. Have the user open the restored task and confirm its history.

## Commands

```powershell
python scripts/codex_session_rescue.py --list
python scripts/codex_session_rescue.py --restore "THREAD-ID"
python scripts/codex_session_rescue.py --archive "THREAD-ID"
python scripts/codex_session_rescue.py --restore-all-archived
python scripts/codex_session_rescue.py --orphans
python scripts/codex_session_rescue.py --restore-trash "THREAD-ID"
python scripts/codex_session_rescue.py
```

## Safety rules

- Never edit Codex SQLite, WAL, SHM, `session_index.jsonl`, credentials, configuration, or global-state files.
- Never manually move active and archived transcripts when the native protocol is available.
- Never mutate a running task.
- Never hard-delete a transcript. Trash must retain the JSONL and recovery manifest, and the staged trash copy must pass SHA-256 verification before native deletion.
- Never skip the automatic backup or verification gate.
- Never claim sidebar visibility before Codex Desktop has restarted and the user has checked it.
- Treat custom paths as untrusted and require the utility's path-confinement check.

## Missing utility

If the script is unavailable, use Codex's native thread tools when exposed: list or read the exact task, call native unarchive, read it again, then require a Codex Desktop restart. Do not invent a filesystem fallback.
