# Architecture

## 1. Layers

```
CKP   Canonical Knowledge Procedure — business-owned, plain language. Never executed directly.
 │    converted by engineers or the discovery prompt (DISCOVERY_PROMPT.md)
 ▼
AOP   Agent Operating Procedure — workflow_graph JSON, steps by INTENT (no tech names)
 │    consumed by the runtime: demo runner now (navigator/runner.py), LangGraph in production
 ▼
Runtime dispatch by node kind
 ├─ ui_task    → UI Agent (navigator/agent.py)            ← section 2
 ├─ data_task  → deterministic tool (runner.DATA_TASKS)   e.g. write_excel
 ├─ decision   → rule evaluator (no models)
 └─ end        → terminate with status success | handoff
```

Business owns the CKP. Where a procedure is row-driven (Excel) or email-triggered, the trigger and the row
loop stay deterministic graph nodes; only screen interaction goes through the UI Agent.

## 2. The UI Agent

```
 ui_task (goal + inputs + rules + side_effects + guards + acceptance + outputs)
          │
 ┌────────▼───────────────────────────────────────────────────────────────┐
 │ loop: observe → decide (Jev) → policy → act → readback → observe …      │
 │       on low confidence / BLOCKED: escalate (gpt-4o-mini) → Jev re-picks │
 │       on DONE: acceptance checks → capture outputs                      │
 └──┬─────────────┬──────────────┬──────────────┬──────────────────────────┘
 observe       decide         policy         act + readback
 snapshot.js   jev.py         policy.py      browser.py / agent.readback
    └──────── Playwright-launched Chromium (persistent profile) ◄────┘
```

Status returned: `DONE | HANDOFF | BLOCKED`, mapped by the runner to the node's `next` / `on_handoff` /
`on_blocked` edges.

### 2.1 Observation → element table

One `page.evaluate(snapshot.js)` per observation. Rules:

- Walks the document **and open shadow roots**. Does not enter iframes (backlog).
- **Modal scoping:** if a visible dialog is open, only its contents (and listboxes it owns) are actionable,
  so Jev cannot click the page behind a modal. Hidden dialogs in the DOM are ignored (the live site keeps a
  hidden privacy dialog).
- Label resolution inside each shadow root: `aria-label` → `aria-labelledby` → `<label for>` → wrapping
  label → placeholder/title → text → icon alt/svg title → `(unlabeled <role>)`.
- `section` = dialog heading, fieldset legend, or labelled landmark. This separates look-alike fields
  (residential vs mailing "Street").
- Disabled controls are listed with no operations (Jev sees that "Done" exists but is not usable yet).
- Off-screen elements are included with `in_viewport:false`, so Jev does not waste steps scrolling.
- Password values are masked.
- Node references are kept in `window.__jev.nodes`; the index *is* the handle.

Element row:
```json
{"index":"12","role":"textbox","label":"City, State","section":"Change rate inputs",
 "value":"Charlotte","autocomplete":true,"operations":["TYPE_TEXT"]}
```
SELECT options are addressed as `index:option` (e.g. `"8:1"`).

`settle()` re-observes until two snapshots 300 ms apart agree (cap 3 s). This absorbs async suggestion
lists and re-renders. Longer waits (the live site's ~7 s rates reload) are handled by Jev choosing WAIT
and by acceptance-check polling.

### 2.2 Decision request (one Jev call per step)

```
questions:
  operation          choice over available ops (CLICK, TYPE_TEXT, SELECT, SCROLL_*, WAIT, DONE, BLOCKED)
  click_target       choice over CLICK-able indices only      ┐ one head per available operation;
  type_text_target   choice over editable indices only        │ only the head matching the chosen
  select_target      choice over "index:option" ids           ┘ operation is used
  type_text_value    choice over AOP input names (values come from inputs, never generated)
  step_completed / expected_state_reached / unexpected_change / human_review_required
                     noul questions about the PREVIOUS action (verification folded into this request)
state: page {url,title,open_dialog,text}, elements[], recent_actions (last 10)
```

Per-operation target heads make invalid combinations (TYPE_TEXT on a button) unrepresentable. Folding
step N−1's verification into step N's request keeps one round trip per step; if the flags halt the run,
the bundled next action is discarded unexecuted.

### 2.3 Policy (code decides)

| Condition | Verdict |
|---|---|
| `unexpected_change` or `human_review_required` ≥ 0.50 on previous step | HANDOFF |
| Jev chose BLOCKED | ESCALATE (or BLOCKED if budget spent) |
| Jev chose DONE | DONE_CHECK → acceptance checks |
| min(op p, target p) < 0.40 | HANDOFF |
| op p < 0.80 or target p < 0.80 | ESCALATE (max 3 per node) or HANDOFF |
| Irreversible target (node not `side_effects:"none"`, label submit-like) | needs p ≥ 0.95, never an LLM-sourced element, and all `guards.before_irreversible` pass |
| otherwise | ACT |

Retry safety (code-declared): TYPE_TEXT, SELECT, SCROLL, WAIT are retried once on readback failure;
CLICK never.

### 2.4 Verification layers

1. **Before acting:** node still connected (`StaleTarget` → re-observe, not a failure); Playwright
   actionability checks (visible, stable, enabled, receives events).
2. **Readback (code):** TYPE_TEXT value (digits-normalised for formatted fields such as "$300,000"),
   SELECT value, checkbox/radio `checked`/`aria-checked` change, CLICK = page/URL fingerprint change.
3. **Jev flags** on the next request.
4. **Guards** before irreversible actions.
5. **Acceptance checks** when Jev says DONE, polled with timeouts. DONE is accepted only if they pass;
   two rejected DONEs → HANDOFF.

### 2.5 Failure taxonomy

| Failure | Response |
|---|---|
| Provider error / invalid answer | No action; node returns BLOCKED with the reason |
| Stale target (DOM re-rendered) | Re-observe and re-decide |
| Low confidence / BLOCKED | Escalate (budget 3), then HANDOFF |
| Readback failed | Retry once if retry-safe; otherwise HANDOFF (CLICK with no effect feeds the no-progress detector) |
| Unexpected change / human review flag | HANDOFF |
| No progress for 3 non-WAIT steps | BLOCKED |
| Step budget (25) exhausted | BLOCKED |
| Native alert/confirm | Dismissed, reported as an event (never auto-accepted) |
| Output capture missing required fields | LLM extraction fallback, values accepted only if verbatim in the dialog text; else HANDOFF |

### 2.6 Escalation contract

Input: goal, rules, element table, recent actions, reason, and the active region's HTML (scripts and styles
stripped, capped at 12k chars). Output JSON: `{diagnosis, subgoal|null, candidates:[{locator, why}], handoff}`.
Candidates must be Playwright locators (role/text/CSS, not XPath). Each is validated (exactly one visible,
enabled match) and appended to the table with `source:"llm"`; the subgoal is appended to the goal.

