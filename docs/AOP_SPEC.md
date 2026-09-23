# AOP specification (v0.1, as implemented)

An AOP is a JSON workflow graph describing **what** to do by intent. It contains no selectors, XPath,
class names or implementation names. The runtime (`navigator/runner.py` now, LangGraph later) executes it.

## Top level

| Key | Meaning |
|---|---|
| `procedure_id`, `version`, `description` | identity; bump `version` on every change |
| `global_config.escalation.model` | escalation LLM (default `openai/gpt-4o-mini`) |
| `global_config.policy` | overrides for `min_operation_p`, `min_operation_p_read_only`, `min_target_p_read_only`, `flag_halt_p_readback_failed`, `min_target_p`, `hard_floor_p`, `irreversible_min_p`, `flag_halt_p`, `human_review_halt_p`, `max_escalations`, `max_steps`, `no_progress_steps` |
| `variables_schema.required/optional` | `{name: {type, origin: user_strict|system_captured, default?}}`; run-time overrides replace defaults |
| `workflow_graph.start_node`, `workflow_graph.nodes` | the graph |

`{{var}}` templates are rendered before each node runs; a value that is exactly `{{var}}` keeps its type
(lists, objects).

## Node kinds

### `ui_task`
| Field | Meaning |
|---|---|
| `start_url` | navigate here first (only if the browser is elsewhere) |
| `goal` | business intent in one or two sentences |
| `inputs` | variables the agent may type (Jev picks which input fills which field) |
| `rules` | only what cannot be inferred from the page: distractors, required suggestion clicks, expected recalculations, waits, business constraints |
| `side_effects` | `"none"` (read-only; irreversible gate off) or `"irreversible_on_submit"` (default) |
| `guards.before_irreversible` | checks that must pass before any Submit-like click |
| `acceptance` | checks that must pass when Jev reports DONE |
| `outputs` | `{var: {from: "dialog_fields", required: [...]}}` or `{var: {from: "text_match", pattern: "…(group)…"}}` |
| `next`, `on_handoff`, `on_blocked` | edges for DONE / HANDOFF / BLOCKED |

### `data_task`
`task` (registered in `runner.DATA_TASKS`), task arguments, `output_variable`, `next`.
Available: `write_excel {data, path}`.

### `decision`
`rules: [{when: {var, op: eq|ne|exists, value}, next}]`, `default_next`. No models involved.

### `end`
`status: success | handoff`, optional `message`.

## Check vocabulary (acceptance and guards)

| Check | Fields | Passes when |
|---|---|---|
| `url_matches` | `pattern` (regex) | current URL matches |
| `text_visible` | `text`, `normalize?`, `timeout_ms?` | text appears in the page (polled until timeout) |
| `dialog_visible` | `contains_text` | a visible dialog contains the text |
| `field_equals` | `field: {label, section?}`, `value`, `normalize?` | the element-table field has that value |

`normalize: "digits"` compares digits only (`"$300,000"` equals `"300000"`).

## Node-splitting rules

Keep one `ui_task` while progress stays visible on the page. Split when: an irreversible action needs its
own acceptance check; progress is not visible (wizards hiding earlier choices); captured data must be used
mid-way; the app, tab or login context changes; or runs exceed the step budget.