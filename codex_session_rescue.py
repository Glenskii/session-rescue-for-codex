#!/usr/bin/env python3
"""Session Rescue for Codex: local, native-protocol task recovery.

Created and maintained by Glen E. Grant.
License: MIT. No network calls, telemetry, or third-party dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


VERSION = "1.0.0"
PORT = 52851
APP_NAME = "Session Rescue for Codex"
BACKUP_DIR = "session-rescue-backups"
TRASH_DIR = "session-rescue-trash"
LOCK_NAME = ".codex_session_rescue.lock"
CLIENT_NAME = "session-rescue-for-codex"
WRITE_ACTIONS = {"archive", "unarchive", "trash"}


class RescueError(RuntimeError):
    """Expected operational failure safe to show to a user."""


def build_timestamp() -> str:
    try:
        value = datetime.fromtimestamp(Path(__file__).stat().st_mtime).astimezone()
        return value.strftime("%Y-%m-%d %I:%M %p %Z")
    except OSError:
        return "unknown"


def build_date() -> str:
    try:
        return datetime.fromtimestamp(Path(__file__).stat().st_mtime).strftime("%m-%d-%y")
    except OSError:
        return "00-00-00"


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def candidate_codex_homes(custom: str | None = None) -> list[Path]:
    values: list[Path] = []
    if custom:
        values.append(Path(custom).expanduser())
    else:
        values.append(default_codex_home())
        if platform.system() == "Windows":
            local = Path(os.environ.get("LOCALAPPDATA", ""))
            packages = local / "Packages"
            if packages.is_dir():
                values.extend(packages.glob("OpenAI.Codex_*/*/LocalCache/.codex"))
    unique: list[Path] = []
    for value in values:
        resolved = value.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def discover_codex_home(custom: str | None = None) -> Path:
    for root in candidate_codex_homes(custom):
        if root.is_dir() and ((root / "sessions").exists() or (root / "archived_sessions").exists()):
            return root
    searched = ", ".join(str(path) for path in candidate_codex_homes(custom))
    raise RescueError(f"No Codex session store found. Searched: {searched}")


def parse_version(value: str) -> tuple[int, ...]:
    digits = []
    for part in value.strip().split("."):
        number = "".join(char for char in part if char.isdigit())
        if number:
            digits.append(int(number))
    return tuple(digits)


def codex_binary_candidates() -> Iterable[Path]:
    configured = os.environ.get("CODEX_BIN")
    if configured:
        yield Path(configured).expanduser()
    found = shutil.which("codex")
    if found:
        yield Path(found)
    if platform.system() == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        yield from sorted((local / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"), reverse=True)
        program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        yield from sorted((program_files / "WindowsApps").glob("OpenAI.Codex_*/*/resources/codex.exe"), reverse=True)


_codex_binary: Path | None = None


def find_codex_binary() -> Path:
    global _codex_binary
    if _codex_binary:
        return _codex_binary
    checked: set[Path] = set()
    best: tuple[tuple[int, ...], Path] | None = None
    for candidate in codex_binary_candidates():
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in checked or not resolved.is_file():
            continue
        checked.add(resolved)
        try:
            version_run = subprocess.run(
                [str(resolved), "--version"], capture_output=True, text=True, timeout=5, check=False
            )
            help_run = subprocess.run(
                [str(resolved), "app-server", "--help"], capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if version_run.returncode != 0 or help_run.returncode != 0:
            continue
        version_text = version_run.stdout.strip().split()[-1]
        candidate_info = (parse_version(version_text), resolved)
        if best is None or candidate_info[0] > best[0]:
            best = candidate_info
    if best is None:
        raise RescueError(
            "A Codex binary with App Server support was not found. Set CODEX_BIN to the current Codex executable."
        )
    _codex_binary = best[1]
    return _codex_binary


class AppServerClient:
    """Small newline-JSON client for Codex's local App Server protocol."""

    def __init__(self, binary: Path):
        self.binary = binary
        self.process: subprocess.Popen[str] | None = None
        self.next_id = 1

    def __enter__(self) -> "AppServerClient":
        self.process = subprocess.Popen(
            [str(self.binary), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        response = self.request(
            "initialize",
            {"clientInfo": {"name": CLIENT_NAME, "title": APP_NAME, "version": VERSION}},
        )
        if not response.get("codexHome"):
            raise RescueError("Codex App Server initialized without a session-store location.")
        self.notify("initialized", {})
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        if not self.process:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.process.kill()
            except OSError:
                pass

    def _send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RescueError("Codex App Server is not running.")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.process or not self.process.stdout:
            raise RescueError("Codex App Server is not running.")
        request_id = self.next_id
        self.next_id += 1
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                stderr = ""
                if self.process.stderr:
                    stderr = self.process.stderr.read().strip()
                raise RescueError(f"Codex App Server closed unexpectedly. {stderr}".strip())
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                detail = error.get("message") if isinstance(error, dict) else str(error)
                raise RescueError(f"Codex rejected {method}: {detail}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}
        raise RescueError(f"Timed out waiting for Codex method {method}.")


def list_protocol_threads(client: AppServerClient, archived: bool) -> list[dict[str, Any]]:
    cursor: str | None = None
    rows: list[dict[str, Any]] = []
    while True:
        params: dict[str, Any] = {
            "archived": archived,
            "limit": 100,
            "sortKey": "updated_at",
            "sortDirection": "desc",
            "useStateDbOnly": False,
            "sourceKinds": [],
        }
        if cursor:
            params["cursor"] = cursor
        result = client.request("thread/list", params)
        page = result.get("data", [])
        if isinstance(page, list):
            for item in page:
                if isinstance(item, dict):
                    item["archived"] = archived
                    rows.append(item)
        cursor = result.get("nextCursor")
        if not cursor:
            return rows


def safe_resolve_thread_path(codex_home: Path, thread: dict[str, Any]) -> Path:
    raw = thread.get("path")
    if not isinstance(raw, str) or not raw:
        raise RescueError(f"Task {thread.get('id', '[unknown]')} has no transcript path.")
    path = Path(raw).resolve()
    allowed = [(codex_home / "sessions").resolve(), (codex_home / "archived_sessions").resolve()]
    if not any(_is_relative_to(path, root) for root in allowed):
        raise RescueError(f"Refusing path outside the Codex stores: {path}")
    if not path.is_file() or path.suffix.lower() != ".jsonl":
        raise RescueError(f"Transcript is missing or invalid: {path}")
    return path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def backup_before_mutation(codex_home: Path, thread: dict[str, Any], action: str) -> dict[str, Any]:
    if action not in WRITE_ACTIONS:
        raise RescueError(f"Unsupported mutation: {action}")
    source = safe_resolve_thread_path(codex_home, thread)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%z")
    target_dir = codex_home / BACKUP_DIR / str(thread["id"]) / stamp
    target = target_dir / source.name
    target_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source, target)
    manifest = {
        "schemaVersion": 1,
        "threadId": thread["id"],
        "action": action,
        "createdAt": datetime.now().astimezone().isoformat(),
        "sourcePath": str(source),
        "backupPath": str(target),
        "sizeBytes": target.stat().st_size,
        "sha256": file_sha256(target),
    }
    atomic_write(target_dir / "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return manifest


def normalize_thread(thread: dict[str, Any]) -> dict[str, Any]:
    status = thread.get("status") if isinstance(thread.get("status"), dict) else {}
    return {
        "id": thread.get("id") or thread.get("sessionId"),
        "title": thread.get("name") or "Untitled task",
        "preview": thread.get("preview") or "",
        "cwd": thread.get("cwd") or "No project directory",
        "source": thread.get("source") or "unknown",
        "modelProvider": thread.get("modelProvider") or "unknown",
        "createdAt": thread.get("createdAt"),
        "updatedAt": thread.get("updatedAt"),
        "recencyAt": thread.get("recencyAt"),
        "archived": bool(thread.get("archived")),
        "path": thread.get("path"),
        "status": status.get("type", "unknown"),
        "cliVersion": thread.get("cliVersion"),
    }


def load_all_sessions(custom_home: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    codex_home = discover_codex_home(custom_home)
    binary = find_codex_binary()
    with AppServerClient(binary) as client:
        active = list_protocol_threads(client, False)
        archived = list_protocol_threads(client, True)
    rows = [normalize_thread(thread) for thread in active + archived]
    rows.sort(key=lambda row: row.get("recencyAt") or row.get("updatedAt") or 0, reverse=True)
    return rows, {
        "codexHome": str(codex_home),
        "codexBinary": str(binary),
        "active": len(active),
        "archived": len(archived),
        "build": build_timestamp(),
        "buildDate": build_date(),
        "version": VERSION,
    }


def fetch_thread(client: AppServerClient, thread_id: str, archived: bool) -> dict[str, Any]:
    for item in list_protocol_threads(client, archived):
        if item.get("id") == thread_id:
            return item
    raise RescueError(f"Task {thread_id} was not found in the expected store.")


def mutate_threads(thread_ids: list[str], action: str, custom_home: str | None = None) -> dict[str, Any]:
    if action not in {"archive", "unarchive", "trash"}:
        raise RescueError(f"Unsupported action: {action}")
    if not thread_ids:
        raise RescueError("No tasks were selected.")
    if len(thread_ids) > 500:
        raise RescueError("Bulk action limit is 500 tasks.")
    codex_home = discover_codex_home(custom_home)
    binary = find_codex_binary()
    outcomes = []
    with AppServerClient(binary) as client:
        for thread_id in thread_ids:
            try:
                source_archived = action == "unarchive"
                thread = fetch_thread(client, thread_id, source_archived)
                status_type = (thread.get("status") or {}).get("type")
                if status_type in {"active", "inProgress", "running"}:
                    raise RescueError("Refusing to mutate a running task.")
                manifest = backup_before_mutation(codex_home, thread, action)
                if action == "archive":
                    client.request("thread/archive", {"threadId": thread_id})
                    fetch_thread(client, thread_id, True)
                elif action == "unarchive":
                    client.request("thread/unarchive", {"threadId": thread_id})
                    fetch_thread(client, thread_id, False)
                else:
                    trash_root = codex_home / TRASH_DIR / thread_id / Path(manifest["backupPath"]).parent.name
                    trash_root.mkdir(parents=True, exist_ok=False)
                    backup_path = Path(manifest["backupPath"])
                    trash_copy = trash_root / backup_path.name
                    shutil.copy2(backup_path, trash_copy)
                    trash_manifest = dict(manifest)
                    trash_manifest["trashPath"] = str(trash_copy)
                    atomic_write(trash_root / "manifest.json", json.dumps(trash_manifest, indent=2).encode("utf-8"))
                    client.request("thread/delete", {"threadId": thread_id})
                outcomes.append({"id": thread_id, "ok": True, "backup": manifest["backupPath"]})
            except RescueError as error:
                outcomes.append({"id": thread_id, "ok": False, "error": str(error)})
    return {
        "action": action,
        "requested": len(thread_ids),
        "succeeded": sum(1 for row in outcomes if row["ok"]),
        "failed": sum(1 for row in outcomes if not row["ok"]),
        "outcomes": outcomes,
        "restartRecommended": action in {"archive", "unarchive"},
    }


def find_orphans(custom_home: str | None = None) -> dict[str, Any]:
    codex_home = discover_codex_home(custom_home)
    disk: dict[str, str] = {}
    for root in (codex_home / "sessions", codex_home / "archived_sessions"):
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            identifier = path.stem.rsplit("-", 1)[-1]
            if len(identifier) == 36:
                disk[identifier] = str(path)
            else:
                parts = path.stem.split("-")
                if len(parts) >= 6:
                    disk["-".join(parts[-5:])] = str(path)
    sessions, _ = load_all_sessions(custom_home)
    protocol_ids = {str(row["id"]) for row in sessions}
    index_ids: set[str] = set()
    index_path = codex_home / "session_index.jsonl"
    if index_path.is_file():
        with index_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                    if isinstance(value.get("id"), str):
                        index_ids.add(value["id"])
                except json.JSONDecodeError:
                    continue
    return {
        "transcriptWithoutProtocolRecord": sorted(disk[item] for item in disk.keys() - protocol_ids),
        "protocolRecordWithoutTranscript": sorted(protocol_ids - disk.keys()),
        "indexRecordWithoutTranscript": sorted(index_ids - disk.keys()),
        "diskTranscriptCount": len(disk),
        "protocolThreadCount": len(protocol_ids),
        "indexThreadCount": len(index_ids),
    }


def restore_from_trash(thread_id: str, custom_home: str | None = None) -> dict[str, Any]:
    codex_home = discover_codex_home(custom_home)
    trash_base = (codex_home / TRASH_DIR / thread_id).resolve()
    if not trash_base.is_dir() or not _is_relative_to(trash_base, (codex_home / TRASH_DIR).resolve()):
        raise RescueError(f"No recovery-trash record exists for task {thread_id}.")
    manifests = sorted(trash_base.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not manifests:
        raise RescueError(f"Task {thread_id} has no recovery manifest.")
    try:
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RescueError(f"Recovery manifest is unreadable: {error}") from error
    source = Path(str(manifest.get("sourcePath", ""))).resolve()
    trash_copy = Path(str(manifest.get("trashPath", ""))).resolve()
    allowed = [(codex_home / "sessions").resolve(), (codex_home / "archived_sessions").resolve()]
    if not any(_is_relative_to(source, root) for root in allowed):
        raise RescueError("Recovery destination falls outside the Codex stores.")
    if not _is_relative_to(trash_copy, trash_base) or not trash_copy.is_file():
        raise RescueError("Recovery transcript is missing or outside its trash record.")
    if source.exists():
        raise RescueError(f"Recovery destination already exists: {source}")
    expected_hash = str(manifest.get("sha256", ""))
    if not expected_hash or file_sha256(trash_copy) != expected_hash:
        raise RescueError("Recovery transcript failed its SHA-256 integrity check.")
    atomic_write(source, trash_copy.read_bytes())
    if file_sha256(source) != expected_hash:
        raise RescueError("Restored transcript did not preserve its original SHA-256 hash.")
    binary = find_codex_binary()
    with AppServerClient(binary) as client:
        expected_archived = _is_relative_to(source, (codex_home / "archived_sessions").resolve())
        fetch_thread(client, thread_id, expected_archived)
    return {
        "id": thread_id,
        "restoredPath": str(source),
        "sha256": expected_hash,
        "verified": True,
        "restartRecommended": True,
    }


HTML_PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Session Rescue for Codex</title>
<style>
:root{--canvas:oklch(13% .004 75);--rail:oklch(16% .004 75);--surface:oklch(19% .005 75);--ledger:oklch(23% .006 75);--line:oklch(38% .006 75);--text:oklch(92% .006 85);--muted:oklch(68% .008 75);--accent:oklch(92% .006 85);--green:oklch(72% .12 145);--focus:oklch(96% .004 85);--ease:cubic-bezier(.23,1,.32,1);font-family:Bahnschrift,Aptos,"Trebuchet MS",sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--text);min-height:100vh;font-size:15px}button,input,select{font:inherit}button{color:inherit}.app{display:grid;grid-template-columns:15rem minmax(0,1fr);min-height:100vh}.rail{position:sticky;top:0;height:100vh;background:var(--rail);border-right:1px solid var(--line);padding:1.3rem 1rem;display:flex;flex-direction:column;gap:1.4rem}.brand{display:grid;grid-template-columns:2.4rem 1fr;align-items:center;gap:.7rem}.mark{display:grid;place-items:center;width:2.4rem;height:2.4rem}.mark img{display:block;width:2.4rem;height:2.4rem;object-fit:contain}.brand strong{display:block;letter-spacing:.04em}.brand small{color:var(--muted)}.nav{display:grid;gap:.35rem}.nav button,.action{border:1px solid transparent;background:transparent;text-align:left;padding:.68rem .72rem;border-radius:2px;cursor:pointer;transition:background 140ms var(--ease),border-color 140ms var(--ease),transform 140ms var(--ease)}.nav button[aria-current=true]{background:var(--ledger);border-color:var(--line);color:var(--text)}.nav button:hover,.action:hover{background:var(--ledger)}button:active{transform:scale(.97)}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--focus);outline-offset:2px}.rail-note{margin-top:auto;color:var(--muted);font-size:.78rem;line-height:1.45}.rail-note code,.mono{font-family:"Cascadia Mono",Consolas,monospace}.main{min-width:0;padding:1.5rem clamp(1rem,3vw,3.2rem) 3rem}.mast{display:flex;align-items:flex-start;justify-content:space-between;gap:2rem;margin-bottom:1.2rem}.mast h1{font-size:1.65rem;line-height:1.1;margin:0 0 .35rem;letter-spacing:.01em}.mast p{margin:0;color:var(--muted);max-width:70ch}.help{width:2.4rem;height:2.4rem;border:1px solid var(--line);background:var(--surface);cursor:pointer;border-radius:2px}.status-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid var(--line);margin-bottom:1rem}.metric{padding:.75rem 1rem;border-right:1px solid var(--line)}.metric:last-child{border-right:0}.metric span{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.12em}.metric strong{font:600 1.08rem "Cascadia Mono",Consolas,monospace}.toolbar{display:grid;grid-template-columns:minmax(14rem,1fr) auto auto;gap:.6rem;margin:1rem 0}.field,select{width:100%;background:var(--surface);border:1px solid var(--line);color:var(--text);padding:.7rem .78rem;border-radius:2px}.action{background:var(--surface);border-color:var(--line);text-align:center;white-space:nowrap}.action.primary{background:var(--accent);border-color:var(--accent);color:var(--canvas);font-weight:700}.action.danger{border-color:color-mix(in oklch,var(--muted),var(--line) 45%);color:oklch(78% .12 30)}.action:disabled{opacity:.42;cursor:not-allowed;transform:none}.bulk{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;padding:.7rem 0;border-bottom:1px solid var(--line)}.bulk .count{margin-right:auto;color:var(--muted)}.ledger{border-bottom:1px solid var(--line)}.project{margin-top:1.25rem;min-width:0}.project-head{display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid var(--text);padding:.45rem 0}.project-head h2{font-size:.85rem;text-transform:uppercase;letter-spacing:.09em;margin:0;overflow-wrap:anywhere;min-width:0}.project-head span{font-family:"Cascadia Mono",Consolas,monospace;color:var(--muted);font-size:.76rem}.row{display:grid;grid-template-columns:2.4rem minmax(15rem,1.7fr) minmax(12rem,1fr) 8rem 14rem;gap:.8rem;align-items:center;padding:.82rem 0;border-bottom:1px solid var(--line);min-width:0}.row>div{min-width:0}.row:hover{background:color-mix(in oklch,var(--ledger),transparent 35%)}.row input{width:1rem;height:1rem;accent-color:var(--accent)}.title{font-weight:650;overflow-wrap:anywhere}.preview{color:var(--muted);font-size:.8rem;margin-top:.24rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.path{font:normal .72rem "Cascadia Mono",Consolas,monospace;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.badge{display:inline-flex;align-items:center;gap:.35rem;border:1px solid var(--line);padding:.25rem .42rem;border-radius:2px;font:600 .68rem "Cascadia Mono",Consolas,monospace;text-transform:uppercase}.badge::before{content:"";width:.45rem;height:.45rem;background:var(--green)}.badge.archived::before{background:var(--accent)}.date{font:normal .7rem "Cascadia Mono",Consolas,monospace;color:var(--muted)}.row-actions{display:flex;gap:.35rem;justify-content:flex-end}.row-actions button{padding:.42rem .55rem;font-size:.72rem}.empty{padding:4rem 1rem;text-align:center;color:var(--muted);border:1px solid var(--line)}dialog{width:min(43rem,calc(100vw - 2rem));background:var(--surface);color:var(--text);border:1px solid var(--line);border-radius:2px;padding:0;box-shadow:0 1.5rem 5rem oklch(5% 0 0/.55);opacity:1;transform:translateY(0);transition:opacity 180ms var(--ease),transform 180ms var(--ease)}dialog::backdrop{background:oklch(5% 0 0/.72)}dialog[open]{@starting-style{opacity:0;transform:translateY(.5rem)}}.dialog-body{padding:1.4rem}.dialog-body h2{margin:0 0 .8rem}.dialog-body p,.dialog-body li{color:var(--muted);line-height:1.55}.dialog-actions{display:flex;justify-content:flex-end;gap:.5rem;border-top:1px solid var(--line);padding:.8rem 1rem}.toast{position:fixed;right:1rem;bottom:1rem;max-width:min(28rem,calc(100vw - 2rem));background:var(--text);color:var(--canvas);padding:.8rem 1rem;border-radius:2px;transform:translateY(0);opacity:1;transition:transform 180ms var(--ease),opacity 180ms var(--ease);z-index:20}.toast.hidden{transform:translateY(1rem);opacity:0;pointer-events:none}.chain{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);margin:1rem 0}.chain div{background:var(--canvas);padding:.65rem}.chain b{display:block;color:var(--accent);font-family:"Cascadia Mono",Consolas,monospace}.chain small{color:var(--muted)}
@media(max-width:1050px){.row{grid-template-columns:2.2rem minmax(12rem,1fr) 8rem 11rem}.row .path{display:none}}
@media(max-width:820px){.app{display:block}.rail{position:static;width:auto;height:auto;border-right:0;border-bottom:1px solid var(--line)}.nav{grid-template-columns:repeat(3,1fr)}.rail-note{display:none}.status-strip{grid-template-columns:repeat(2,1fr)}.metric:nth-child(2){border-right:0}.metric:nth-child(-n+2){border-bottom:1px solid var(--line)}.toolbar{grid-template-columns:1fr}.row{grid-template-columns:2rem 1fr auto}.row .date{display:none}.row-actions{grid-column:2/4;justify-content:flex-start}}
@media(hover:hover) and (pointer:fine){.action:hover,.nav button:hover{border-color:var(--muted)}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition-duration:0ms!important;animation-duration:0ms!important}}
</style>
</head>
<body>
<div class="app">
<aside class="rail"><div class="brand"><div class="mark"><img src="/assets/codex-logo.png" alt="Codex logo"></div><div><strong>SESSION RESCUE</strong><small>for Codex</small></div></div><nav class="nav" aria-label="Task state"><button data-filter="all" aria-current="true">All tasks</button><button data-filter="active">Active</button><button data-filter="archived">Archived</button></nav><div class="rail-note">Local only<br>No telemetry<br>Native Codex protocol<br><code>v<span id="version">1.0.0</span><br>Build <span id="buildDate">00-00-00</span></code></div></aside>
<main class="main"><header class="mast"><div><h1>Task recovery ledger</h1><p>Find the exact task, preserve its transcript, then make one verified change.</p></div><button class="help" id="help" aria-label="Open help">?</button></header>
<section class="status-strip" aria-label="Store status"><div class="metric"><span>Active</span><strong id="activeCount">0</strong></div><div class="metric"><span>Archived</span><strong id="archivedCount">0</strong></div><div class="metric"><span>Selected</span><strong id="selectedCount">0</strong></div><div class="metric"><span>Protocol</span><strong id="protocolState">checking</strong></div></section>
<div class="toolbar"><input class="field" id="search" type="search" placeholder="Search title, project, task ID, or prompt" aria-label="Search tasks"><select id="source" aria-label="Filter by source"><option value="all">All sources</option></select><button class="action" id="orphans">Integrity report</button></div>
<div class="bulk"><span class="count" id="selectionText">No tasks selected</span><button class="action primary" id="restoreSelected" disabled>Restore selected</button><button class="action" id="archiveSelected" disabled>Archive selected</button><button class="action danger" id="trashSelected" disabled>Trash selected</button></div>
<div id="ledger" class="ledger" aria-live="polite"></div></main></div>
<dialog id="helpDialog"><div class="dialog-body"><h2>Recovery workflow</h2><ol><li>Filter to Archived and identify the task by project, prompt, and task ID.</li><li>Select Restore. The tool creates a timestamped transcript backup first.</li><li>The native Codex <code>thread/unarchive</code> operation moves the byte-identical transcript back to its dated session store.</li><li>Fully close Codex Desktop and start it again so the sidebar reloads the restored state.</li><li>Verify the task title and history before continuing work.</li></ol><div class="chain"><div><b>01</b><small>Discover</small></div><div><b>02</b><small>Back up</small></div><div><b>03</b><small>Native action</small></div><div><b>04</b><small>Verify</small></div></div><p>Trash is recoverable: the full JSONL transcript and manifest remain under <code>session-rescue-trash</code>. No data leaves this computer.</p><p>Built by <strong>Glen E. Grant</strong>. Last updated: <span id="buildTime"></span></p></div><div class="dialog-actions"><button class="action" onclick="helpDialog.close()">Close</button></div></dialog>
<dialog id="confirmDialog"><div class="dialog-body"><h2 id="confirmTitle">Confirm</h2><p id="confirmText"></p></div><div class="dialog-actions"><button class="action" id="cancelConfirm">Cancel</button><button class="action primary" id="acceptConfirm">Confirm</button></div></dialog>
<div class="toast hidden" id="toast" role="status"></div>
<script>
const state={sessions:[],filter:'all',query:'',source:'all',selected:new Set(),diagnostic:null};
const $=id=>document.getElementById(id); const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
async function api(path,body={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Rescue-Token':window.RESCUE_TOKEN},body:JSON.stringify(body)});const data=await response.json();if(!response.ok||data.error)throw new Error(data.error||`Request failed (${response.status})`);return data}
function showToast(message){const node=$('toast');node.textContent=message;node.classList.remove('hidden');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>node.classList.add('hidden'),4200)}
function formatDate(epoch){if(!epoch)return 'unknown';return new Date(epoch*1000).toLocaleString()}
function filtered(){return state.sessions.filter(item=>{if(state.filter==='active'&&item.archived)return false;if(state.filter==='archived'&&!item.archived)return false;if(state.source!=='all'&&item.source!==state.source)return false;const hay=[item.title,item.preview,item.cwd,item.id].join('\n').toLowerCase();return hay.includes(state.query.toLowerCase())})}
function render(){const rows=filtered();const groups=new Map();for(const row of rows){const key=row.cwd||'No project directory';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row)}$('activeCount').textContent=state.sessions.filter(x=>!x.archived).length;$('archivedCount').textContent=state.sessions.filter(x=>x.archived).length;$('selectedCount').textContent=state.selected.size;$('selectionText').textContent=state.selected.size?`${state.selected.size} task(s) selected`:'No tasks selected';$('restoreSelected').disabled=![...state.selected].some(id=>state.sessions.find(x=>x.id===id)?.archived);$('archiveSelected').disabled=![...state.selected].some(id=>!state.sessions.find(x=>x.id===id)?.archived);$('trashSelected').disabled=!state.selected.size;if(!rows.length){$('ledger').innerHTML='<div class="empty">No tasks match this evidence filter.</div>';return}let html='';for(const [project,items] of groups){html+=`<section class="project"><header class="project-head"><h2>${escapeHtml(project)}</h2><span>${items.length} task(s)</span></header>`;for(const item of items){html+=`<article class="row"><input type="checkbox" aria-label="Select ${escapeHtml(item.title)}" data-id="${escapeHtml(item.id)}" ${state.selected.has(item.id)?'checked':''}><div><div class="title">${escapeHtml(item.title)}</div><div class="preview">${escapeHtml(item.preview||'No prompt preview')}</div></div><div class="path" title="${escapeHtml(item.path)}">${escapeHtml(item.id)}<br>${escapeHtml(item.source)} · ${escapeHtml(item.cliVersion||'unknown version')}</div><div><span class="badge ${item.archived?'archived':''}">${item.archived?'Archived':'Active'}</span></div><div><div class="date">Updated ${escapeHtml(formatDate(item.updatedAt))}</div><div class="row-actions"><button class="action ${item.archived?'primary':''}" data-action="${item.archived?'unarchive':'archive'}" data-id="${escapeHtml(item.id)}">${item.archived?'Restore':'Archive'}</button><button class="action danger" data-action="trash" data-id="${escapeHtml(item.id)}">Trash</button></div></div></article>`}html+='</section>'}$('ledger').innerHTML=html;document.querySelectorAll('input[data-id]').forEach(box=>box.addEventListener('change',()=>{box.checked?state.selected.add(box.dataset.id):state.selected.delete(box.dataset.id);render()}));document.querySelectorAll('button[data-action]').forEach(button=>button.addEventListener('click',()=>confirmAction(button.dataset.action,[button.dataset.id]))) }
async function refresh(){try{$('protocolState').textContent='loading';const data=await api('/api/list');state.sessions=data.sessions;state.diagnostic=data.diagnostic;$('protocolState').textContent='native';$('version').textContent=data.diagnostic.version;$('buildTime').textContent=data.diagnostic.build;$('buildDate').textContent=data.diagnostic.buildDate;const sources=[...new Set(state.sessions.map(x=>x.source))].sort();$('source').innerHTML='<option value="all">All sources</option>'+sources.map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join('');render()}catch(error){$('protocolState').textContent='error';showToast(error.message)}}
function confirmAction(action,ids){const valid=ids.filter(Boolean);if(!valid.length)return;const labels={unarchive:'Restore',archive:'Archive',trash:'Move to recovery trash'};$('confirmTitle').textContent=`${labels[action]} ${valid.length} task(s)?`;$('confirmText').textContent=action==='trash'?'A full transcript copy and manifest will be retained before Codex removes the task. This is recoverable, but intentionally disruptive.':`A timestamped transcript backup will be created before the native Codex ${action} operation.`;$('acceptConfirm').onclick=async()=>{confirmDialog.close();try{const result=await api(`/api/${action}`,{ids:valid});showToast(`${result.succeeded}/${result.requested} task(s) ${action==='unarchive'?'restored':action+'d'} and verified.`);state.selected.clear();await refresh();if(result.restartRecommended)showToast('Verified on disk. Fully close and restart Codex Desktop now so its sidebar reloads.')}catch(error){showToast(error.message)}};confirmDialog.showModal()}
document.querySelectorAll('.nav button').forEach(button=>button.addEventListener('click',()=>{state.filter=button.dataset.filter;document.querySelectorAll('.nav button').forEach(x=>x.setAttribute('aria-current',String(x===button)));render()}));$('search').addEventListener('input',event=>{state.query=event.target.value;render()});$('source').addEventListener('change',event=>{state.source=event.target.value;render()});$('help').addEventListener('click',()=>helpDialog.showModal());$('cancelConfirm').addEventListener('click',()=>confirmDialog.close());$('restoreSelected').addEventListener('click',()=>confirmAction('unarchive',[...state.selected].filter(id=>state.sessions.find(x=>x.id===id)?.archived)));$('archiveSelected').addEventListener('click',()=>confirmAction('archive',[...state.selected].filter(id=>!state.sessions.find(x=>x.id===id)?.archived)));$('trashSelected').addEventListener('click',()=>confirmAction('trash',[...state.selected]));$('orphans').addEventListener('click',async()=>{try{const report=await api('/api/orphans');showToast(`Integrity scan: ${report.transcriptWithoutProtocolRecord.length} unindexed transcript(s), ${report.protocolRecordWithoutTranscript.length} missing transcript(s).`)}catch(error){showToast(error.message)}});setInterval(()=>api('/api/heartbeat').catch(()=>{}),2500);refresh();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    last_heartbeat = time.time()
    rescue_token = uuid.uuid4().hex
    custom_home: str | None = None

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _headers(self, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        if request_path == "/assets/codex-logo.png":
            logo_path = Path(__file__).resolve().parent / "assets" / "codex-logo.png"
            if not logo_path.is_file():
                self._headers(404, "text/plain; charset=utf-8")
                self.wfile.write(b"Logo not found")
                return
            self._headers(200, "image/png")
            self.wfile.write(logo_path.read_bytes())
            return
        if request_path != "/":
            self._headers(404, "text/plain; charset=utf-8")
            self.wfile.write(b"Not found")
            return
        page = HTML_PAGE.replace(
            "<script>", f"<script>window.RESCUE_TOKEN={json.dumps(self.rescue_token)};</script><script>", 1
        )
        self._headers(200, "text/html; charset=utf-8")
        self.wfile.write(page.encode("utf-8"))

    def do_POST(self) -> None:
        if self.headers.get("X-Rescue-Token") != self.rescue_token:
            self._json({"error": "Invalid local request token."}, 403)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            self._json({"error": "Request too large."}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"error": "Invalid JSON request."}, 400)
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/heartbeat":
                Handler.last_heartbeat = time.time()
                result: dict[str, Any] = {"ok": True}
            elif path == "/api/list":
                sessions, diagnostic = load_all_sessions(self.custom_home)
                result = {"sessions": sessions, "diagnostic": diagnostic}
            elif path in {"/api/archive", "/api/unarchive", "/api/trash"}:
                ids = body.get("ids")
                if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                    raise RescueError("ids must be a list of task IDs.")
                result = mutate_threads(ids, path.rsplit("/", 1)[-1], self.custom_home)
            elif path == "/api/orphans":
                result = find_orphans(self.custom_home)
            else:
                self._json({"error": "Unknown endpoint."}, 404)
                return
            self._json(result, 200)
        except RescueError as error:
            self._json({"error": str(error)}, 409)
        except Exception as error:
            self._json({"error": f"Unexpected local failure: {error}"}, 500)

    def _json(self, value: dict[str, Any], status: int) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8")
        self.wfile.write(payload)


def cli_list(custom_home: str | None) -> int:
    sessions, diagnostic = load_all_sessions(custom_home)
    for row in sessions:
        state = "ARCHIVED" if row["archived"] else "active  "
        print(f"[{state}] [{row['source']:<8.8}] {row['title'][:52]:<52} {row['cwd']}")
        print(f"           {row['id']}")
    print(f"\n{len(sessions)} tasks: {diagnostic['active']} active, {diagnostic['archived']} archived.")
    return 0


def run_server(custom_home: str | None) -> int:
    codex_home = discover_codex_home(custom_home)
    lock_file = codex_home / LOCK_NAME
    Handler.custom_home = custom_home
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    atomic_write(lock_file, str(os.getpid()).encode("ascii"))
    url = f"http://127.0.0.1:{PORT}"
    print(f"{APP_NAME} v{VERSION}")
    print(f"Local server: {url}")
    print("Close the browser tab to stop the server.")

    def watchdog() -> None:
        while True:
            time.sleep(5)
            if time.time() - Handler.last_heartbeat > 35:
                server.shutdown()
                return

    def shutdown(_signal: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        try:
            lock_file.unlink()
        except OSError:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME}: safely manage archived Codex tasks")
    parser.add_argument("--path", help="Custom Codex home directory")
    parser.add_argument("--list", action="store_true", help="List active and archived tasks")
    parser.add_argument("--restore-all-archived", action="store_true", help="Restore all archived tasks")
    parser.add_argument("--archive", action="append", metavar="THREAD_ID", help="Archive one task by ID")
    parser.add_argument("--restore", action="append", metavar="THREAD_ID", help="Restore one task by ID")
    parser.add_argument("--restore-trash", metavar="THREAD_ID", help="Recover the newest trashed copy of one task")
    parser.add_argument("--orphans", action="store_true", help="Print the integrity report")
    args = parser.parse_args()
    try:
        if args.list:
            return cli_list(args.path)
        if args.orphans:
            print(json.dumps(find_orphans(args.path), indent=2))
            return 0
        if args.archive:
            print(json.dumps(mutate_threads(args.archive, "archive", args.path), indent=2))
            return 0
        if args.restore:
            print(json.dumps(mutate_threads(args.restore, "unarchive", args.path), indent=2))
            return 0
        if args.restore_trash:
            print(json.dumps(restore_from_trash(args.restore_trash, args.path), indent=2))
            return 0
        if args.restore_all_archived:
            sessions, _ = load_all_sessions(args.path)
            archived = [row["id"] for row in sessions if row["archived"]]
            if not archived:
                print("No archived tasks found.")
                return 0
            print(json.dumps(mutate_threads(archived, "unarchive", args.path), indent=2))
            return 0
        return run_server(args.path)
    except RescueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
