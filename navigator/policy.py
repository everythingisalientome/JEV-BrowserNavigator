"""Jev reports, code decides. Pure functions; no I/O."""
import re

DEFAULTS = {
    "min_operation_p": 0.80,
    "min_operation_p_read_only": 0.50,   # D22: on side_effects:"none" nodes a wrong reversible pick costs one step; readback catches it
    "min_target_p": 0.80,
    "min_target_p_read_only": 0.50,      # D25: same reasoning as min_operation_p_read_only
    "hard_floor_p": 0.40,          # below this: hand off, don't even escalate
    "irreversible_min_p": 0.95,
    "flag_halt_p": 0.75,           # unexpected_change when code readback passed (D25)
    "flag_halt_p_readback_failed": 0.50,  # unexpected_change when code readback also failed (model + code agree)
    "human_review_halt_p": 0.75,   # human_review_required (D21: probe showed 0.59 on a benign state; recalibrate from real runs)
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
    uc_key = "flag_halt_p_readback_failed" if decision.get("prev_ok") is False else "flag_halt_p"
    for f, key in (("unexpected_change", uc_key), ("human_review_required", "human_review_halt_p")):
        if (flags.get(f) or 0) >= c[key]:
            return {"verdict": "HANDOFF", "reason": f"{f} p={flags[f]:.2f} ≥ {c[key]:.2f} on the previous step"}

    op, tgt = decision["operation"], decision.get("target")
    can_escalate = escalations_used < c["max_escalations"]
    if op["value"] == "BLOCKED":
        return {"verdict": "ESCALATE" if can_escalate else "BLOCKED", "reason": "Jev reported BLOCKED"}
    if op["value"] == "DONE":
        return {"verdict": "DONE_CHECK", "reason": "Jev reported DONE; running acceptance checks"}

    weakest = min([op["p"]] + ([tgt["p"]] if tgt else []))
    if weakest < c["hard_floor_p"]:
        return {"verdict": "HANDOFF", "reason": f"confidence {weakest:.2f} below hard floor"}
    read_only = node.get("side_effects") == "none"
    min_op = c["min_operation_p_read_only"] if read_only else c["min_operation_p"]
    min_tgt = c["min_target_p_read_only"] if read_only else c["min_target_p"]
    if op["p"] < min_op or (tgt and tgt["p"] < min_tgt):
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