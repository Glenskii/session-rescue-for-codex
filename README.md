# Session Rescue for Codex

Find, verify, restore, archive, and recoverably trash local Codex tasks through Codex's native App Server protocol.

Created and maintained by [Glen E. Grant](https://profile.glenegrant.com) ([@Glenskii](https://github.com/Glenskii)).

> [!IMPORTANT]
> After restoring or archiving a task, fully close **Codex Desktop** and start it again. The transcript can be restored and protocol-verified while the running sidebar still shows stale state. Closing only the current task tab is not sufficient.

## The problem

A Codex task can disappear from the sidebar immediately after it is archived. The transcript may remain intact, but the running app's sidebar index can stay stale after a correct restore. Session Rescue exposes both active and archived task stores, creates evidence-preserving backups, invokes Codex's native task methods, and verifies the resulting state.

## Recovery workflow

1. List the task stores:

   ```powershell
   python codex_session_rescue.py --list
   ```

2. Find the exact task by title, working directory, prompt preview, and task ID.
3. Restore it with the browser interface or CLI:

   ```powershell
   python codex_session_rescue.py --restore "THREAD-ID"
   ```

4. Confirm the command reports `succeeded: 1` and a timestamped backup path.
5. Fully close Codex Desktop and start it again so the sidebar rebuilds from the restored state.
6. Open the task and confirm its history before continuing work.

## What it does

- Discovers active and archived tasks through native `thread/list` requests.
- Searches title, prompt, project directory, and task ID.
- Filters by Active, Archived, and Codex source.
- Groups tasks by working directory.
- Restores one task or all archived tasks.
- Archives one task or a selected group.
- Refuses to mutate tasks whose protocol status is running.
- Stages recoverable trash copies before invoking native deletion.
- Restores a trashed transcript by ID with SHA-256 verification.
- Compares protocol, disk transcript, and session-index records for orphans.
- Provides a local browser GUI and headless CLI.
- Includes an in-app recovery guide and build date.
- Includes a conversational Codex skill under `skills/codex-session-rescue/`.

## Safety model

- **Native protocol first.** Archive and restore call Codex's `thread/archive` and `thread/unarchive` methods. The tool does not imitate the operation by moving files itself.
- **Backup before mutation.** The full JSONL transcript is copied to `.codex/session-rescue-backups/<thread-id>/<timestamp>/` before every archive, restore, or trash action.
- **Recoverable trash.** Trash retains the transcript and a recovery manifest under `.codex/session-rescue-trash/` before native deletion.
- **Atomic tool-owned writes.** Manifests and trash recovery writes use a temporary file plus `os.replace`.
- **Path confinement.** Transcript paths must resolve under the discovered Codex `sessions` or `archived_sessions` store.
- **Hash verification.** Backups and trash restores record and verify SHA-256.
- **No network, telemetry, or third-party dependencies.** Python standard library only. The GUI binds to `127.0.0.1` and uses a per-run request token.
- **No database editing.** The tool never edits Codex SQLite, WAL, SHM, index, configuration, credential, or global-state files.

## Verified Codex behavior

The restore design is based on a controlled Codex Desktop experiment, not the Claude session schema:

- Native archive moved a completed disposable task from `sessions/YYYY/MM/DD/` to `archived_sessions/`.
- Native unarchive moved it back to the original dated store.
- The JSONL length and SHA-256 remained identical through both transitions.
- `session_index.jsonl` did not change during archive or unarchive.
- A restored task was protocol-readable before the running sidebar showed it; restarting Codex refreshed that presentation layer.

See [VERIFICATION.md](VERIFICATION.md) for exact evidence and limitations.

## Requirements

- Python 3.8 or newer
- A current Codex installation whose CLI supports `codex app-server`
- Windows, macOS, or Linux

If multiple Codex CLIs are installed, the tool selects the newest App Server-capable binary. Override discovery when necessary:

```powershell
$env:CODEX_BIN = "C:\path\to\current\codex.exe"
```

## Usage

Browser GUI:

```powershell
python codex_session_rescue.py
```

The interface opens at `http://127.0.0.1:52851` and shuts down after the browser tab closes.

CLI:

```powershell
python codex_session_rescue.py --list
python codex_session_rescue.py --restore "THREAD-ID"
python codex_session_rescue.py --archive "THREAD-ID"
python codex_session_rescue.py --restore-all-archived
python codex_session_rescue.py --orphans
python codex_session_rescue.py --restore-trash "THREAD-ID"
python codex_session_rescue.py --path "D:\custom\.codex" --list
```

Archive, restore, and trash are mutations. Read the exact target list and keep the generated backup folders.

## How Codex stores tasks

Default root: `$CODEX_HOME`, or `~/.codex` when that variable is unset.

| State | Default location |
| --- | --- |
| Active | `.codex/sessions/YYYY/MM/DD/rollout-...-<thread-id>.jsonl` |
| Archived | `.codex/archived_sessions/rollout-...-<thread-id>.jsonl` |
| Rescue backups | `.codex/session-rescue-backups/<thread-id>/<timestamp>/` |
| Recovery trash | `.codex/session-rescue-trash/<thread-id>/<timestamp>/` |

Codex App Server remains authoritative for state transitions. Local JSONL discovery is used for integrity evidence and recovery copies, not as an invented archive flag.

## Conversational skill

Copy `skills/codex-session-rescue/` into your Codex skills directory, normally `~/.codex/skills/`. Then ask:

> Use `$codex-session-rescue` to find and safely restore the Codex task I accidentally archived.

The skill requires confirmation before bulk archive or trash operations and verifies each restored task.

## Contributors

1. **[Glen E. Grant](https://profile.glenegrant.com)** ([@Glenskii](https://github.com/Glenskii)) — creator and maintainer of Session Rescue for Codex and [Session Rescue for Claude](https://github.com/Glenskii/session-rescue-for-claude)
2. **[SugaCrypto](https://github.com/SugaCrypto)** — original author of [cowork-archive-manager](https://github.com/SugaCrypto/cowork-archive-manager), prior art credited by the Claude counterpart

Contributions are welcome through issues and pull requests.

## Trademark and attribution

The included Codex mark is an unmodified OpenAI asset used to identify the OpenAI service this utility directly supports. Codex, OpenAI, and their marks belong to OpenAI. Follow the current [OpenAI brand guidelines](https://openai.com/brand/).

Session Rescue for Codex is an independent community project created by Glen E. Grant. It is not affiliated with, sponsored by, or endorsed by OpenAI.

## License

MIT. See [LICENSE](LICENSE).
