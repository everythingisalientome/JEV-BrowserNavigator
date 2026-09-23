"""P0: one raw call to Jev on OpenRouter. Prints the exact response so we KNOW (not assume):
  - does a choice answer carry the full per-option distribution, or only value + probability?
  - is token usage returned (measured cost) or must we estimate?
  - does the noul question shape we send match what the endpoint expects?
Run: OPENROUTER_API_KEY=... python scripts/probe_jev.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from navigator.jev import JEV_MODEL, JEV_URL, http_post

body = {
    "model": JEV_MODEL,
    "state": {"page": {"url": "https://example.test/rates", "text": "Change rate inputs"},
              "elements": [{"index": "1", "role": "link", "label": "Check all rates"},
                           {"index": "2", "role": "button", "label": "Check rates opens dropdown"}]},
    "questions": {
        "operation": {"type": "choice", "criteria": {"CLICK": "Click an element.", "WAIT": "Wait.", "DONE": "Goal complete."},
                      "instructions": {"goal": "Open the Check rates dropdown."}},
        "click_target": {"type": "choice", "criteria": {"1": "[1] link \"Check all rates\"", "2": "[2] button \"Check rates opens dropdown\""},
                         "instructions": {"goal": "Open the Check rates dropdown."}},
        "unexpected_change": {"type": "noul", "criteria": "The page shows an error.", "instructions": {"previous_action": "none"}},
    },
}
res = http_post(JEV_URL, body, os.environ["OPENROUTER_API_KEY"])
print(json.dumps(res, indent=2))
a = res.get("answers", res)
print("\nfull distribution on choice:", "probabilities" in (a.get("operation") or {}))
print("usage returned:", bool(res.get("usage")), res.get("usage"))
