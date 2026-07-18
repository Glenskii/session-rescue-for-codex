# Codex Archive and Restore Verification

Test date: 2026-07-18
Platform: Windows, Codex Desktop 0.144.5
Disposable task: `019f7392-c169-7dc1-9f0f-eb7683ee277d`

## Experiment

1. Created a disposable, completed Codex task.
2. Recorded its active transcript path, byte length, SHA-256, and session-index entry count.
3. Called the native Codex archive operation.
4. Recorded the same evidence in the archived store.
5. Called the native Codex unarchive operation.
6. Recorded the restored evidence in the dated active store.
7. Repeated archive and restore through `codex_session_rescue.py`, requiring automatic backup and protocol readback.
8. Moved only the disposable task through recoverable trash, restored it from its manifest, verified SHA-256, and confirmed native protocol discovery.

## Results

| Phase | Active files | Archived files | Bytes | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| Before archive | 1 | 0 | 113,260 | `2757A9A8A570DCEF2BE9E9EC9FF2B69A5D49C2FF984E6B69A024F9196A2CA768` |
| After archive | 0 | 1 | 113,260 | `2757A9A8A570DCEF2BE9E9EC9FF2B69A5D49C2FF984E6B69A024F9196A2CA768` |
| After unarchive | 1 | 0 | 113,260 | `2757A9A8A570DCEF2BE9E9EC9FF2B69A5D49C2FF984E6B69A024F9196A2CA768` |

`session_index.jsonl` contained one entry for the task before the experiment and remained at one entry throughout. The index record did not change during archive or unarchive.

## Conclusions

- **User action required:** fully close and restart Codex Desktop after archive or restore. The running sidebar can remain stale even when protocol and disk verification pass.
- Codex does not use Claude Desktop's `isArchived` metadata flag model.
- The tested Codex build performs a byte-preserving file transition through native App Server methods.
- Restore success must be verified through the native protocol and on-disk location.
- The running sidebar may remain stale even after successful native restore. A full Codex restart can be necessary for the sidebar to refresh.
- Manual SQLite or session-index editing is unnecessary and outside this tool's design.
- Recoverable trash restoration reproduced the original SHA-256 and returned the disposable task to native active-task discovery.

## Limits

- This is a verified snapshot of Codex Desktop 0.144.5 behavior on Windows, not a promise that OpenAI will never change its internal storage.
- macOS and Linux path discovery is implemented, but the controlled GUI restart experiment was performed on Windows.
- Trash uses native `thread/delete` only after preserving a full recoverable copy and manifest. Users should retain rescue folders until the task is confirmed.
