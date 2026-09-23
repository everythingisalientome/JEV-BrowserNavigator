"""Jev reports, code decides. Pure functions; no I/O."""
import re

DEFAULTS = {
    "min_operation_p": 0.80,
    "min_target_p": 0.80,
    "hard_floor_p": 0.40,          # below this: hand off, don't even escalate
    "irreversible_min_p": 0.95,
    "flag_halt_p": 0.50,           # unexpected_change / human_review_required
    "max_escalations": 3,
    "max_steps": 25,
    "no_progress_steps": 3,
}

# Declared per operation in code, never asked of the model.
RETRY_SAFE = {"TYPE_TEXT": True, "SELECT": True, "SCROLL_DOWN": True, "SCROLL_UP": True, "WAIT": True, "CLICK": False}

SUBMIT_LIKE = re.compile(r"\b(submit|save|confirm|delete|remove|close account|pay|transfer|apply|sign|approve|place order)\b", re.I)


def irreversible(node: dict, element: dict | None) -> bool:
    if node.get("side_effects", "irreversible_on_submit") == "none" or not element:
        return False
    return bool(SUBMIT_LIKE.search(element.get("label", "")))


def judge(decision: dict, node: dict, obs: dict, cfg: dict, escalations_used: int) -> dict:
    """-> {'verdict': ACT|ESCALATE|HANDOFF|BLOCKED|DONE_CHECK, 'reason': str}"""
    c = {**DEFAULTS, **(cfg or {})}
    flags = decision.get("flags") or {}
    for f in ("unexpected_change", "human_review_required"):
        if (flags.get(f) or 0) >= c["flag_halt_p"]:
            return {"verdict": "HANDOFF", "reason": f"{f} p={flags[f]:.2f} on the previous step"}

    op, tgt = decision["operation"], decision.get("target")
    can_escalate = escalations_used < c["max_escalations"]
    if op["value"] == "BLOCKED":
        return {"verdict": "ESCALATE" if can_escalate else "BLOCKED", "reason": "Jev reported BLOCKED"}
    if op["value"] == "DONE":
        return {"verdict": "DONE_CHECK", "reason": "Jev reported DONE; running acceptance checks"}

    weakest = min([op["p"]] + ([tgt["p"]] if tgt else []))
    if weakest < c["hard_floor_p"]:
        return {"verdict": "HANDOFF", "reason": f"confidence {weakest:.2f} below hard floor"}
    if op["p"] < c["min_operation_p"] or (tgt and tgt["p"] < c["min_target_p"]):
        why = f"low confidence (operation {op['p']:.2f}" + (f", target {tgt['p']:.2f}" if tgt else "") + ")"
        return {"verdict": "ESCALATE" if can_escalate else "HANDOFF", "reason": why}

    element = None
    if tgt:
        idx = tgt["value"].split(":")[0]
        element = next((e for e in obs["elements"] if e["index"] == idx), None)
    if irreversible(node, element):
        if element and element.get("source") == "llm":
            return {"verdict": "HANDOFF", "reason": "irreversible target was proposed by the escalation LLM"}
        if min(op["p"], tgt["p"]) < c["irreversible_min_p"]:
            return {"verdict": "HANDOFF", "reason": "irreversible action below the high-confidence bar"}
    return {"verdict": "ACT", "reason": "above thresholds"}
