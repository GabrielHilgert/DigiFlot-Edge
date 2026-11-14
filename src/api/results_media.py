"""On-demand, idle-only MJPEG playback over WebSocket.

No media workers run at startup. Each connected player owns at most one short-lived
FFmpeg stream-copy process; no preview files are created on disk.
"""
import asyncio
import os
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from api.local import get_local_directory
from api.results import _VIDEO_PROBE_CACHE, _safe_relative_path

router = APIRouter(prefix="/api/results", tags=["results-media"])
MAX_SESSIONS = 2
MAX_FRAME_BYTES = 12 * 1024 * 1024
MAX_DISPLAY_FPS = 12.0


class ResultsMediaManager:
    """Tracks only active viewers; revocation runs synchronously on exit from Idle."""

    def __init__(self, max_sessions=MAX_SESSIONS):
        self.lock = threading.Lock()
        self.sessions = set()
        self.max_sessions = max_sessions
        self.generation = 0

    def register(self, session):
        with self.lock:
            if len(self.sessions) >= self.max_sessions:
                return False
            self.sessions.add(session)
            session.generation = self.generation
            return True

    def discard(self, session):
        with self.lock:
            self.sessions.discard(session)

    def revoke(self):
        # Called while DigiFlot.lock is held, before preparing another experiment.
        with self.lock:
            self.generation += 1
            sessions = tuple(self.sessions)
        for session in sessions:
            session.revoke()


class MediaSessionRevoked(Exception):
    pass


