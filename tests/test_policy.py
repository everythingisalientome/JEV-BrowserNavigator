"""Policy unit checks (pure functions). Run: python -m tests.test_policy"""
from navigator import policy

obs = {"elements": [{"index": "1", "label": "Submit Change", "role": "button"},
                    {"index": "2", "label": "Go", "role": "button"},
                    {"index": "3", "label": "Submit", "role": "button", "source": "llm"}]}


def d(op, p, t=None, tp=0.99, flags=None):
    return {"operation": {"value": op, "p": p}, "target": {"value": t, "p": tp} if t else None, "flags": flags or {}}


W, R = {"side_effects": "irreversible_on_submit"}, {"side_effects": "none"}
CASES = [
    (d("CLICK", .90, "1", .90), W, "HANDOFF"),   # submit-like below 0.95 bar
    (d("CLICK", .99, "1", .99), W, "ACT"),
    (d("CLICK", .99, "3", .99), W, "HANDOFF"),   # LLM-sourced irreversible target
    (d("CLICK", .90, "2", .90), W, "ACT"),       # "Go" is not submit-like by label
    (d("CLICK", .90, "1", .90), R, "ACT"),       # read-only node: gate off
    (d("CLICK", .60, "2"), R, "ESCALATE"),
    (d("CLICK", .30, "2"), R, "HANDOFF"),        # below hard floor
    (d("CLICK", .99, "2", flags={"unexpected_change": .7}), R, "HANDOFF"),
    (d("BLOCKED", .90), R, "ESCALATE"),
    (d("DONE", .90), R, "DONE_CHECK"),
]
for dec, node, want in CASES:
    got = policy.judge(dec, node, obs, {}, 0)["verdict"]
    assert got == want, (dec, node, got, want)
assert policy.judge(d("BLOCKED", .9), R, obs, {}, 3)["verdict"] == "BLOCKED"  # escalation budget spent
print(f"policy: {len(CASES) + 1} cases pass")
