"""Demo server (stdlib only).

GET  /          demo UI
GET  /aop       the AOP JSON being run (for the "What we ask" tab)
GET  /screen    live MJPEG stream of the agent's browser (CDP screencast)
GET  /events    Server-Sent Events: every step, decision, flag, metric
POST /run       start a run; body = {"variables": {...}} overrides
"""
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from navigator.browser import FrameStore
from navigator.runner import EventBus, Runtime, run_aop

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text())
AOP_PATH = ROOT / CONFIG.get("aop", "aop/wf_mortgage_rates.json")

try:
    from navigator.env import load_env
    load_env()
except ImportError:
    pass


FRAMES = FrameStore()
BUS = EventBus()
RUN_LOCK = threading.Lock()


def start_run(overrides: dict) -> bool:
    if not RUN_LOCK.acquire(blocking=False):
        return False
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        RUN_LOCK.release()
        raise RuntimeError("Set OPENROUTER_API_KEY")

    def worker():
        try:
            BUS.reset()
            aop = json.loads(AOP_PATH.read_text())
            cfg = {**aop.get("global_config", {}), **CONFIG}
            rt = Runtime(cfg, {"openrouter": key}, BUS, FRAMES)
            asyncio.run(run_aop(aop, overrides, rt))
        except Exception as e:  # surface setup failures in the UI
            BUS.emit("run_finished", {"status": "error", "reason": f"{type(e).__name__}: {e}"})
        finally:
            RUN_LOCK.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, (ROOT / "ui" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/aop":
            return self._send(200, AOP_PATH.read_bytes())
        if self.path == "/screen":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            seq = -1
            try:
                while True:
                    seq, jpeg = FRAMES.wait_next(seq, timeout=1.0)
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = BUS.subscribe()
            try:
                while True:
                    try:
                        ev = q.get(timeout=15)
                        self.wfile.write(f"data: {json.dumps(ev, default=str)}\n\n".encode())
                    except Exception:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, b'{"error":"not found"}')
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            started = start_run(body.get("variables", {}))
        except RuntimeError as e:
            return self._send(400, json.dumps({"error": str(e)}).encode())
        self._send(202 if started else 409, json.dumps({"started": started}).encode())


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else CONFIG.get("port", 8765)
    print(f"Jev browser navigator demo → http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
