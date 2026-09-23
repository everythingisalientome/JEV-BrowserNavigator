"""The UI Agent: executes one AOP ui_task node. Returns plain data (LangGraph-node compatible)."""
import time

from . import checks, escalate, jev, policy
from .browser import StaleTarget, digits


class Metrics:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.jev_requests = 0
        self.latencies = []
        self.input_tokens = 0
        self.tokens_measured = True
        self.escalations = 0
        self.esc_tokens = 0
        self.esc_cost_known = True
        self.steps = 0
        self.verified = 0
        self.buckets = {"decide": 0.0, "act": 0.0, "wait": 0.0, "escalate": 0.0}

    def snapshot(self) -> dict:
        lat = sorted(self.latencies)
        med = lat[len(lat) // 2] if lat else None
        return {"elapsed_s": round(time.perf_counter() - self.t0, 2), "jev_requests": self.jev_requests,
                "median_latency_ms": med, "input_tokens": self.input_tokens, "tokens_measured": self.tokens_measured,
                "jev_cost_usd": round(self.input_tokens * jev.JEV_PRICE_PER_M_INPUT / 1e6, 6),
                "escalations": self.escalations, "escalation_tokens": self.esc_tokens,
                "steps": self.steps, "verified": self.verified,
                "time_buckets_s": {k: round(v, 2) for k, v in self.buckets.items()}}


def describe(op, target, obs, value_name=None, text=None) -> str:
    if not target:
        return op
    idx = target.split(":")[0]
    e = next((x for x in obs["elements"] if x["index"] == idx), {})
    s = f"{op} [{target}] {e.get('role', '')} \"{e.get('label', '')}\""
    if op == "SELECT":
        opt = next((o["label"] for o in e.get("options", []) if o["index"] == target), "")
        s += f" → {opt}"
    if op == "TYPE_TEXT":
        s += f" ← {value_name} ({text!r})"
    return s


def readback(op, target, before, after, text=None) -> tuple[bool, str]:
    """Code-level verification from the post-action observation."""
    if op in ("WAIT", "SCROLL_DOWN", "SCROLL_UP"):
        return True, "no readback needed"
    idx = target.split(":")[0]
    b = next((e for e in before["elements"] if e["index"] == idx), {})
    same = [e for e in after["elements"] if e["label"] == b.get("label") and e.get("section") == b.get("section")]
    if op == "TYPE_TEXT":
        if not same:
            return True, "field re-rendered; value not re-readable (form advanced)"
        got = same[0].get("value", "")
        numeric = bool(digits(text)) and not any(ch.isalpha() for ch in text)
        if numeric:  # formatted fields: "$300,000" reads back for "300000"
            ok = digits(got) == digits(text)
        else:        # autocomplete may append/trim: accept containment either way
            ok = bool(got) and (text.lower() in got.lower() or got.lower() in text.lower())
        return ok, f"value = {got!r}"
    if op == "SELECT":
        opt = next((o["label"] for o in b.get("options", []) if o["index"] == target), None)
        got = same[0].get("value") if same else None
        return got == opt, f"selected = {got!r}"
    if op == "CLICK":
        changed = after["fingerprint"] != before["fingerprint"] or after["url"] != before["url"]
        if same and "checked" in b:
            return same[0].get("checked") != b.get("checked") or changed, f"checked = {same[0].get('checked')}"
        return changed, "page changed" if changed else "no visible effect"
    return False, "unknown operation"


async def run_ui_task(node: dict, variables: dict, rt) -> dict:
    """rt: runtime with .browser, .emit(type, data), .keys, .cfg, .metrics"""
    b, m, cfg = rt.browser, rt.metrics, {**policy.DEFAULTS, **rt.cfg.get("policy", {})}
    goal = node["goal"]
    rules = node.get("rules", [])
    inputs = {k: variables[k] for k in node.get("inputs", [])}
    esc_model = rt.cfg.get("escalation", {}).get("model", "openai/gpt-4o-mini")
    history, prev, subgoal = [], None, None
    escalations_used = done_rejections = 0
    extra_rows = []

    if node.get("start_url") and b.page.url.rstrip("/") != node["start_url"].rstrip("/"):
        await b.page.goto(node["start_url"], wait_until="domcontentloaded")
    obs = await b.settle()
    rt.emit("observation", {"obs": obs})

    for step in range(1, cfg["max_steps"] + 1):
        obs_for_jev = {**obs, "elements": obs["elements"] + extra_rows}
        eff_goal = goal + (f"\nCurrent subgoal: {subgoal}" if subgoal else "")
        t = time.perf_counter()
        try:
            d = await jev.decide(obs_for_jev, eff_goal, rules, inputs, history, prev, rt.keys["openrouter"])
        except (jev.JevError, KeyError, ValueError) as e:
            m.buckets["decide"] += time.perf_counter() - t
            rt.emit("error", {"step": step, "message": str(e)})
            return {"status": "BLOCKED", "reason": str(e), "outputs": {}}
        m.buckets["decide"] += time.perf_counter() - t
        m.jev_requests += 1
        m.latencies.append(d["latency_ms"])
        m.input_tokens += d["input_tokens"]
        m.tokens_measured &= d["tokens_measured"]

        verdict = policy.judge(d, node, obs_for_jev, cfg, escalations_used)
        rt.emit("jev_request", {"step": step, "request": d["request"], "raw_answers": d["raw"].get("answers", d["raw"])})
        rt.emit("decision", {"step": step, "operation": d["operation"], "target": d["target"], "value": d["value"],
                             "flags": d["flags"], "verifying": prev and prev["describe"], "latency_ms": d["latency_ms"],
                             "input_tokens": d["input_tokens"], "verdict": verdict, "metrics": m.snapshot()})

        if verdict["verdict"] in ("HANDOFF", "BLOCKED"):
            return {"status": verdict["verdict"], "reason": verdict["reason"], "outputs": {}}

        if verdict["verdict"] == "ESCALATE":
            escalations_used += 1
            m.escalations += 1
            t = time.perf_counter()
            try:
                region = await b.active_region_html()
                out, meta = await escalate.direction(esc_model, rt.keys["openrouter"], eff_goal, rules, obs_for_jev,
                                                     history, verdict["reason"], region)
            except Exception as e:  # escalation failure never causes an action
                m.buckets["escalate"] += time.perf_counter() - t
                rt.emit("escalation", {"step": step, "error": str(e)})
                return {"status": "HANDOFF", "reason": f"escalation failed: {e}", "outputs": {}}
            m.buckets["escalate"] += time.perf_counter() - t
            m.esc_tokens += int((meta.get("usage") or {}).get("total_tokens") or 0)
            adopted = []
            for c in out.get("candidates", []):
                row = await b.adopt_locator(c["locator"])
                if row:
                    adopted.append(row)
            extra_rows = adopted
            subgoal = out.get("subgoal") or subgoal
            rt.emit("escalation", {"step": step, "reason": verdict["reason"], "diagnosis": out.get("diagnosis"),
                                   "subgoal": subgoal, "proposed": [c["locator"] for c in out.get("candidates", [])],
                                   "adopted": [r["locator"] for r in adopted], "latency_ms": meta["latency_ms"],
                                   "metrics": m.snapshot()})
            if out.get("handoff"):
                return {"status": "HANDOFF", "reason": out.get("diagnosis") or "escalation requested handoff", "outputs": {}}
            prev = None
            continue

        if verdict["verdict"] == "DONE_CHECK":
            results = []
            for c in node.get("acceptance", []):
                ok, detail = await checks.run_check(b.page, b.observe, c)
                results.append({"check": c["check"], "ok": ok, "detail": detail})
            rt.emit("acceptance", {"step": step, "results": results})
            if all(r["ok"] for r in results):
                outputs, problems = {}, []
                for name, spec in node.get("outputs", {}).items():
                    val, status = await checks.capture(b.page, spec)
                    if spec.get("from") == "dialog_fields" and val and val["missing"]:
                        kept, _ = await escalate.extract_fields(esc_model, rt.keys["openrouter"], val["text"] or "")
                        m.escalations += 1
                        val["rows"] = val["rows"] + [{"field": f["field"], "value": f["value"], "note": "via LLM (verbatim-checked)"}
                                                     for f in kept if f["field"] not in {r["field"] for r in val["rows"]}]
                        val["missing"] = [r for r in spec.get("required", []) if r not in {x["field"] for x in val["rows"]}]
                        status = "ok" if not val["missing"] else f"missing {val['missing']}"
                    outputs[name] = val["rows"] if isinstance(val, dict) and "rows" in val else val
                    if status != "ok":
                        problems.append(f"{name}: {status}")
                rt.emit("outputs", {"outputs": {k: v for k, v in outputs.items()}, "problems": problems})
                if problems:
                    return {"status": "HANDOFF", "reason": "; ".join(problems), "outputs": outputs}
                return {"status": "DONE", "reason": "acceptance passed", "outputs": outputs}
            done_rejections += 1
            if done_rejections >= 2:
                return {"status": "HANDOFF", "reason": "DONE claimed twice but acceptance failed", "outputs": {}}
            history.append({"action": "DONE rejected by acceptance checks", "page_changed": False})
            prev = None
            continue

        # ---- ACT ----
        op = d["operation"]["value"]
        target = d["target"]["value"] if d["target"] else None
        value_name = d["value"]["value"] if d["value"] else None
        text = str(inputs[value_name]) if value_name else None
        desc = describe(op, target, obs_for_jev, value_name, text)
        tgt_el = next((e for e in obs_for_jev["elements"] if target and e["index"] == target.split(":")[0]), None)
        if policy.irreversible(node, tgt_el):  # code-checkable rules run before any Submit-like click
            for g in node.get("guards", {}).get("before_irreversible", []):
                ok_g, detail_g = await checks.run_check(b.page, b.observe, g)
                rt.emit("acceptance", {"step": step, "results": [{"check": "guard " + g["check"], "ok": ok_g, "detail": detail_g}]})
                if not ok_g:
                    return {"status": "HANDOFF", "reason": f"guard failed before irreversible action: {detail_g}", "outputs": {}}
        attempts = 2 if policy.RETRY_SAFE.get(op) else 1
        t = time.perf_counter()
        ok, detail, after, stale = False, "", obs, False
        for attempt in range(attempts):
            try:
                res = await b.act(op, target, obs_for_jev, text)
                after = res["after"]
            except StaleTarget as e:
                ok, detail, after, stale = False, str(e), await b.settle(), True
                break
            except Exception as e:
                ok, detail, after = False, f"{type(e).__name__}: {str(e)[:160]}", await b.settle()
                if not policy.RETRY_SAFE.get(op):
                    break
                continue
            ok, detail = readback(op, target, obs_for_jev, after, text)
            if ok:
                break
        spent = time.perf_counter() - t
        m.buckets["wait" if op == "WAIT" else "act"] += spent
        m.steps += 1
        m.verified += int(ok)
        extra_rows = []
        changed = after["fingerprint"] != obs["fingerprint"]
        history.append({"step": step, "action": desc, "readback": detail, "page_changed": changed})
        rt.emit("action", {"step": step, "describe": desc, "ok": ok, "readback": detail, "retry_safe": policy.RETRY_SAFE.get(op),
                           "ms": round(spent * 1000), "metrics": m.snapshot()})
        rt.emit("observation", {"obs": after})
        if stale:  # page re-rendered between decision and action: not a failure, decide again
            prev, obs = None, after
            continue
        if not ok and op != "CLICK":  # safe ops were already retried once
            return {"status": "HANDOFF", "reason": f"readback failed: {detail}", "outputs": {}}
        recent = history[-cfg["no_progress_steps"]:]
        if len(recent) == cfg["no_progress_steps"] and all(not h.get("page_changed") and "WAIT" not in h.get("action", "") for h in recent):
            return {"status": "BLOCKED", "reason": "no progress for 3 steps", "outputs": {}}
        prev = {"describe": desc}
        obs = after
    return {"status": "BLOCKED", "reason": f"step budget ({cfg['max_steps']}) exhausted", "outputs": {}}
