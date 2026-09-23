// One atomic read of the page. Returns the element table Jev sees and keeps
// references to the real DOM nodes in window.__jev.nodes (index -> node).
// No selectors, no XPath: the index IS the handle.
(() => {
  const MAX_TEXT = 3000;
  const INTERACTIVE_ROLES = new Set([
    'button', 'link', 'option', 'radio', 'checkbox', 'tab', 'menuitem',
    'menuitemradio', 'menuitemcheckbox', 'combobox', 'textbox', 'switch', 'searchbox', 'spinbutton'
  ]);
  const vw = window.innerWidth, vh = window.innerHeight;

  // ---- tree walk that enters open shadow roots ----
  function* walk(root) {
    const stack = [root];
    while (stack.length) {
      const n = stack.pop();
      if (n.nodeType === 1) {
        yield n;
        if (n.shadowRoot) stack.push(...Array.from(n.shadowRoot.children).reverse());
      }
      const kids = n.children ? Array.from(n.children) : [];
      for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
    }
  }

  function visible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) return false;
    return true;
  }

  function isInteractive(el) {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (el.hasAttribute('disabled') && tag !== 'input' && tag !== 'select') { /* keep, marked disabled */ }
    if (tag === 'a' && el.hasAttribute('href')) return true;
    if (tag === 'button' || tag === 'select' || tag === 'textarea' || tag === 'summary') return true;
    if (tag === 'input') return (el.type || 'text') !== 'hidden';
    if (INTERACTIVE_ROLES.has(role)) return true;
    if (el.hasAttribute('onclick')) return true;
    if (el.getAttribute('contenteditable') === 'true') return true;
    return false;
  }

  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();

  function byIdInRoot(el, id) {
    const root = el.getRootNode();
    return root.getElementById ? root.getElementById(id) : document.getElementById(id);
  }

  function labelOf(el) {
    const aria = el.getAttribute('aria-label');
    if (clean(aria)) return clean(aria);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map((id) => byIdInRoot(el, id)).filter(Boolean).map((n) => n.innerText || n.textContent).join(' ');
      if (clean(t)) return clean(t);
    }
    if (el.id) {
      const root = el.getRootNode();
      const lab = root.querySelector ? root.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
      if (lab && clean(lab.innerText)) return clean(lab.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && clean(wrap.innerText)) return clean(wrap.innerText).slice(0, 80);
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea') {
      if (clean(el.placeholder)) return clean(el.placeholder);
      if (clean(el.title)) return clean(el.title);
      if (el.type === 'submit' || el.type === 'button') return clean(el.value) || '(unlabeled input)';
    }
    const txt = clean(el.innerText || el.textContent);
    if (txt) return txt.slice(0, 80);
    const img = el.querySelector('img[alt]');
    if (img && clean(img.alt)) return clean(img.alt);
    const svgTitle = el.querySelector('svg title');
    if (svgTitle && clean(svgTitle.textContent)) return clean(svgTitle.textContent);
    if (clean(el.title)) return clean(el.title);
    return '(unlabeled ' + (el.getAttribute('role') || tag) + ')';
  }

  function roleOf(el) {
    const role = el.getAttribute('role');
    if (role) return role.toLowerCase();
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.type || 'text').toLowerCase();
      if (t === 'checkbox' || t === 'radio') return t;
      if (t === 'submit' || t === 'button' || t === 'reset') return 'button';
      return 'textbox';
    }
    if (tag === 'button' || tag === 'summary') return 'button';
    return tag;
  }

  function sectionOf(el) {
    // nearest dialog heading, else fieldset legend, else nearest labelled landmark
    let n = el;
    while (n) {
      if (n.nodeType === 1) {
        const role = n.getAttribute && n.getAttribute('role');
        if (role === 'dialog' || role === 'alertdialog' || n.tagName === 'DIALOG') {
          const h = n.querySelector('h1,h2,h3,h4,[role=heading]');
          return clean(h ? h.innerText : n.getAttribute('aria-label')).replace(/,\s*undefined$/, '') || 'Dialog';
        }
        if (n.tagName === 'FIELDSET') {
          const lg = n.querySelector('legend');
          if (lg && clean(lg.innerText)) return clean(lg.innerText);
        }
        const al = n.getAttribute && n.getAttribute('aria-label');
        if (al && ['form', 'region', 'navigation', 'search', 'section'].includes((role || n.tagName).toLowerCase())) return clean(al);
      }
      n = n.parentNode || (n.host || null);
    }
    return '';
  }

  // ---- modal scoping: if a visible modal is open, only its contents are actionable ----
  const dialogs = [];
  for (const el of walk(document.documentElement)) {
    const role = (el.getAttribute('role') || '').toLowerCase();
    if ((role === 'dialog' || role === 'alertdialog' || el.tagName === 'DIALOG') && visible(el) && clean(el.innerText)) dialogs.push(el);
  }
  const modal = dialogs.length ? dialogs[dialogs.length - 1] : null;
  const inScope = (el) => {
    if (!modal) return true;
    if (modal.contains(el)) return true;
    // popups owned by a control inside the modal (autocomplete listboxes rendered elsewhere)
    const lb = el.closest('[role=listbox]');
    return !!(lb && lb.id && modal.querySelector(`[aria-controls="${CSS.escape(lb.id)}"],[aria-owns="${CSS.escape(lb.id)}"]`));
  };

  // ---- build the table ----
  const nodes = [];
  const elements = [];
  const rects = [];
  const seen = new Set();
  for (const el of walk(document.documentElement)) {
    if (!isInteractive(el) || !visible(el) || !inScope(el)) continue;
    // skip a control nested inside another interactive control we already took (e.g. span inside button)
    let p = el.parentElement, nested = false;
    while (p) { if (seen.has(p)) { nested = true; break; } p = p.parentElement; }
    if (nested) continue;
    seen.add(el);

    const tag = el.tagName.toLowerCase();
    const role = roleOf(el);
    const disabled = el.disabled === true || el.getAttribute('aria-disabled') === 'true';
    const r = el.getBoundingClientRect();
    const index = String(nodes.length + 1);
    const e = { index, role, label: labelOf(el), section: sectionOf(el), operations: [] };

    if (tag === 'select') {
      e.value = el.selectedOptions[0] ? clean(el.selectedOptions[0].textContent) : '';
      e.options = Array.from(el.options).map((o, i) => ({ index: `${index}:${i + 1}`, label: clean(o.textContent), value: o.value }));
      if (!disabled) e.operations.push('SELECT');
    } else if ((tag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file'].includes((el.type || 'text').toLowerCase()))
               || tag === 'textarea' || el.getAttribute('contenteditable') === 'true' || role === 'textbox' || role === 'searchbox') {
      const pw = (el.type || '').toLowerCase() === 'password';
      e.value = pw ? (el.value ? '••••' : '') : clean(el.value !== undefined ? el.value : el.innerText);
      if (el.getAttribute('aria-autocomplete') || role === 'combobox' || el.getAttribute('aria-controls')) e.autocomplete = true;
      if (!disabled && !el.readOnly) e.operations.push('TYPE_TEXT');
    } else {
      const checked = el.getAttribute('aria-checked') ?? (el.checked === undefined ? null : String(el.checked));
      if (checked !== null && checked !== undefined) e.checked = checked;
      const sel = el.getAttribute('aria-selected'); if (sel) e.selected = sel;
      const exp = el.getAttribute('aria-expanded'); if (exp) e.expanded = exp;
      if (!disabled) e.operations.push('CLICK');
    }
    if (disabled) e.disabled = true;
    if (r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) e.in_viewport = false;
    elements.push(e);
    nodes.push(el);
    rects.push({ index, x: r.left, y: r.top, w: r.width, h: r.height });
  }

  const textRoot = modal || document.body;
  const text = clean(textRoot.innerText).slice(0, MAX_TEXT);
  window.__jev = { nodes, modal };
  return {
    url: location.href,
    title: document.title,
    text,
    modal: modal ? sectionOf(modal.querySelector('*') || modal) || 'Dialog' : null,
    elements,
    rects,
    viewport: { w: vw, h: vh },
    scroll: { y: Math.round(window.scrollY), max: Math.max(0, document.documentElement.scrollHeight - vh) }
  };
})()
