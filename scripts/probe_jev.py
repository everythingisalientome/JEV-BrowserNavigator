"""P0: one raw call to Jev on OpenRouter, built by the SAME build_request() the agent uses each step.
The page state below is an example (no browser); the question shapes are the real ones.
Prints the raw response, then checks:
  - does each choice answer carry the full per-option distribution, or only value + probability?
  - is token usage returned (measured cost) or must we estimate?
  - are all heads answered: operation, click/type_text/select targets, type_text_value, 4 noul flags?
Run: python scripts/probe_jev.py   (reads OPENROUTER_API_KEY from the environment or .env)"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from navigator.env import load_env  # optional .env support
    load_env()
except ImportError:
    pass
from navigator import jev  # noqa: E402

GOAL = ("Go to mortgage rates, change the rate inputs to Charlotte, NC with home price 300000 "
        "and county Mecklenburg, then open the details for 30-Year Fixed Rate.")
RULES = ["City, State is an autocomplete: type it, then click the suggestion that matches Charlotte, NC exactly."]
INPUTS = {"city_state": "Charlotte, NC", "home_price": "300000", "county": "Mecklenburg"}

# Example observation, as snapshot.js would return it mid-flow with the "Change rate inputs" dialog open.
OBS = {
    "url": "https://www.wellsfargo.com/mortgage/rates/",
    "title": "Current mortgage rates | Wells Fargo",
    "modal": "Change rate inputs",
    "text": "Change rate inputs City, State Austin, TX Home price $400,000 Down payment amount $80,000 Cancel Done",
    "scroll": {"y": 0, "max": 900},
    "elements": [
        {"index": "1", "role": "button", "label": "(unlabeled button)", "section": "Change rate inputs", "operations": ["CLICK"]},
        {"index": "2", "role": "textbox", "label": "City, State", "section": "Change rate inputs", "value": "Austin, TX",
         "autocomplete": True, "operations": ["TYPE_TEXT"]},
        {"index": "3", "role": "textbox", "label": "Home price", "section": "Change rate inputs", "value": "$400,000", "operations": ["TYPE_TEXT"]},
        {"index": "4", "role": "textbox", "label": "Down payment amount", "section": "Change rate inputs", "value": "$80,000", "operations": ["TYPE_TEXT"]},
        {"index": "5", "role": "combobox", "label": "Loan purpose", "section": "Change rate inputs", "value": "Home Purchase",
         "options": [{"index": "5:1", "label": "Home Purchase", "value": "p"}, {"index": "5:2", "label": "Refinance", "value": "r"}],
         "operations": ["SELECT"]},
        {"index": "6", "role": "button", "label": "Done", "section": "Change rate inputs", "operations": ["CLICK"]},
        {"index": "7", "role": "button", "label": "Cancel", "section": "Change rate inputs", "operations": ["CLICK"]},
    ],
}
HISTORY = [{"step": 3, "action": 'CLICK [3] link "Change rate inputs"', "readback": "page changed", "page_changed": True}]
PREV = {"describe": 'CLICK [3] link "Change rate inputs"'}

body, ops, heads = jev.build_request(OBS, GOAL, RULES, INPUTS, HISTORY, PREV)
print("=== REQUEST QUESTIONS (built by navigator/jev.py) ===")
print(json.dumps(body["questions"], indent=2)[:2500], "…\n")

key = os.environ.get("OPENROUTER_API_KEY")
if not key:
    sys.exit("Set OPENROUTER_API_KEY (environment or .env)")
res = jev.http_post(jev.JEV_URL, body, key)
print("=== RAW RESPONSE ===")
print(json.dumps(res, indent=2))

answers = res.get("answers", res)
print("\n=== SHAPE CHECKS ===")
checks = {"operation": ops, **{op.lower() + "_target": cands for op, cands in heads.items()}, "type_text_value": INPUTS}
for name, ids in checks.items():
    a = answers.get(name)
    if a is None:
        print(f"{name:24s} MISSING")
        continue
    try:
        c = jev.parse_choice(a, ids)
        print(f"{name:24s} value={c['value']!r:14s} p={c['p']:.3f}  full_distribution={'probabilities' in a}  keys={sorted(a)}")
    except Exception as e:
        print(f"{name:24s} UNPARSEABLE ({e}); raw={a}")
for name in jev.VERIFY_QUESTIONS:
    a = answers.get(name)
    print(f"{name:24s} p_true={jev.parse_noul(a)}  raw={a}")
usage = res.get("usage")
print(f"\nusage returned: {bool(usage)}  {usage}")
print("\nExpected on this state: operation=TYPE_TEXT, type_text_target='2', type_text_value='city_state'.")
