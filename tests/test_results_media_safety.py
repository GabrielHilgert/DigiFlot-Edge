"""Hardware-free safety tests for idle-only MJPEG playback."""
import ast
import asyncio
import os
import shutil
import struct
import subprocess
import tempfile
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
    import time
    namespace = {"threading": threading, "asyncio": asyncio, "shutil": shutil, "subprocess": subprocess,
                 "Path": Path, "MAX_SESSIONS": 2, "MAX_FRAME_BYTES": 12 * 1024 * 1024,
                 "MAX_DISPLAY_FPS": 12.0, "time": time, "os": os, "struct": struct,
                 "WebSocketDisconnect": type("WebSocketDisconnect", (Exception,), {})}
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


    def test_actual_mjpeg_frame_streams_without_extra_files(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is not installed")
        with tempfile.TemporaryDirectory() as directory:
            recording = Path(directory) / "recording.avi"
            command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                       "testsrc2=size=160x120:rate=10", "-frames:v", "6", "-c:v", "mjpeg", str(recording)]
            subprocess.run(command, capture_output=True, check=True, timeout=20)

            class FakeWebSocket:
                def __init__(self):
                    self.frames = []
                    self.messages = []

                async def send_bytes(self, data):
                    self.frames.append(data)

                async def send_json(self, data):
                    self.messages.append(data)

            async def run():
                classes = media_classes()
                manager = classes["ResultsMediaManager"]()
                digiflot = SimpleNamespace(IDLE="Idle", state="Idle", lock=threading.RLock())
                websocket = FakeWebSocket()
                session = classes["ResultsMediaSession"](websocket, digiflot, manager, recording,
                                                         {"fps": 10.0, "duration_s": 0.6})
                self.assertTrue(manager.register(session))
                await session.stream(0, 1, single=True)
                self.assertEqual(len(websocket.frames), 1)
                self.assertEqual(websocket.frames[0][8:10], bytes.fromhex("ffd8"))
                self.assertEqual(websocket.frames[0][-2:], bytes.fromhex("ffd9"))
                self.assertIsNone(session.process)
                manager.discard(session)

            asyncio.run(run())
            self.assertEqual(list(Path(directory).iterdir()), [recording],
                             "Direct MJPEG playback must not generate preview files")

    def test_state_machine_revokes_before_preparation(self):
        digiflot = (SOURCE.parents[2] / "src/lib/digiflot.py").read_text(encoding="utf-8")
        start = digiflot.index("    def select_experiment(")
        body = digiflot[start:digiflot.index("    def select_physical_cell(", start)]
        self.assertLess(body.index("self.results_media_manager.revoke()"), body.index("self._reset_run_state_unlocked()"))
        app = (SOURCE.parents[2] / "src/app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(results_media_router)", app)
        self.assertIn("app.state.results_media_manager.revoke()", app)
        results = (SOURCE.parents[2] / "src/api/results.py").read_text(encoding="utf-8")
        self.assertIn('raise HTTPException(status_code=409, detail="Video playback requires DigiFlot to be Idle.")', results)


if __name__ == "__main__":
    unittest.main()
