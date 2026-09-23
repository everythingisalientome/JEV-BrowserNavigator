# Roadmap

## Status

| Phase | Deliverable | Status |
|---|---|---|
| P0 | Probe Jev response shape on OpenRouter (`scripts/probe_jev.py`) | **Script ready; not yet run** |
| P1 | Target app | wellsfargo.com mortgage-rates flow; discovery walk done (`docs/DISCOVERY_WF.md`) |
| P2 | Observer + fixture tests | Done (offline) |
| P3 | Jev question builder + tolerant parser | Done; noul question shape unconfirmed |
| P4 | Executor, readback, policy, guards, `run_ui_task` | Done (offline) |
| P5 | Escalation (gpt-4o-mini), locator validation | Done (offline, scripted stand-in) |
| P6 | Presentation UI (screencast, SSE, metrics) | Done; not yet seen against a live run |
| P7 | Evidence runs | Not started |

## Next steps, in order

1. **Run P0.** Adjust `jev.build_request` / `parse_choice` to the real shapes. Confirm whether `usage` is
   returned (cost measured vs estimated).
2. **First live run** on wellsfargo.com, headed, demo profile. Record: success, steps, requests, median
   latency, tokens, escalations, time buckets.
3. **Rule ablation.** Remove AOP `rules` one at a time and re-run; record which rules Jev actually needs.
   This is the most useful evidence for leadership (how much site knowledge the AOP must carry).
4. **Evidence table (P7).** 5 runs from a fresh page; report per-run outcomes (the site is not deterministic:
   rates change daily, reload timing varies). Keep measured and estimated columns separate.
5. **Calibration check.** Across runs, compare Jev's probabilities with outcomes (were 0.9 picks right ~90%
   of the time?). Needed before tuning thresholds; current 0.80 / 0.95 / 0.50 are placeholders.

## Back pocket (agreed direction, not built)

### Adapters (same element table → same Jev questions → same policy)

```
             ┌─ PlaywrightAdapter   (Chromium HTML: JSP, ASP.NET, frames)            ← built
observe() ──►├─ IEDriverAdapter     (Edge IE mode via Selenium IEDriver; ES5 snapshot)
act(op,idx)  ├─ UIAAdapter          (applets, ActiveX, thick clients via Windows UI Automation)
             └─ VisionAdapter       (Citrix / pixel-only: screenshot → OCR + detector → element table)
```

Before building any of these, inventory the real target apps: what fraction run in Edge IE mode, use
applets/ActiveX, or sit behind Citrix. That count decides which adapter comes second.

### Observer / executor coverage

- **Iframes:** walk `page.frames` (same-origin first, then cross-origin frames via Playwright frames).
- **Closed shadow roots:** read via the browser accessibility tree (CDP) instead of page JavaScript.
- **New tabs / pop-ups:** `context.on("page")`; follow the new page and repoint the screencast.
- **Downloads / uploads:** `expect_download()`, `set_input_files()`; new AOP fields.
- **Native dialog policy:** allowlist per node instead of always dismissing.
- **JS-bound controls the observer misses** (div with addEventListener): currently found only by escalation;
  consider cursor:pointer + tabindex heuristics if runs show it is common.

### Workflow features

- **Row loops over Excel input** (the team's common pattern): `read_next_row` data task, `decision` on
  `row_found`, loop edge back to the ui_task; per-row results appended to the output workbook.
- **Email-triggered runs:** trigger adapter feeding variables into `run_aop`.
- **LangGraph wrapper:** each node kind → LangGraph node; checkpointer; `interrupt()` for approvals.
- **Write-ahead ledger** before irreversible actions; resume logic routes ambiguous cases to human review.
- **Human take-over on HANDOFF:** make the screencast pane interactive (forward clicks/keys via CDP
  `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent`), ~30 lines.

### Cost and speed

- **Descriptor replay cache:** after a successful run, store each chosen element as a semantic descriptor
  (role + label + section + screen signature, never a selector). On later rows, replay descriptors and call
  Jev only when one fails to resolve. Big saving for Excel-row loops over identical screens.
- **Freshness handling:** jev-ultrafast saw decisions discarded when pages change during a 1–2 s decision;
  measure how often our stale-target path fires on real apps before optimising.

### Infrastructure

- **Sandboxing on user machines** (stretch): Hyper-V for attended bots.
- **Profile management:** one persistent profile per service account; ACL-protected; rotation policy.
- **On-prem models:** swap `JEV_URL` and the escalation endpoint via environment variables; no code change.

## Explicitly out of scope for the demo

Local POC bank app, IE mode, thick clients, Citrix, multi-row input, LangGraph itself.
