"""Hardware-free regression for fast, cached browser preview conversion."""
import ast
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def preview_functions():
    source = Path(__file__).resolve().parents[1] / "src/api/results.py"
    parsed = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    required = {"_browser_video_cache_path", "_ensure_browser_video"}
    nodes = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name in required]
    assert len(nodes) == len(required), "Results video preview functions have changed"
    namespace = {
        "Path": Path, "hashlib": hashlib, "shutil": shutil, "subprocess": subprocess, "HTTPException": RuntimeError,
        "_relative": lambda directory, path: path.relative_to(directory).as_posix(),
        "_results_cache_directory": lambda directory: directory.parent / ".results_cache" / directory.name,
        "_video_media_type": lambda path: "video/mp4" if path.suffix == ".mp4" else "video/x-msvideo", "_parse_number": float,
        "_probe_video": lambda path: {"browser_compatible": False, "fps": 30.0},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


class ResultsVideoPreviewTest(unittest.TestCase):
    def test_fast_preview_uses_existing_cache_and_preserves_original(self):
        namespace = preview_functions()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "experiment"
            directory.mkdir()
            original = directory / "recording.avi"
            original.write_bytes(b"unmodified-original-video")
            stat = original.stat()
            digest = hashlib.sha256(f"recording.avi|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()[:20]
            expected = directory.parent / ".results_cache" / directory.name / f"{digest}.browser.mp4"
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                Path(command[-1]).write_bytes(b"browser-preview")
                return SimpleNamespace(returncode=0, stderr="", stdout="")

            with patch.object(shutil, "which", return_value="ffmpeg"), patch.object(subprocess, "run", side_effect=fake_run):
                output, media_type, transcoded = namespace["_ensure_browser_video"](directory, original)
                self.assertEqual((output, media_type, transcoded), (expected, "video/mp4", True))
                self.assertEqual(original.read_bytes(), b"unmodified-original-video")
                self.assertEqual(calls[0][calls[0].index("-preset") + 1], "ultrafast")
                self.assertEqual(calls[0][calls[0].index("-crf") + 1], "28")
                self.assertEqual(calls[0][calls[0].index("-c:v") + 1], "libx264")
                self.assertIn("fps=12", calls[0][calls[0].index("-vf") + 1])
                self.assertIn("min(960,iw)", calls[0][calls[0].index("-vf") + 1])
                self.assertEqual(namespace["_ensure_browser_video"](directory, original), (expected, "video/mp4", True))
            self.assertEqual(len(calls), 1, "A cached preview must never be transcoded again")

    def test_compatible_video_is_served_directly(self):
        namespace = preview_functions()
        namespace["_probe_video"] = lambda path: {"browser_compatible": True, "fps": 30.0}
        with tempfile.TemporaryDirectory() as temporary:
            original = Path(temporary) / "recording.mp4"
            original.write_bytes(b"compatible")
            self.assertEqual(namespace["_ensure_browser_video"](original.parent, original),
                             (original, "video/mp4", False))


if __name__ == "__main__":
    unittest.main()
