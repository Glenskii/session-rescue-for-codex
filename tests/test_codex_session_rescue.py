import hashlib
import json
import tempfile
import unittest
from pathlib import Path

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
