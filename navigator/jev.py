"""Jev via OpenRouter. Builds typed questions from the element table; parses typed answers.

The model reports; it never decides policy. Everything here is pure data in / data out.
"""
import asyncio
import json
import math
import os
import time
import urllib.error
import urllib.request

JEV_URL = os.environ.get("JEV_URL", "https://openrouter.ai/api/alpha/decisions")
JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
JEV_PRICE_PER_M_INPUT = 0.042  # USD per 1M input tokens; output is free

OPERATION_TEXT = {
    "CLICK": "Click an element: button, link, menu option, suggestion, radio or checkbox.",
    "TYPE_TEXT": "Enter text into an editable field. The value comes from the task inputs.",
    "SELECT": "Choose an option in a dropdown.",
    "SCROLL_DOWN": "Scroll down to reveal more of the page.",
    "SCROLL_UP": "Scroll up.",
    "WAIT": "Wait for the page to finish loading or updating.",
    "DONE": "Every part of the goal is visibly complete on the page.",
    "BLOCKED": "No available operation can make progress.",
}

RULES = [
    "Choose the single next operation that makes progress toward the goal.",
    "Use only elements from the table. Disabled elements (no operations) cannot be used yet.",
    "Prefer exact label matches over similar-looking items.",
]

VERIFY_QUESTIONS = {  # asked as noul questions: the answer is P(true)
    "step_completed": "Did the previous action take effect on the page?",
    "expected_state_reached": "Given the goal, is the page now in the state the previous action was meant to produce (the intended dialog, field value, or page is showing)?",
    "unexpected_change": "Did something change that the previous action should not have caused (an error, a wrong page, a different record, lost input)?",
    "human_review_required": "Does the page show an error message, a login or verification challenge, a blocked or failed action, or a different customer or record than the goal intends, so that a person must look before the task continues?",
}


class JevError(RuntimeError):
    pass


def http_post(url: str, body: dict, key: str, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 529) and attempt < 2:
                time.sleep(0.5 * 2 ** attempt)
                continue
            raise JevError(f"HTTP {e.code} from model provider; no action executed: {e.read()[:3000].decode(errors='replace')}") from None
        except urllib.error.URLError as e:
            raise JevError(f"Model connection failed; no action executed: {e.reason}") from None
    raise JevError("Model unavailable; no action executed.")


# ---------------- question building ----------------
def available_operations(obs: dict, has_inputs: bool) -> dict:
    ops = {}
    kinds = {op for e in obs["elements"] for op in e.get("operations", [])}
    for op in ("CLICK", "TYPE_TEXT", "SELECT"):
        if op in kinds and (op != "TYPE_TEXT" or has_inputs):
            ops[op] = OPERATION_TEXT[op]
    if not obs.get("modal"):
        if obs["scroll"]["y"] < obs["scroll"]["max"]:
            ops["SCROLL_DOWN"] = OPERATION_TEXT["SCROLL_DOWN"]
        if obs["scroll"]["y"] > 0:
            ops["SCROLL_UP"] = OPERATION_TEXT["SCROLL_UP"]
    ops["WAIT"] = OPERATION_TEXT["WAIT"]
    ops["DONE"] = OPERATION_TEXT["DONE"]
    ops["BLOCKED"] = OPERATION_TEXT["BLOCKED"]
    return ops


def target_candidates(obs: dict) -> dict:
    """{operation: {target_id: one-line description}} — each operation has only its valid targets.
    Criteria values are plain strings (the shape the working email demo uses)."""
    heads = {}
    for e in obs["elements"]:
        parts = [f"[{e['index']}] {e['role']} \"{e['label']}\""]
        if e.get("section"):
            parts.append(f"in {e['section']}")
        for k in ("value", "checked", "selected", "expanded"):
            if k in e and e[k] not in ("", None):
                parts.append(f"{k}={e[k]!r}")
        if e.get("in_viewport") is False:
            parts.append("(off-screen)")
        base = " ".join(parts)
        for op in e.get("operations", []):
            if op == "SELECT":  # D22: never offer the already-selected option (a no-op)
                for o in e["options"]:
                    if o["label"] != e.get("value"):
                        heads.setdefault(op, {})[o["index"]] = f"{base} → option \"{o['label']}\""
            else:
                heads.setdefault(op, {})[e["index"]] = base
    return heads


def _instructions(goal: str, rules: list, extra: str = "") -> str:
    text = f"Goal: {goal}\nRules: " + " ".join(f"({i + 1}) {r}" for i, r in enumerate(RULES + list(rules or [])))
    return text + (f"\n{extra}" if extra else "")