class ResultsMediaSession:
    def __init__(self, websocket, digiflot, manager, file_path: Path, probe: dict):
        self.websocket = websocket
        self.digiflot = digiflot
        self.manager = manager
        self.file_path = file_path
        self.fps = max(0.1, float(probe.get("fps") or 30))
        self.duration = max(0.0, float(probe.get("duration_s") or 0))
        self.generation = -1
        self.loop = asyncio.get_running_loop()
        self.revoked = False
        self.task = None
        self.process = None
        self.send_lock = asyncio.Lock()

    def permitted(self):
        return (not self.revoked and self.digiflot.state == self.digiflot.IDLE
                and self.generation == self.manager.generation)

    def _kill_process(self):
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def revoke(self):
        self.revoked = True
        self._kill_process()
        try:
            self.loop.call_soon_threadsafe(self._schedule_revoke)
        except RuntimeError:
            pass

    def _schedule_revoke(self):
        if self.task:
            self.task.cancel()
        asyncio.create_task(self._notify_revoke())

    async def _notify_revoke(self):
        try:
            await self.websocket.close(code=4409, reason="Result playback requires Idle")
        except (RuntimeError, OSError):
            pass

    async def send(self, payload):
        if self.revoked:
            return
        async with self.send_lock:
            if isinstance(payload, bytes):
                await self.websocket.send_bytes(payload)
            else:
                await self.websocket.send_json(payload)

    def _start_process(self, position, one_frame=False):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for MJPEG playback")
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                   "-ss", f"{position:.6f}", "-i", str(self.file_path),
                   "-map", "0:v:0", "-an", "-c:v", "copy"]
        if self.file_path.suffix.lower() == ".avi":
            command += ["-bsf:v", "mjpeg2jpeg"]
        if one_frame:
            command += ["-frames:v", "1"]
        command += ["-f", "image2pipe", "pipe:1"]
        # No await here: the lock protects process creation against the
        # Idle -> preparation transition in another FastAPI worker thread.
        with self.digiflot.lock:
            if not self.permitted():
                raise MediaSessionRevoked()
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, bufsize=0)
            self.process = process
        return process

    async def stop(self):
        task = self.task
        self.task = None
        if task:
            task.cancel()
        self._kill_process()
        if task:
            try:
                await task
            except (asyncio.CancelledError, MediaSessionRevoked):
                pass

    async def stream(self, position, rate, single=False):
        process = None
        frame_index = 0
        last_sent = -float("inf")
        started = time.monotonic()
        pending = bytearray()
        try:
            process = self._start_process(position, one_frame=single)
            while self.permitted():
                chunk = await asyncio.to_thread(os.read, process.stdout.fileno(), 128 * 1024)
                if not chunk:
                    break
                pending.extend(chunk)
                while True:
                    start = pending.find(b"\xff\xd8")
                    if start < 0:
                        pending.clear()
                        break
                    if start:
                        del pending[:start]
                    end = pending.find(b"\xff\xd9", 2)
                    if end < 0:
                        if len(pending) > MAX_FRAME_BYTES:
                            raise RuntimeError("JPEG frame exceeds preview memory limit")
                        break
                    if end + 2 > MAX_FRAME_BYTES:
                        raise RuntimeError("JPEG frame exceeds preview memory limit")
                    jpeg = bytes(pending[:end + 2])
                    del pending[:end + 2]
                    timestamp = position + frame_index / self.fps
                    frame_index += 1
                    if not self.permitted():
                        raise MediaSessionRevoked()
                    if not single:
                        spacing = max(1 / self.fps, rate / MAX_DISPLAY_FPS)
                        if timestamp - last_sent < spacing - 0.0001:
                            continue
                        deadline = started + (timestamp - position) / rate
                        delay = deadline - time.monotonic()
                        if delay < -0.25:
                            continue
                        if delay > 0:
                            await asyncio.sleep(delay)
                    if not self.permitted():
                        raise MediaSessionRevoked()
                    await self.send(struct.pack("!d", timestamp) + jpeg)
                    last_sent = timestamp
                    if single:
                        return
            if self.permitted():
                await self.send({"type": "frame" if single else "ended",
                                 "time": min(self.duration, position + frame_index / self.fps)})
        except (MediaSessionRevoked, asyncio.CancelledError, WebSocketDisconnect):
            pass
        except (OSError, RuntimeError, ValueError) as error:
            if self.permitted():
                try:
                    await self.send({"type": "error", "message": str(error)})
                except (RuntimeError, WebSocketDisconnect, OSError):
                    pass
        finally:
            self._kill_process()
            if process is not None:
                try:
                    await asyncio.to_thread(process.wait, timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)
                if process.stdout:
                    process.stdout.close()
                if self.process is process:
                    self.process = None

    async def run(self):
        try:
            await self.send({"type": "ready", "fps": self.fps, "duration_s": self.duration,
                             "max_fps": MAX_DISPLAY_FPS})
            while self.permitted():
                command = await self.websocket.receive_json()
                if not self.permitted():
                    break
                action = command.get("type")
                if action not in {"play", "seek", "pause"}:
                    await self.send({"type": "error", "message": "Unsupported media command"})
                    continue
                await self.stop()
                if action == "pause":
                    await self.send({"type": "paused"})
                    continue
                try:
                    position = float(command.get("time", 0))
                    rate = float(command.get("rate", 1))
                    if not (0 <= position < float("inf") and 0.25 <= rate <= 4.0):
                        raise ValueError()
                except (TypeError, ValueError):
                    await self.send({"type": "error", "message": "Invalid playback time or rate"})
                    continue
                position = min(position, max(0.0, self.duration - 0.001)) if self.duration else position
                self.task = asyncio.create_task(self.stream(position, rate, single=action == "seek"))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await self.stop()
            self.manager.discard(self)


@router.websocket("/{storage_id}/mjpeg")
async def playback(websocket: WebSocket, storage_id: str, path: str = Query(...)):
    await websocket.accept()
    digiflot = websocket.app.state.digiflot
    manager = websocket.app.state.results_media_manager
    session = None
    with digiflot.lock:
        if digiflot.state == digiflot.IDLE:
            try:
                directory = get_local_directory(storage_id)
                file_path = _safe_relative_path(directory, path)
                # Results overview already ffprobes each recording. Reuse that
                # metadata: never launch ffprobe while holding the run controller
                # lock, which could otherwise delay experiment preparation.
                stat = file_path.stat()
                cache_key = (str(file_path.resolve()), stat.st_size, stat.st_mtime_ns)
                probe = _VIDEO_PROBE_CACHE.get(cache_key) or {}
                if probe.get("codec") == "mjpeg" and probe.get("ok"):
                    session = ResultsMediaSession(websocket, digiflot, manager, file_path, probe)
            except Exception:
                pass
            if session and not manager.register(session):
                session = None
    if session is None:
        await websocket.send_json({"type": "error", "message":
            "Playback unavailable: DigiFlot must be Idle, the recording metadata must be loaded, and at most two viewers are supported. Refresh Results if necessary."})
        await websocket.close(code=4409)
        return
    await session.run()
