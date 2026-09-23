# Decision log

Each entry: decision, reason, evidence where we have it. Newest last. Change a decision by adding a new
entry that supersedes an old one; do not rewrite history.

| # | Decision | Reason / evidence |
|---|---|---|
| D1 | Model the agent on browser-use/jev-ultrafast: structured element table, no screenshots in the decision loop, one Jev request per step. | Their public results: Google Flights task median ~7.1 s, median Jev requests 17. Small sample (3 run pairs), so treated as a mechanism, not a benchmark. |
| D2 | Per-operation target heads (`click_target`, `type_text_target`, `select_target`) instead of one target over all elements. | Makes invalid operation/target pairs unrepresentable; this is how jev-ultrafast does it. |
| D3 | Verification of step N−1 is asked as noul questions inside step N's request. | Halves round trips; the post-action observation is exactly the next decision's state. |
| D4 | Models may escalate caution, never reduce it. Code readback is the primary verdict. | Auditability; a confident model must not override a failed check. |
| D5 | Retry safety declared per operation in code; CLICK never auto-retried. | A retried checkbox click toggles it back; asking a model whether retry is safe is not auditable. |
| D6 | No XPath, no CSS selectors in AOPs. Jev is the primary navigator. | Selector authoring is slow and brittle between design time and runtime. Live evidence: the rates dialog uses hashed CSS-module classes (`index__item___Fb24v`) that change per deploy. XPath also does not pierce shadow DOM. |
| D7 | Escalation LLM (openai/gpt-4o-mini) gives direction only: subgoal + Playwright locators, validated by code, then Jev picks. | Keeps "Jev chooses, code executes" intact; LLM output never reaches the browser unvalidated. |
| D8 | TYPE_TEXT values come from AOP inputs via a `type_text_value` choice question; no text generation in the normal path. | Team automations type row/state data, not free text; fixed values are auditable and readback-comparable. |
| D9 | Irreversibility declared per node (`side_effects`) plus `guards.before_irreversible`; label heuristic is secondary. | Live evidence: the site's "Go" navigation button is `type=submit`; a type=submit heuristic would wrongly gate it. |
| D10 | AOP nodes are intent-level kinds (`ui_task`, `data_task`, `decision`, `end`); no `agent: jev/playwright` fields. | Business readers see steps, not technology; the runtime binds kinds to executors. Deterministic tools (Excel) never run through a model. |
| D11 | One `ui_task` for the whole rates flow; split only on evidence (irreversible step, invisible progress, mid-way capture, context change, step budget). | Jev sees one page + goal + last 10 actions; it works while progress is visible on the page. |
| D12 | Playwright launches a new browser on a dedicated, non-default persistent profile directory. | Requirement: existing profile, new browser process. Chrome 136+ ignores remote debugging on the default user-data dir. |
| D13 | Demo live view = CDP screencast streamed as MJPEG + SSE events from a stdlib server. Not an iframe. | Bank sites refuse framing; an iframe would be a different browser; stdlib keeps dependencies at two. |
| D14 | Demo target is wellsfargo.com (mortgage rates → 30-year fixed details → Excel). The local bank-form app was dropped. | Audience prefers real apps over POC apps. Consequence: no irreversible step and no shadow DOM in the demo flow; both are covered by the offline fixture and policy tests. |
| D15 | Playwright async API on one worker thread; Jev/LLM HTTP calls via `asyncio.to_thread`. | Sync API would freeze screencast frames during model calls. |
| D16 | Output capture is deterministic (label/value pairs inside the visible dialog); LLM extraction only as fallback, values kept only if verbatim in the dialog text. | Live walk: generic extractor reached 12/12 fields after one refinement; the fallback guards against misses without allowing invented values. |
| D17 | browser-harness `interaction-skills` not adopted as a dependency. | They are playbooks for LLMs driving raw CDP; Playwright already provides those mechanics. Used as an edge-case checklist only. We act via element handles, not coordinate clicks, to keep actionability checks and exact readback. |
| D18 | LangGraph for production orchestration; checkpoints at node boundaries; write-ahead before irreversible actions; no per-click graph nodes. | Existing workflow JSON maps directly to LangGraph; browser state is not checkpointable and resumes re-run a node from its start. |
| D19 | Isolation: demo = dedicated profile dir; attended production = Hyper-V; unattended = existing team robot infra (out of scope). | A user-data-dir isolates browser state only, not the OS. |
| D20 | Data exposure to models is not a constraint for this design. | At work, models run on-prem and Jev is being onboarded. |
