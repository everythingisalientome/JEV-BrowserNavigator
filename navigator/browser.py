"""PlaywrightAdapter: the only module that touches the browser.

observe() -> element table (one evaluate call)
act()     -> executes one typed action on a node reference, then waits for the page to settle
Frames from a CDP screencast are pushed to a FrameStore for the demo's live view.
"""
import asyncio
import base64
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from playwright.async_api import async_playwright

SNAPSHOT_JS = (Path(__file__).parent / "snapshot.js").read_text(encoding="utf-8")


class StaleTarget(Exception):
    """The chosen node is gone or changed; observe again."""


class FrameStore:
    """Latest screencast JPEG, shared with the HTTP server thread."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpeg = None
        self.seq = 0

    def put(self, jpeg: bytes):
        with self.cond:
            self.jpeg, self.seq = jpeg, self.seq + 1
            self.cond.notify_all()

    def wait_next(self, last_seq: int, timeout: float = 1.0):
        with self.cond:
            if self.seq == last_seq:
                self.cond.wait(timeout)
            return self.seq, self.jpeg


def fingerprint(obs: dict) -> str:
    core = {
        "url": obs["url"],
        "text": obs["text"],
        "modal": obs["modal"],
        "els": [(e["role"], e["label"], e.get("value"), e.get("checked"), e.get("disabled")) for e in obs["elements"]],
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


class Browser:
    def __init__(self, cfg: dict, frames: FrameStore | None = None, on_event=None):
        self.cfg = cfg
        self.frames = frames
        self.on_event = on_event or (lambda *a, **k: None)
        self._pw = self.ctx = self.page = self._cdp = None

    # ---------- lifecycle ----------
    async def start(self, url: str):
        self._pw = await async_playwright().start()
        vp = self.cfg.get("viewport", {"width": 1280, "height": 800})
        self.ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=self.cfg.get("user_data_dir", "./.profiles/demo"),
            headless=self.cfg.get("headless", False),
            channel=self.cfg.get("channel") or None,
            viewport=vp,
            args=[f"--window-size={vp['width']},{vp['height'] + 120}"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        self.page.on("dialog", lambda d: asyncio.ensure_future(self._native_dialog(d)))
        await self._start_screencast()
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.settle()

    async def close(self):
        try:
            if self.ctx:
                await self.ctx.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def _native_dialog(self, dialog):
        # Native alert/confirm: never auto-accept. Dismiss and report so policy can decide.
        self.on_event("native_dialog", {"type": dialog.type, "message": dialog.message})
        await dialog.dismiss()

    async def _start_screencast(self):
        if not self.frames:
            return
        self._cdp = await self.ctx.new_cdp_session(self.page)
        # keep rendering even when the window is not focused/visible (jev-ultrafast does the same)
        await self._cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})

        def on_frame(p):
            self.frames.put(base64.b64decode(p["data"]))
            asyncio.ensure_future(self._cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))

        self._cdp.on("Page.screencastFrame", on_frame)
        await self._cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": 1280, "maxHeight": 800})

    # ---------- observe ----------
    async def observe(self) -> dict:
        obs = await self.page.evaluate(SNAPSHOT_JS)
        obs["fingerprint"] = fingerprint(obs)
        return obs

    async def settle(self, max_ms: int = 3000, quiet_ms: int = 300) -> dict:
        """Wait until two consecutive snapshots agree (async suggestions, re-renders), capped."""
        deadline = time.perf_counter() + max_ms / 1000
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=max_ms)
        except Exception:
            pass
        prev = await self.observe()
        while time.perf_counter() < deadline:
            await asyncio.sleep(quiet_ms / 1000)
            cur = await self.observe()
            if cur["fingerprint"] == prev["fingerprint"]:
                return cur
            prev = cur
        return prev

    # ---------- act ----------
    async def _handle(self, index: str, obs: dict):
        h = await self.page.evaluate_handle(
            "([i, fp]) => { const n = window.__jev && window.__jev.nodes[i - 1]; return (n && n.isConnected) ? n : null; }",
            [int(index), obs["fingerprint"]],
        )
        el = h.as_element()
        if el is None:
            raise StaleTarget(f"element [{index}] is no longer on the page")
        return el

    async def act(self, op: str, target: str | None, obs: dict, text: str | None = None) -> dict:
        """Execute one operation. Returns {'after': observation}. Raises StaleTarget."""
        if op in ("CLICK", "TYPE_TEXT", "SELECT"):
            idx = target.split(":")[0]
            el = await self._handle(idx, obs)
            elem = next(e for e in obs["elements"] if e["index"] == idx)
            if op == "CLICK":
                await el.click(timeout=5000)
            elif op == "TYPE_TEXT":
                if elem.get("autocomplete"):
                    # autocomplete widgets listen to keystrokes; do not blur (it closes the suggestion list)
                    await el.click(timeout=5000)
                    await el.fill("")
                    await el.type(text, delay=25)
                else:
                    await el.fill(text, timeout=5000)
                    await el.evaluate("n => n.blur()")  # legacy/formatted fields validate on blur
            elif op == "SELECT":
                opt = next(o for o in elem["options"] if o["index"] == target)
                await el.select_option(value=opt["value"], timeout=5000)
        elif op in ("SCROLL_DOWN", "SCROLL_UP"):
            await self.page.mouse.wheel(0, 600 if op == "SCROLL_DOWN" else -600)
        elif op == "WAIT":
            await asyncio.sleep(1.0)
        return {"after": await self.settle()}

    # ---------- escalation support ----------
    async def active_region_html(self, limit: int = 12000) -> str:
        return await self.page.evaluate(
            """(limit) => {
                const root = (window.__jev && window.__jev.modal) || document.body;
                const c = root.cloneNode(true);
                c.querySelectorAll('script,style,svg,noscript,link,meta').forEach(n => n.remove());
                return c.outerHTML.replace(/\\s+/g, ' ').slice(0, limit);
            }""",
            limit,
        )

    async def adopt_locator(self, locator: str) -> dict | None:
        """Validate an LLM-proposed Playwright locator: exactly one visible, enabled match.
        Returns an element-table row appended to __jev.nodes, or None."""
        try:
            loc = self.page.locator(locator)
            if await loc.count() != 1:
                return None
            if not await loc.is_visible() or not await loc.is_enabled():
                return None
            h = await loc.element_handle(timeout=2000)
            info = await h.evaluate(
                """n => { window.__jev.nodes.push(n); const r = n.getBoundingClientRect();
                          return { index: String(window.__jev.nodes.length),
                                   label: (n.innerText || n.getAttribute('aria-label') || n.value || '').trim().slice(0, 80),
                                   rect: { x: r.left, y: r.top, w: r.width, h: r.height } }; }"""
            )
            return {"index": info["index"], "role": "llm-candidate", "label": info["label"] or locator,
                    "section": "", "operations": ["CLICK"], "source": "llm", "locator": locator, "rect": info["rect"]}
        except Exception:
            return None
