"""Offline end-to-end test. Real Chromium, real observer/executor/policy/runner, fixture page.
Jev and the escalation LLM are replaced by a scripted stand-in, so this proves the plumbing,
NOT Jev's accuracy. Run: python -m tests.test_offline"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from navigator import escalate, jev  # noqa: E402
from navigator.browser import FrameStore  # noqa: E402
from navigator.runner import EventBus, Runtime, run_aop  # noqa: E402

PLAN = [  # (operation, label substring, input name)
    ("CLICK", "Check rates opens dropdown", None),
    ("CLICK", "Go", None),
    ("CLICK", "Change rate inputs", None),
    ("TYPE_TEXT", "City, State", "city_state"),
    ("CLICK", "Charlotte, NC", None),
    ("TYPE_TEXT", "Home price", "home_price"),
    ("CLICK", "Done", None),
    ("DONE", None, None),          # end of node 1: county dialog is open
    ("CLICK", "Mecklenburg", None),
    ("CLICK", "Done", None),
    ("CLICK", "30-Year Fixed Rate", None),
    ("DONE", None, None),
]


class FakeJev:
    """Answers from the request's own element table, like Jev would, following PLAN."""

    def __init__(self, shape="full", low_conf_at=None):
        self.i, self.shape, self.low_conf_at, self.calls = 0, shape, low_conf_at, 0

    def choice(self, value, ids, p=0.97):
        if self.shape == "full":
            rest = [k for k in ids if k != value]
            dist = {value: p, **{k: (1 - p) / max(1, len(rest)) for k in rest}}
            return {"choice": value, "probabilities": dist, "confidence": p}
        return {"type": "choice", "value": value, "probability": p}

    def __call__(self, url, body, key, timeout=30.0):
        if "chat/completions" in url:  # escalation stand-in: points at the element Jev was unsure about
            return {"choices": [{"message": {"content": json.dumps({
                "diagnosis": "target ambiguous", "subgoal": "open the Check rates dropdown",
                "candidates": [{"locator": "role=button[name='Check rates opens dropdown']", "why": "dropdown"}],
                "handoff": False})}}], "usage": {"total_tokens": 900}}
        self.calls += 1
        q, els = body["questions"], body["state"]["elements"]
        op, label, inp = PLAN[min(self.i, len(PLAN) - 1)]
        ans = {}
        target = None
        if op != "DONE":
            cands = q.get(op.lower() + "_target", {}).get("criteria", {})
            target = next((k for k, v in cands.items() if f'"{label}"' in v or (label in v and op != "CLICK")), None)
            if target is None:  # expected element not on screen yet (e.g. rates reloading)
                op = "WAIT"
        page = json.dumps(body["state"]["page"])
        if op == "DONE":
            final = self.i >= len(PLAN) - 1
            if final and "Monthly payment" not in page:
                op = "WAIT"
            elif not final and "Select a County" not in page:
                op = "WAIT"
            else:
                self.i += 1
        p = 0.45 if self.low_conf_at is not None and self.calls == self.low_conf_at else 0.97  # below the read-only 0.50 bar (D22)
        ans["operation"] = self.choice(op, q["operation"]["criteria"], p)
        if target:
            ans[op.lower() + "_target"] = self.choice(target, q[op.lower() + "_target"]["criteria"])
            self.i += 1 if not (self.low_conf_at is not None and self.calls == self.low_conf_at) else 0
        if op == "TYPE_TEXT":
            ans["type_text_value"] = self.choice(inp, q["type_text_value"]["criteria"])
        for f in jev.VERIFY_QUESTIONS:
            if f in q:
                ans[f] = {"type": "noul", "noul": 0.9 if f in ("step_completed", "expected_state_reached") else 0.03}
        return {"answers": ans, "usage": {"prompt_tokens": len(json.dumps(body)) // 4}}


async def run_case(shape, low_conf_at=None):
    fake = FakeJev(shape, low_conf_at)
    jev.http_post = fake
    escalate.http_post = fake
    aop = json.loads((ROOT / "aop" / "wf_mortgage_rates.json").read_text())
    out = Path(tempfile.mkdtemp()) / "rates.xlsx"
    bus, frames = EventBus(), FrameStore()
    cfg = {**aop["global_config"], "browser": {"headless": True, "user_data_dir": tempfile.mkdtemp()}}
    rt = Runtime(cfg, {"openrouter": "test"}, bus, frames)
    fixture = (ROOT / "tests" / "fixtures" / "rates.html").resolve().as_uri()
    res = await run_aop(aop, {"start_url": fixture, "export_path": str(out)}, rt)
    kinds = [e["type"] for e in bus.history]
    return res, rt.metrics.snapshot(), out, frames.seq, kinds, bus.history


def main():
    ok = True
    for shape, low in (("full", None), ("value_only", None), ("full", 1)):
        res, m, out, nframes, kinds, hist = asyncio.run(run_case(shape, low))
        acts = [e for e in hist if e["type"] == "action"]
        print(f"\n== answer shape={shape} low_conf_at={low}: {res['status']} ({res['reason']})")
        for a in acts:
            print(f"  {a['step']:>2} {'ok ' if a['ok'] else 'BAD'} {a['describe'][:78]:<78} | {a['readback']}")
        esc = [e for e in hist if e["type"] == "escalation"]
        if esc:
            print("  escalation:", {k: esc[0].get(k) for k in ('reason', 'subgoal', 'adopted')})
        outs = next((e for e in reversed(hist) if e["type"] == "outputs"), {}).get("outputs", {})
        print("  outputs:", json.dumps(outs)[:300])
        print(f"  excel exists={out.exists()}  screencast frames={nframes}  metrics={m}")
        ok &= res["status"] == "success" and out.exists() and nframes > 0 and len(outs.get("rate_details", [])) >= 6
        if low:
            ok &= bool(esc)
    print("\nALL PASSED" if ok else "\nFAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()