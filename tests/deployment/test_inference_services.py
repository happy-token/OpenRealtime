"""Unit tests for the standalone model-service packaging."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deploy.inference_services.app import JobManager, Settings


class InferenceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def manager(self, kind: str) -> JobManager:
        return JobManager(Settings(kind=kind, runtime_root=self.root / "runtime",
                                   job_root=self.root / "jobs", token="", timeout_seconds=5))

    def test_health_is_not_ready_without_model_runtime(self):
        ready, missing = self.manager("wav2lip").readiness()
        self.assertFalse(ready)
        self.assertTrue(any(".venv/bin/python" in path for path in missing))

    def test_wav2lip_never_accepts_commercial_usage(self):
        manager = self.manager("wav2lip")
        with self.assertRaisesRegex(ValueError, "non-commercial"):
            manager.submit(None, b"video", b"audio", rights_confirmed=True,
                           usage_scope="commercial")

    def test_submit_persists_private_inputs_and_reuses_client_job_id(self):
        manager = self.manager("wav2lip")
        with patch.object(manager, "readiness", return_value=(True, [])), \
             patch.object(manager._executor, "submit"):
            created = manager.submit("client-job-1", b"video", b"audio", rights_confirmed=True)
            repeated = manager.submit("client-job-1", b"different", b"different", rights_confirmed=True)
        directory = self.root / "jobs" / "client-job-1"
        self.assertEqual(created, repeated)
        self.assertEqual((directory / "source.mp4").read_bytes(), b"video")
        self.assertEqual((directory / "reference.wav").stat().st_mode & 0o777, 0o600)
        self.assertEqual(manager.get("client-job-1")["state"], "queued")

    def test_invalid_client_job_id_cannot_escape_job_root(self):
        manager = self.manager("liveportrait")
        with patch.object(manager, "readiness", return_value=(True, [])):
            with self.assertRaisesRegex(ValueError, "invalid job id"):
                manager.submit("../outside", b"portrait", b"driving", rights_confirmed=True)

    def test_liveportrait_job_preserves_media_extensions_and_motion_config(self):
        manager = self.manager("liveportrait")
        with patch.object(manager, "readiness", return_value=(True, [])), \
             patch.object(manager._executor, "submit"):
            job = manager.submit("liveportrait-test", b"jpeg", b"webm", rights_confirmed=True,
                                 source_extension=".jpg", reference_extension=".webm",
                                 config_json='{"driving_multiplier": 1}')
        directory = self.root / "jobs" / job["id"]
        self.assertEqual((directory / "source.jpg").read_bytes(), b"jpeg")
        self.assertEqual((directory / "driving.webm").read_bytes(), b"webm")
        command = manager._command(directory, "personal")
        self.assertIn("--config-json", command)
        self.assertIn(str(directory / "config.json"), command)

    def test_liveportrait_rejects_unsupported_media_extension(self):
        manager = self.manager("liveportrait")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            manager.submit(None, b"source", b"driving", rights_confirmed=True,
                           source_extension=".svg")

    def test_every_model_requires_media_rights(self):
        for kind in ("wav2lip", "musetalk", "liveportrait"):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "rights"):
                    self.manager(kind).submit(None, b"video", b"audio", rights_confirmed=False)

    def test_restart_marks_incomplete_job_failed_without_restarting_inference(self):
        manager = self.manager("liveportrait")
        job_dir = self.root / "jobs" / "job-1"
        job_dir.mkdir()
        (job_dir / "job.json").write_text(json.dumps({"id": "job-1", "state": "processing"}))
        next_manager = self.manager("liveportrait")
        self.assertEqual(next_manager.get("job-1")["state"], "failed")
        self.assertIn("restarted", next_manager.get("job-1")["error"])
        self.assertEqual(manager.settings.job_root, next_manager.settings.job_root)

    def test_model_commands_reuse_existing_providers(self):
        directory = self.root / "job"
        directory.mkdir()
        (directory / "source.jpg").write_bytes(b"portrait")
        (directory / "driving.mp4").write_bytes(b"driving")
        with patch("sys.executable", "/usr/bin/python3"):
            wav = self.manager("wav2lip")._command(directory, "research")
            live = self.manager("liveportrait")._command(directory, "personal")
        muse = self.manager("musetalk")._command(directory, "personal")
        self.assertIn("wav2lip_provider.py", wav[1])
        self.assertIn("--usage-scope", wav)
        self.assertIn("liveportrait_provider.py", live[1])
        self.assertIn("generate_musetalk_talking.sh", muse[1])


if __name__ == "__main__":
    unittest.main()
