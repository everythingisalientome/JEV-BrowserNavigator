# Roadmap

## Status

| Phase | Deliverable | Status |
|---|---|---|
| P0 | Probe Jev response shape on OpenRouter (`scripts/probe_jev.py`) | **Done 2026-09-23**: full distributions, `usage` with cost, noul = `{"noul": p}`; expected answers hit (TYPE_TEXT 0.98, target 1.00, city_state 1.00); see D21 |
| P1 | Target app | wellsfargo.com mortgage-rates flow; discovery walk done (`docs/DISCOVERY_WF.md`) |
| P2 | Observer + fixture tests | Done (offline) |
| P3 | Jev question builder + tolerant parser | Done; noul question shape unconfirmed |
| P4 | Executor, readback, policy, guards, `run_ui_task` | Done (offline) |
| P5 | Escalation (gpt-4o-mini), locator validation | Done (offline, scripted stand-in) |
| P6 | Presentation UI (screencast, SSE, metrics) | Done; not yet seen against a live run |
| P7 | Evidence runs | Run #1 done (see log below); 4 more after D22 |

## Live run log (measured)

| # | Date | Outcome | Steps | Jev req | Median ms | Tokens | Cost | Escalations | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-23 | HANDOFF at step 5 | 1 executed | 5 | 461 | 38,040 | $0.0016 | 3 (6.5 s) | Op-threshold 0.80 escalated a CLICK-vs-no-op-SELECT split; step 2 pick correct at p=1.00; LLM selector rejected by validation. Led to D22. |
| 2 | 2026-09-23 | BLOCKED at step 4 (no progress) | 3 executed, 0 verified | 4 | 408 | 29,069 | $0.0012 | 1 (1.5 s) | Jev chose nav link "Home Loans" (0.76, then 1.0); the link opens a hover menu, not a page; three no-effect clicks. gpt-4o-mini endorsed the same route. Led to D23, D24. |
| 3 | 2026-09-23 | HANDOFF at step 3 (flag) | 2 executed, 2 verified | 3 | 380 | 21,928 | $0.0009 | 0 | Card picked at 0.99, Go at 0.77 → rates page reached. unexpected_change = 0.50 on the navigation halted the run; next pick (Change rate inputs 0.67) was correct. Led to D25. |
| 4 | 2026-09-23 | HANDOFF at step 14 | 10 executed, 10 verified | 14 | 363 | 56,167 | $0.0024 | 3 (4.9 s) | Reached the inputs dialog; city typed and suggestion clicked correctly; then county typed into City (hidden dependency) and "Mecklenburg, NY" chosen; LLM repeated an invalid locator 3×. Led to D26 (node split), D27 (escalation dedupe). |
| 5 | 2026-09-23 | HANDOFF at step 10 (hard floor) | 8 executed, 8 verified | 10 | 348 | 40,516 | $0.0017 | 1 (1.5 s, helpful) | Node 1 fully completed (Done pressed, county dialog open) but acceptance was only checked on a DONE claim; Jev gave DONE 0.08 and split on the next dialog. Led to D28. |
| 6 | 2026-09-23 | SUCCESS | 18 executed, 18 verified | 19 | <ms> | <tokens> | <$> | 1 (helpful) | First full pass. Node 1 ended by code acceptance at the Done click; 7 WAITs (~9 s) during the rates reload; 12/12 fields captured. |

## Next steps, in order

1. **First live run** on wellsfargo.com, headed, demo profile. Record: success, steps, requests, median
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