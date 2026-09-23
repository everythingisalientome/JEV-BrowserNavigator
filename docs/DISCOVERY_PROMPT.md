# Discovery prompt: walk an app with Claude in Chrome and produce an AOP

Paste everything below the line into Claude (with the Claude in Chrome extension connected),
fill in the three blocks at the top, and attach the current AOP JSON if you are extending one.

---

You are doing a **discovery walk** for a Jev-based UI automation. Use the connected browser to
perform the procedure below once, for real, and turn what you observe into an AOP (Agent Operating
Procedure) JSON in the schema given at the end. You are recording ground truth, not writing selectors.

## Inputs (fill in)

**App and start URL:** <e.g. https://www.wellsfargo.com/>

**Procedure (the business steps, in plain language):**
<numbered steps as the business describes them>

**Data values for this walk:** <e.g. city_state = Charlotte, NC; home_price = 300000>

**Existing AOP to extend (optional):** <attached / none>

## Rules for the walk

1. Perform each step in the browser. After every step, observe the page before the next one.
2. Never click anything irreversible (submit, save, confirm, pay, transfer, delete, sign) without asking
   me first in chat and waiting for a yes. Read-only navigation and filling search/filter fields is fine.
3. Do not sign in or enter credentials. If a login appears, stop and tell me.
4. Never use XPath or CSS class names in anything you produce. Describe elements by role, accessible
   name, visible text and section/dialog, because that is all the agent will see.
5. If a step is ambiguous or the page differs from the procedure, stop and tell me what you see.

## What to record at every step

- The **element acted on**: role, accessible name/label, section or dialog it sits in, and its value
  or checked state before and after.
- **Look-alike distractors** the agent could confuse it with (e.g. "Check all rates" vs "Check rates";
  "30-Year Fixed-Rate VA" vs "30-Year Fixed Rate").
- **Widget behaviour:** autocomplete (does a suggestion have to be clicked? is Done disabled until then?),
  custom radios/checkboxes (role, how the state shows), native vs custom dropdowns, dialogs and
  which one is on top, fields that recalculate other fields.
- **Timing:** anything that updates asynchronously, and roughly how long it took (e.g. "summary
  updated about 7 s after Done").
- **Re-renders:** did an action replace the DOM so earlier element references went stale?
- **Structure flags:** count of open shadow roots, iframes (same- or cross-origin), native alert/confirm
  dialogs, new tabs/pop-ups, downloads, file uploads, canvas-drawn controls, unlabeled icon buttons,
  hashed/generated class names.
- **How success shows on screen** for each part of the procedure (text that appears, a dialog that
  opens, a URL change): this becomes the acceptance checks.
- **Data to capture:** exact labels and values as displayed; how they are laid out.

## What to produce

1. **Verified step trace**: a table (#, screen, action, element, what changed, design implication).
2. **AOP JSON** in the schema below. Decide node boundaries with these rules: keep one `ui_task` while
   progress stays visible on the page; start a new node when (a) an irreversible action needs its own
   acceptance check, (b) progress is not visible on the page (e.g. a wizard that hides earlier choices),
   (c) data must be captured and used elsewhere mid-way, (d) the app, tab or login context changes, or
   (e) the step count would exceed about 20.
   - `goal`: the business intent in one or two sentences with `{{variables}}`, not a click list.
   - `rules`: only what the agent could not infer from the page (distractors, required suggestion clicks,
     expected recalculations, waits, business constraints).
   - `acceptance`: only checks from the vocabulary below, derived from "how success shows on screen".
   - `side_effects`: `"none"` for read-only nodes; otherwise `"irreversible_on_submit"` plus
     `guards.before_irreversible` for any value that must be right before submitting.
3. **Golden observations**: for each screen, the list of interactive elements you saw
   (role, label, section, value) so the observer can be tested against them.
4. **Framework impact**: list anything from "Structure flags" that the current framework does not
   handle (see "Known limits" below), and say whether it needs a code change or just an AOP rule.
5. A spreadsheet of any captured data, if the procedure includes capture.

## AOP schema (current)

```json
{
  "procedure_id": "kebab-case-id", "version": "0.1.0", "description": "...",
  "global_config": {"escalation": {"model": "openai/gpt-4o-mini"},
                    "policy": {"min_operation_p": 0.80, "min_target_p": 0.80, "flag_halt_p": 0.50, "max_steps": 25}},
  "variables_schema": {
    "required": {"<name>": {"type": "string", "origin": "user_strict", "default": "<optional>"}},
    "optional": {"<name>": {"type": "string|array|object", "origin": "user_strict|system_captured"}}
  },
  "workflow_graph": {
    "start_node": "<node>",
    "nodes": {
      "<ui node>": {
        "kind": "ui_task",
        "start_url": "{{start_url}}   (first ui_task only)",
        "goal": "...", "inputs": ["<variables the agent may type>"], "rules": ["..."],
        "side_effects": "none | irreversible_on_submit",
        "guards": {"before_irreversible": [{"check": "field_equals", "field": {"label": "...", "section": "..."}, "value": "{{var}}", "normalize": "digits"}]},
        "acceptance": [{"check": "...", "...": "..."}],
        "outputs": {"<var>": {"from": "dialog_fields", "required": ["..."]},
                    "<var2>": {"from": "text_match", "pattern": "regex with one (group)"}},
        "next": "<node>", "on_handoff": "<node>", "on_blocked": "<node>"
      },
      "<data node>": {"kind": "data_task", "task": "write_excel", "data": "{{var}}", "path": "{{export_path}}", "output_variable": "excel_path", "next": "<node>"},
      "<branch>": {"kind": "decision", "rules": [{"when": {"var": "x", "op": "eq|ne|exists", "value": "..."}, "next": "<node>"}], "default_next": "<node>"},
      "<end>": {"kind": "end", "status": "success | handoff", "message": "..."}
    }
  }
}
```

**Acceptance and guard check vocabulary:** `url_matches {pattern}` · `text_visible {text, normalize?, timeout_ms?}` ·
`dialog_visible {contains_text}` · `field_equals {field:{label, section?}, value, normalize?}`.
`normalize: "digits"` compares digits only ("$300,000" = "300000").

**Data tasks available:** `write_excel`. Anything else (read an Excel row, send an email) is a new data task.

## Known limits of the current framework (flag these if you see them)

Cross-origin iframes (observer reads the top document and open shadow roots only) · closed shadow roots ·
canvas-drawn controls · new tabs/pop-up windows · file upload and download steps · native alert/confirm
(auto-dismissed and reported) · login/MFA (use the persistent profile, sign in once by hand) ·
row loops over Excel input (needs a read-row data task).
