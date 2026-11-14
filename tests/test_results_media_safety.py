"""Hardware-free safety tests for idle-only MJPEG playback."""
import ast
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "src/api/results_media.py"


def media_classes():
    source = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    names = {"ResultsMediaManager", "ResultsMediaSession", "MediaSessionRevoked"}
    nodes = [item for item in source.body if isinstance(item, ast.ClassDef) and item.name in names]
    assert len(nodes) == len(names)
    import asyncio
    import shutil
    import time
    namespace = {"threading": threading, "asyncio": asyncio, "shutil": shutil, "subprocess": subprocess,
                 "Path": Path, "MAX_SESSIONS": 2, "MAX_FRAME_BYTES": 12 * 1024 * 1024,
                 "MAX_DISPLAY_FPS": 12.0, "time": time}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


class MediaSafetyTest(unittest.TestCase):
    def test_two_tabs_share_session_limit_and_revoke_together(self):
        cls = media_classes()["ResultsMediaManager"]
        manager = cls(max_sessions=2)

        class FakeSession:
            def __init__(self):
                self.generation = -1
                self.revocations = 0

            def revoke(self):
                self.revocations += 1

        first, second, third = FakeSession(), FakeSession(), FakeSession()
        self.assertTrue(manager.register(first))
        self.assertTrue(manager.register(second))
        self.assertFalse(manager.register(third))
        manager.revoke()
        self.assertEqual((first.revocations, second.revocations, third.revocations), (1, 1, 0))
        self.assertEqual(manager.generation, 1)
        manager.discard(first)
        self.assertTrue(manager.register(third))
        self.assertEqual(third.generation, 1)

    def test_ffmpeg_cannot_start_outside_idle_or_after_revoke(self):
        classes = media_classes()
        manager = classes["ResultsMediaManager"]()
        digiflot = SimpleNamespace(IDLE="Idle", state="Idle", lock=threading.RLock())
        session = classes["ResultsMediaSession"].__new__(classes["ResultsMediaSession"])
        session.digiflot, session.manager, session.file_path = digiflot, manager, Path("recording.avi")
        session.revoked, session.generation, session.process = False, 0, None
        self.assertTrue(manager.register(session))
        fake_process = SimpleNamespace(poll=lambda: None)
        with patch("shutil.which", return_value="ffmpeg"), patch.object(subprocess, "Popen", return_value=fake_process) as create:
            self.assertIs(session._start_process(12.5, one_frame=True), fake_process)
            command = create.call_args.args[0]
            self.assertEqual(command[command.index("-c:v") + 1], "copy")
            self.assertIn("mjpeg2jpeg", command)
            self.assertIn("image2pipe", command)
            self.assertIn("-frames:v", command)
            digiflot.state = "CellSelection"
            with self.assertRaises(classes["MediaSessionRevoked"]):
                session._start_process(12)
            self.assertEqual(create.call_count, 1)
            digiflot.state = "Idle"
            session.revoked = True
            with self.assertRaises(classes["MediaSessionRevoked"]):
                session._start_process(12)
            self.assertEqual(create.call_count, 1)

    def test_state_machine_revokes_before_preparation(self):
        digiflot = (SOURCE.parents[1] / "src/lib/digiflot.py").read_text(encoding="utf-8")
        start = digiflot.index("    def select_experiment(")
        body = digiflot[start:digiflot.index("    def select_physical_cell(", start)]
        self.assertLess(body.index("self.results_media_manager.revoke()"), body.index("self._reset_run_state_unlocked()"))
        app = (SOURCE.parents[1] / "src/app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(results_media_router)", app)
        self.assertIn("app.state.results_media_manager.revoke()", app)
        results = (SOURCE.parents[1] / "src/api/results.py").read_text(encoding="utf-8")
        self.assertIn('raise HTTPException(status_code=409, detail="Video playback requires DigiFlot to be Idle.")', results)


if __name__ == "__main__":
    unittest.main()
