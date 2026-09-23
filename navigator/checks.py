"""Deterministic acceptance checks and output capture. Code, not model, says whether it worked."""
import asyncio
import re
import time

from .browser import digits

DIALOG_FIELDS_JS = """() => {
  const vis = d => { const r = d.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(d).visibility !== 'hidden'; };
  const ds = [...document.querySelectorAll('[role=dialog],[role=alertdialog],dialog')].filter(d => vis(d) && d.innerText.trim());
  const d = ds[ds.length - 1]; if (!d) return null;
  const txt = e => (e.innerText || '').trim();
  const rows = [], used = [];
  for (const el of d.querySelectorAll('*')) {
    if (used.some(u => u.contains(el))) continue;
    const kids = [...el.children].filter(c => txt(c));
    if (kids.length !== 2) continue;
    const k = txt(kids[0]), v = txt(kids[1]);
    if (k.includes('\\n') || k.length > 40 || /^[\\d$.,%]/.test(k)) continue;
    const lines = v.split('\\n');
    rows.push({field: k, value: lines[0], note: lines.slice(1).join(' ') || null});
    used.push(el);
  }
  const h = d.querySelector('h1,h2,h3,h4,[role=heading]');
  return {title: h ? txt(h).replace(/,\\s*undefined$/, '') : null, rows, text: txt(d)};
}"""


def _norm(s: str, mode: str | None) -> str:
    return digits(s) if mode == "digits" else re.sub(r"\s+", " ", str(s)).strip().lower()


async def run_check(page, obs_fn, check: dict) -> tuple[bool, str]:
    """Poll a check until it passes or its timeout expires."""
    timeout = check.get("timeout_ms", 0) / 1000
    deadline = time.perf_counter() + timeout
    while True:
        ok, detail = await _once(page, obs_fn, check)
        if ok or time.perf_counter() >= deadline:
            return ok, detail
        await asyncio.sleep(0.5)


async def _once(page, obs_fn, c: dict) -> tuple[bool, str]:
    kind = c["check"]
    if kind == "url_matches":
        ok = re.search(c["pattern"], page.url, re.I) is not None
        return ok, f"url {page.url}"
    if kind == "text_visible":
        body = await page.evaluate("() => document.body.innerText")
        ok = _norm(c["text"], c.get("normalize")) in _norm(body, c.get("normalize"))
        return ok, f"text {'found' if ok else 'not found'}: {c['text']}"
    if kind == "dialog_visible":
        info = await page.evaluate(DIALOG_FIELDS_JS)
        ok = bool(info) and _norm(c.get("contains_text", ""), None) in _norm(info["text"], None)
        return ok, f"dialog {'open' if info else 'not open'}"
    if kind == "field_equals":
        obs = await obs_fn()
        want = c["field"]
        el = next((e for e in obs["elements"] if e["label"] == want.get("label")
                   and (not want.get("section") or e.get("section") == want["section"])), None)
        ok = bool(el) and _norm(el.get("value", ""), c.get("normalize")) == _norm(c["value"], c.get("normalize"))
        return ok, f"{want.get('label')} = {el.get('value') if el else 'missing'}"
    return False, f"unknown check {kind}"


async def capture(page, spec: dict) -> tuple[object, str]:
    src = spec["from"]
    if src == "dialog_fields":
        info = await page.evaluate(DIALOG_FIELDS_JS)
        rows = info["rows"] if info else []
        missing = [r for r in spec.get("required", []) if r not in {x["field"] for x in rows}]
        return {"rows": rows, "title": info and info["title"], "text": info and info["text"], "missing": missing}, \
            ("ok" if not missing and rows else f"missing {missing or 'all fields'}")
    if src == "text_match":
        body = await page.evaluate("() => document.body.innerText")
        m = re.search(spec["pattern"], body)
        return (m.group(1) if m else None), ("ok" if m else "no match")
    return None, f"unknown source {src}"
