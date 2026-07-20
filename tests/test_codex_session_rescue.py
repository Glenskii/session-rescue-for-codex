import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import codex_session_rescue as rescue


class SessionRescueTests(unittest.TestCase):
    def test_version_parser_prefers_numeric_segments(self):
        self.assertEqual((0, 144, 5), rescue.parse_version("0.144.5"))
        self.assertEqual((0, 144, 5), rescue.parse_version("0.144.5-alpha"))

    def test_normalize_thread_preserves_evidence_fields(self):
        row = rescue.normalize_thread(
            {
                "id": "thread-1",
                "name": "Recovered task",
                "preview": "Original request",
                "cwd": "C:/Work",
                "source": "vscode",
                "archived": True,
                "status": {"type": "idle"},
                "path": "C:/Store/thread.jsonl",
            }
        )
        self.assertEqual("thread-1", row["id"])
        self.assertEqual("Recovered task", row["title"])
        self.assertTrue(row["archived"])
        self.assertEqual("idle", row["status"])

    def test_atomic_write_replaces_complete_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            rescue.atomic_write(target, b"first")
            rescue.atomic_write(target, b"second")
            self.assertEqual(b"second", target.read_bytes())
            self.assertEqual([], list(target.parent.glob("*.tmp")))

    def test_backup_is_confined_and_hash_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".codex"
            transcript = root / "sessions" / "2026" / "07" / "18" / "rollout-test.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_bytes(b'{"type":"session_meta"}\n')
            thread = {"id": "thread-1", "path": str(transcript)}
            manifest = rescue.backup_before_mutation(root, thread, "archive")
            backup = Path(manifest["backupPath"])
            self.assertTrue(backup.is_file())
            self.assertEqual(transcript.read_bytes(), backup.read_bytes())
            self.assertEqual(hashlib.sha256(backup.read_bytes()).hexdigest(), manifest["sha256"])
            loaded = json.loads((backup.parent / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("archive", loaded["action"])

    def test_verified_copy_rejects_a_corrupted_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jsonl"
            target = Path(directory) / "target.jsonl"
            source.write_bytes(b'original transcript\n')

            def corrupt_copy(_source, destination):
                Path(destination).write_bytes(b'corrupted transcript\n')

            with patch.object(rescue.shutil, "copy2", side_effect=corrupt_copy):
                with self.assertRaisesRegex(rescue.RescueError, "did not preserve"):
                    rescue.verified_copy(source, target)

    def test_verified_copy_rejects_an_unexpected_source_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jsonl"
            target = Path(directory) / "target.jsonl"
            source.write_bytes(b'original transcript\n')
            with self.assertRaisesRegex(rescue.RescueError, "source failed"):
                rescue.verified_copy(source, target, "0" * 64)
            self.assertFalse(target.exists())

    def test_trash_copy_failure_blocks_native_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".codex"
            backup = root / rescue.BACKUP_DIR / "thread-1" / "stamp" / "rollout.jsonl"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b'original transcript\n')
            client = MagicMock()
            client_context = MagicMock()
            client_context.__enter__.return_value = client
            client_context.__exit__.return_value = False
            manifest = {
                "backupPath": str(backup),
                "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            }
            thread = {"id": "thread-1", "status": {"type": "idle"}}

            with (
                patch.object(rescue, "discover_codex_home", return_value=root),
                patch.object(rescue, "find_codex_binary", return_value=Path("codex")),
                patch.object(rescue, "AppServerClient", return_value=client_context),
                patch.object(rescue, "fetch_thread", return_value=thread),
                patch.object(rescue, "backup_before_mutation", return_value=manifest),
                patch.object(rescue, "verified_copy", side_effect=rescue.RescueError("copy mismatch")),
            ):
                result = rescue.mutate_threads(["thread-1"], "trash")

            self.assertEqual(0, result["succeeded"])
            self.assertEqual(1, result["failed"])
            client.request.assert_not_called()

    def test_path_confinement_rejects_external_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".codex"
            (root / "sessions").mkdir(parents=True)
            external = Path(directory) / "outside.jsonl"
            external.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(rescue.RescueError):
                rescue.safe_resolve_thread_path(root, {"id": "thread-1", "path": str(external)})

    def test_interface_contains_required_identity_and_restart_guidance(self):
        self.assertIn("/assets/codex-logo.png", rescue.HTML_PAGE)
        self.assertIn("Fully close Codex Desktop", rescue.HTML_PAGE)
        self.assertIn("buildDate", rescue.HTML_PAGE)
        self.assertNotIn("--orange", rescue.HTML_PAGE)
        self.assertNotIn("purple", rescue.HTML_PAGE.lower())


if __name__ == "__main__":
    unittest.main()