## 3. Demo presentation

```
Python process (server.py)
 ├─ worker thread: asyncio + Playwright → Chromium (persistent demo profile)
 │    ├─ UI Agent drives the page
 │    └─ CDP session: Page.startScreencast → FrameStore (latest JPEG)
 │       Emulation.setFocusEmulationEnabled keeps rendering when the window is not focused
 └─ ThreadingHTTPServer
      /          ui/index.html
      /screen    MJPEG (multipart/x-mixed-replace) from FrameStore → <img>
      /events    Server-Sent Events from EventBus (history replayed to late joiners)
      /aop       the AOP (for the "What we ask" tab)
      POST /run  starts one run at a time
```

Not an iframe: bank sites typically refuse framing, and an iframe would be a different browser from the
one being driven. The overlay of numbered elements is drawn from the observation's rectangles scaled to
the frame.

Event types: `run_started, node_started, observation, jev_request, decision, action, escalation,
acceptance, outputs, node_finished, native_dialog, error, run_finished`. Metrics travel inside
`decision`, `action`, `escalation`, `node_finished`, `run_finished`.

## 4. Browser and profile

Playwright **launches** a new browser with `launch_persistent_context(user_data_dir=...)`; it does not attach
to the user's running browser. From Chrome 136, remote-debugging switches (pipe included) are ignored on the
**default** user-data directory, so the profile must be a dedicated, non-default directory. SSO/MFA: sign in
once by hand in that profile. Treat the directory as a credential store (ACLs, one per service account).
`channel: "msedge"` in `config.json` uses installed Edge.

Isolation plan: demo = dedicated profile dir; attended production = Hyper-V; unattended = the team's existing
robot infrastructure (out of scope here).

## 5. Adapter boundary (future)

The element table is the contract. Jev, policy, verification and the UI are adapter-agnostic.

```
             ┌─ PlaywrightAdapter   (Chromium HTML: JSP, ASP.NET, frames)            ← built
observe() ──►├─ IEDriverAdapter     (Edge IE mode via Selenium IEDriver; ES5 snapshot)
act(op,idx)  ├─ UIAAdapter          (applets, ActiveX, thick clients via Windows UI Automation)
             └─ VisionAdapter       (Citrix / pixel-only: screenshot → OCR + detector → element table)
                        │
          same element table → same Jev questions → same policy layer
```

Interface to preserve when adding one: `start(url)`, `observe() -> {url,title,text,modal,elements,rects,
viewport,scroll,fingerprint}`, `settle()`, `act(op, target, obs, text) -> {after}`, `active_region_html()`,
`adopt_locator()`, `close()`, plus optional frame streaming. Vision needs no VLM necessarily: OCR plus a UI
element detector can produce the table; a VLM is optional for labelling. Verification is weaker there
(OCR readback only).

## 6. Production: LangGraph

- Each AOP node becomes a LangGraph node; `ui_task` wraps `run_ui_task` (about ten lines).
- **Checkpoint at node boundaries, not per click.** Browser state is not checkpointable, and LangGraph
  re-runs an interrupted node from its start.
- **Write-ahead record before any irreversible action;** on resume, a write-ahead record without a completion
  record routes to human review instead of re-clicking.
- `approval` steps map to LangGraph `interrupt()` (human-in-the-loop), durable via the checkpointer.
- Cross-cutting concerns (policy gate, verification, audit, metering, screenshots, redaction) run as one
  explicit, ordered middleware list around the executor, not decorator weaving, so the order is auditable.
