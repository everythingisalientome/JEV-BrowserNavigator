# Jev browser navigator — demo

An AOP (workflow JSON) runs against a real website. Each UI step: observe the page as a numbered
element table → Jev picks an operation and a target with probabilities → code applies policy →
Playwright acts → code reads the result back. gpt-4o-mini is called only when Jev is stuck, and
only for direction; Jev still makes the pick.

```
server.py            stdlib web server: demo UI, live screencast (/screen), events (/events), POST /run
config.json          port, AOP path, browser profile/headless/channel
aop/                 AOP JSON (what to do) — wf_mortgage_rates.json
navigator/
  snapshot.js        observer: one DOM read → element table (open shadow roots, modal scoping, labels)
  browser.py         PlaywrightAdapter: persistent-profile launch, observe, act, settle, screencast
  jev.py             question builder, OpenRouter call, answer parsing, token usage
  policy.py          thresholds, hard rules, retry-safety table (code decides)
  agent.py           UI Agent loop for one ui_task node (LangGraph-node compatible function)
  checks.py          acceptance checks and output capture (deterministic)
  escalate.py        gpt-4o-mini: subgoal + validated locators; verbatim-checked extraction fallback
  runner.py          AOP graph runner (ui_task, data_task, decision, end) + event bus
ui/index.html        the demo page (live browser left, steps centre, Jev metrics right)
scripts/probe_jev.py P0: one raw Jev call to confirm the response shape
tests/               offline tests (fixture page + scripted stand-in for Jev)
docs/DISCOVERY_PROMPT.md  prompt for walking a new app with Claude in Chrome and producing an AOP
```

## Setup (Windows or macOS, Python 3.10+)

```bash
python -m venv .venv && .venv\Scripts\activate        # macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium                  # or set "channel": "msedge" in config.json
set OPENROUTER_API_KEY=sk-or-...                       # macOS: export OPENROUTER_API_KEY=...
```

## Run order

1. **P0 probe (do this first):** `python scripts/probe_jev.py`
   It prints the raw Jev response. Check three things, then adjust `navigator/jev.py` if needed:
   - whether choice answers include the full `probabilities` map (the probability bars need it;
     the parser also accepts `value` + `probability`, in which case only the winner has a bar);
   - whether `usage` is returned (otherwise cost shows as "est." from a chars/4 estimate);
   - whether the `noul` question shape matches what your email-classification demo sends
     (if your email demo builds noul questions differently, copy that shape into `build_request`).
2. **Offline tests:** `python -m tests.test_policy` and `python -m tests.test_offline`
   (the second uses a local fixture page and a scripted stand-in for Jev: it proves the plumbing,
   not Jev's accuracy).
3. **Demo:** `python server.py` → open http://127.0.0.1:8765 → Start.
   The agent's Chromium window opens separately; the demo page shows its live screencast.
   Put the demo page full-screen and the Chromium window behind it.

## Measured vs estimated

| Shown in the UI | Source |
|---|---|
| Elapsed time, per-step ms, time buckets | measured, wall clock (includes network, page waits and the screencast's own overhead) |
| Jev requests, median decision latency | measured client-side (includes OpenRouter overhead, not pure model time) |
| Input tokens, Jev cost | measured if the response has `usage`; otherwise estimated and labelled "est." |
| Probabilities, verification flags | as returned by Jev |
| Readback ✓/✗, acceptance | computed by code from the page |

## Status of this build

Verified here (offline, headless Chromium): the observer (shadow DOM, modal scoping, hidden-dialog
exclusion, unlabeled icons, disabled buttons), all actions including autocomplete typing and re-rendered
custom radios, readback, policy rules, escalation plumbing and locator validation, acceptance polling,
dialog field capture, Excel export, the screencast frame stream, and the server endpoints.

**Not yet verified:** any real Jev or gpt-4o-mini call (no network from the build sandbox), the live
wellsfargo.com run, headed-browser behaviour on Windows, and bot detection against the Playwright-launched
profile. The first live run will tell us which of the AOP rules Jev actually needs.