def build_request(obs: dict, goal: str, rules: list, inputs: dict, history: list, prev: dict | None) -> tuple[dict, dict, dict]:
    ops = available_operations(obs, bool(inputs))
    heads = {k: v for k, v in target_candidates(obs).items() if k in ops}
    questions = {"operation": {"type": "choice", "criteria": ops,
                               "instructions": _instructions(goal, rules, "Which operation comes next?")}}
    for op, cands in heads.items():
        questions[op.lower() + "_target"] = {
            "type": "choice", "criteria": cands,
            "instructions": _instructions(goal, rules, f"If the operation is {op}, which element is the target?"),
        }
    if "TYPE_TEXT" in ops and inputs:
        questions["type_text_value"] = {
            "type": "choice",
            "criteria": {name: f"{name} = {value!r}" for name, value in inputs.items()},
            "instructions": _instructions(goal, rules, "Which task input belongs in the text field being filled?"),
        }
    if prev:  # verification of the PREVIOUS step, folded into this request (noul = P(true), no criteria)
        ctx = (f"Previous action: {prev['describe']}. Code readback after it: {prev.get('readback', 'n/a')}"
               f"{'; the URL changed to ' + prev['url_after'] if prev.get('url_after') and prev.get('url_after') != prev.get('url_before') else ''}. "
               "Navigating to a new page, opening a dialog or menu, and fields recalculating are normal effects of clicking links and buttons. "
               f"Overall goal: {goal}. ")
        for name, text in VERIFY_QUESTIONS.items():
            questions[name] = {"type": "noul", "instructions": ctx + text}
    state = {
        "page": {"url": obs["url"], "title": obs["title"], "open_dialog": obs.get("modal"), "text": obs["text"]},
        "elements": [{k: v for k, v in e.items() if k != "options"} | ({"options": [o["label"] for o in e["options"]]} if "options" in e else {})
                     for e in obs["elements"]],
        "recent_actions": history[-10:],
    }
    return {"model": JEV_MODEL, "state": state, "questions": questions}, ops, heads


# ---------------- answer parsing (tolerant of both documented shapes) ----------------
def parse_choice(ans: dict, ids) -> dict:
    """Normalise to {value, p, dist}. Accepts {value, probability} or {choice, probabilities, confidence}."""
    ids = set(ids)
    if not isinstance(ans, dict):
        raise JevError("missing choice answer; no action executed")
    if "probabilities" in ans:
        dist = {k: float(v) for k, v in ans["probabilities"].items()}
        value = ans.get("choice", ans.get("value"))
        if value is None and dist:
            value = max(dist, key=dist.get)
    else:
        value = ans.get("value", ans.get("choice"))
        p = ans.get("probability", ans.get("confidence"))
        dist = {value: float(p)} if value is not None and p is not None else {}
    if value not in ids:
        raise JevError(f"choice {value!r} not among offered ids; no action executed")
    p = dist.get(value)
    if p is None or not (math.isfinite(p) and 0 <= p <= 1):
        raise JevError("invalid probability; no action executed")
    return {"value": value, "p": p, "dist": dist}


def parse_noul(ans) -> float | None:
    if isinstance(ans, dict):
        v = ans.get("noul", ans.get("probability"))
        return float(v) if v is not None else None
    return None


def input_tokens(result: dict, body: dict) -> tuple[int, bool]:
    """(tokens, measured). Falls back to a chars/4 estimate if the provider sends no usage."""
    u = result.get("usage") or {}
    for k in ("input_tokens", "prompt_tokens"):
        if isinstance(u.get(k), (int, float)):
            return int(u[k]), True
    return len(json.dumps(body)) // 4, False


async def decide(obs, goal, rules, inputs, history, prev, key: str) -> dict:
    body, ops, heads = build_request(obs, goal, rules, inputs, history, prev)
    t0 = time.perf_counter()
    result = await asyncio.to_thread(http_post, JEV_URL, body, key)
    latency_ms = round((time.perf_counter() - t0) * 1000)
    answers = result.get("answers", result)
    op = parse_choice(answers.get("operation"), ops)
    target = value = None
    if op["value"] in heads:
        target = parse_choice(answers.get(op["value"].lower() + "_target"), heads[op["value"]])
    if op["value"] == "TYPE_TEXT":
        value = parse_choice(answers.get("type_text_value"), inputs)
    flags = {name: parse_noul(answers.get(name)) for name in VERIFY_QUESTIONS} if prev else {}
    tokens, measured = input_tokens(result, body)
    return {"operation": op, "target": target, "value": value, "flags": flags,
            "latency_ms": latency_ms, "input_tokens": tokens, "tokens_measured": measured,
            "request": body, "raw": result}