# CLAUDE.md

Guidance for Claude Code working in this repository. Read this first, then `docs/ARCHITECTURE.md`.
Design decisions and their reasons are in `docs/DECISIONS.md`; what's next is in `docs/ROADMAP.md`.

## What this is

A browser-automation agent where **TypeSafe's Jev** (a "System One" decision model: typed answers with
probabilities, no text generation) chooses each UI action from a numbered table of the page's own
elements, and **code** decides whether to act. Workflows are described as **AOPs** (Agent Operating
Procedures): intent-level JSON graphs that LangGraph will consume in production. The current demo runs a
mortgage-rates flow on wellsfargo.com with a presentation UI (live browser left, steps centre, Jev metrics right).

## Commands

```bash
pip install -r requirements.txt && python -m playwright install chromium
python scripts/probe_jev.py          # P0: raw Jev response shape (needs OPENROUTER_API_KEY)
python -m tests.test_policy          # pure policy unit tests
python -m tests.test_offline         # end-to-end on a local fixture page, scripted stand-in for Jev
python server.py                     # demo at http://127.0.0.1:8765
```

Both test suites must pass before any change is considered done. They need no network.

## Repository map

| Path | Role |
|---|---|
| `aop/*.json` | AOPs: *what* to do. No implementation names inside. |
| `navigator/snapshot.js` | Observer: one DOM read → element table; node refs kept in `window.__jev.nodes` |
| `navigator/browser.py` | PlaywrightAdapter: launch (persistent profile), observe, settle, act, screencast |
| `navigator/jev.py` | Question builder, Jev call via OpenRouter, tolerant answer parsing, token usage |
| `navigator/policy.py` | Thresholds, hard rules, retry-safety table. Pure functions. |
| `navigator/agent.py` | `run_ui_task(node, variables, rt)`: the UI Agent loop for one `ui_task` |
| `navigator/checks.py` | Acceptance checks and output capture (deterministic) |
| `navigator/escalate.py` | Escalation LLM (gpt-4o-mini): direction only |
| `navigator/runner.py` | AOP graph runner (stand-in for LangGraph), event bus, data tasks |
| `server.py`, `ui/index.html` | Demo server (stdlib) and page: `/screen` MJPEG, `/events` SSE, `POST /run` |
| `docs/DISCOVERY_PROMPT.md` | Prompt for walking a new app with Claude in Chrome to produce an AOP |

## Invariants: do not break these

1. **Jev reports, code decides.** Jev returns choices and probabilities; `policy.py` decides act / escalate /
   hand off. Never let a model output trigger an action without passing policy.
2. **No XPath, no CSS class names, no selectors in AOPs.** Targets are element-table indices resolved at
   runtime. (XPath also does not pierce shadow DOM, which the team's apps use heavily.)
3. **The escalation LLM never acts.** It returns a subgoal and/or candidate Playwright locators. Code accepts
   a locator only if it matches exactly one visible, enabled element; Jev still makes the pick. An
   LLM-sourced element can never be the target of an irreversible action.
4. **Models can escalate caution, never reduce it.** Verification flags (`unexpected_change`,
   `human_review_required`) can halt a run even when code readback passes; a confident model answer never
   overrides a failed code readback or acceptance check.
5. **Retry safety is declared in code per operation** (`policy.RETRY_SAFE`), never asked of a model.
   CLICK is never auto-retried (a checkbox retry toggles it back).
6. **Irreversibility is declared per AOP node** (`side_effects`), with `guards.before_irreversible` checked by
   code before any Submit-like click. Markup heuristics alone are not trusted (the live site's "Go" button is
   `type=submit`).
7. **AOPs describe intent.** Node kinds are `ui_task`, `data_task`, `decision`, `end`. No `jev`/`playwright`
   names in AOPs; the runtime binds kinds to executors.
8. **`run_ui_task` stays LangGraph-ready:** plain data in, plain data out (`status`, `reason`, `outputs`).
   The browser lives in the runtime object, never in workflow state.
9. **Every number shown is labelled measured or estimated.** Never display invented Jev metrics; token cost
   falls back to an estimate only when the provider sends no `usage`, and the UI says "est.".
10. **Typed values come from AOP inputs**, chosen by Jev via the `type_text_value` question. No free-text
    generation in the normal path. Secrets are filled by code and never sent to any model.

## Working conventions

- Lead with design reasoning before code; propose, then build. Push back on over-engineering: add a
  concept only when a real run shows the need (e.g. split a `ui_task` only when evidence says so).
- Dependencies: Playwright, openpyxl, and the standard library. Ask before adding anything else.
- Playwright is used through the **async** API on one worker thread so CDP screencast events keep flowing
  while Jev calls run in `asyncio.to_thread`.
- When changing the observer, update `tests/fixtures/rates.html` to reproduce the new structure and extend
  `tests/test_offline.py`. The fixture mirrors structures seen on the live site; keep it that way.
- New acceptance check → one function in `checks.py` + a line in `docs/AOP_SPEC.md`.
- New data task → a function in `runner.DATA_TASKS` + `docs/AOP_SPEC.md`.
- Prefer grounded evidence: when something is unverified (a response shape, a site behaviour), say so and
  add a probe or test rather than assuming.

## Known unverified items (check before relying on them)

- OpenRouter Jev response shape: full distribution vs value+probability, `usage` presence, and the exact
  `noul` question format (align with the team's working email-classification demo). Run `scripts/probe_jev.py`.
- Live wellsfargo.com run with real Jev; headed Chromium on Windows; bot detection with the Playwright profile.
- Which AOP `rules` Jev actually needs (run the rule-ablation experiment in `docs/ROADMAP.md`).
