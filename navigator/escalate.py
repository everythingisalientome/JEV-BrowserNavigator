"""Escalation LLM (default openai/gpt-4o-mini via OpenRouter).

It gives DIRECTION only: a revised subgoal and/or candidate Playwright locators for
elements the observer missed. Code validates every locator; Jev still makes the pick.
"""
import asyncio
import json
import os
import time

from .jev import http_post

CHAT_URL = os.environ.get("ESCALATION_URL", "https://openrouter.ai/api/v1/chat/completions")

SYSTEM = """You help a browser agent that is stuck. You never act; you give direction.
Return ONLY a JSON object:
{"diagnosis": "<one sentence>",
 "subgoal": "<the immediate next objective in plain words, or null>",
 "candidates": [{"locator": "<Playwright locator>", "why": "<short>"}],
 "handoff": <true if a person must take over>}
Locator rules: Playwright syntax only, exactly one of these forms:
  role=button[name="Check rates opens dropdown"]     (role + accessible name; preferred)
  text="Charlotte, NC"                               (exact visible text)
  #some-id  or  .some-class                          (CSS, only if the HTML shows a stable id/class)
Never XPath. Never CSS attribute guesses like button[name=...] (buttons have no name attribute).
Propose candidates ONLY for elements missing from the element table; if the right element is already in
the table, return no candidates and put the direction in "subgoal".
If the goal or subgoal is already satisfied on this page, say so in "diagnosis" and give the NEXT objective.
Never propose irreversible actions (submit, delete, confirm payment)."""

EXTRACT_SYSTEM = """Extract label/value pairs from the text. Return ONLY JSON:
{"fields": [{"field": "<label as written>", "value": "<value exactly as written>"}]}
Copy values verbatim; do not compute, round or infer."""


def _json_from(content: str) -> dict:
    s = content.strip().strip("`")
    if s.startswith("json"):
        s = s[4:]
    return json.loads(s[s.find("{"): s.rfind("}") + 1])


async def chat(model: str, system: str, user: dict, key: str) -> tuple[dict, dict]:
    body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user)}]}
    t0 = time.perf_counter()
    res = await asyncio.to_thread(http_post, CHAT_URL, body, key, 45.0)
    meta = {"latency_ms": round((time.perf_counter() - t0) * 1000), "usage": res.get("usage", {}), "model": model}
    return _json_from(res["choices"][0]["message"]["content"]), meta


async def direction(model, key, goal, rules, obs, history, reason, region_html) -> tuple[dict, dict]:
    user = {"goal": goal, "rules": rules, "why_stuck": reason,
            "url": obs["url"], "open_dialog": obs.get("modal"),
            "element_table": [f"[{e['index']}] {e['role']} \"{e['label']}\" {e.get('section', '')} ops={e.get('operations')}"
                              for e in obs["elements"]],
            "recent_actions": history[-8:], "active_region_html": region_html}
    out, meta = await chat(model, SYSTEM, user, key)
    out.setdefault("candidates", [])
    out["candidates"] = [c for c in out["candidates"] if isinstance(c, dict) and c.get("locator")
                         and not c["locator"].lstrip().startswith(("/", "xpath="))][:5]
    return out, meta


async def extract_fields(model, key, text: str) -> tuple[list, dict]:
    out, meta = await chat(model, EXTRACT_SYSTEM, {"text": text}, key)
    # anti-hallucination: keep only pairs whose value appears verbatim in the source text
    kept = [f for f in out.get("fields", []) if str(f.get("value", "")) and str(f["value"]) in text]
    return kept, meta
