"""
Driving the CTMS tab - what lets Claude act in CTMS while he directs it.

The bridge (ctms_bridge.py) attaches to the tab; this is what it does there.

    see        a picture with every clickable thing numbered on it, the
               numbered list, and the words on the screen
    click / type / key / select / scroll / hover   on one of those numbers
    goto / back / forward / reload / dialog / wait

This is what Playwright would do - Playwright drives Edge through this very
DevTools connection - without installing anything on a locked-down machine.

The rails are code, not good intentions:
  - a page with a password box on show is the sign-in page: nothing is clicked
    or typed there, ever. He signs in himself. Nothing is pasted from the work
    PC's clipboard either - it could be holding a password.
  - a button, link, key press, reload or dialog answer that would book, save,
    submit, confirm, send or delete is refused unless the command carries
    commit=True, which Claude only sends once he has said so in the chat.
    Unsure counts as risky.
  - goto stays on the CTMS site.
  - a number is checked against the picture it came from: if the page moved
    on underneath, the click is refused rather than landing on whatever is
    there now.

Standard library only.
"""
import base64
import json
import re
import struct
import time
from urllib.parse import urljoin, urlsplit

import cdp


class Refused(Exception):
    """Not done, on purpose. The message says why, in words for the chat."""


class NeedsCommit(Refused):
    """Not done because it would save, book, submit or delete - ask him first."""


HIDDEN = ("CTMS is not on screen in the automation browser - the window is minimised, or another "
          "tab is selected. Restore it (it can sit behind other windows) and keep CTMS as its "
          "selected tab.")


def jpeg_size(raw):
    """(width, height) of a JPEG from its frame header, or (0, 0)."""
    i = 2
    while i + 9 < len(raw):
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", raw[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
    return 0, 0


def grab(ws, fmt="jpeg", max_w=1280, quality=55, dialog=None):
    """The visible part of the tab as base64, and where it was. Raises with a reason."""
    if dialog:
        raise RuntimeError(f"A {dialog.get('type') or 'dialog'} box is open in CTMS: "
                           f"\"{str(dialog.get('message') or '')[:160]}\" - it has to be answered first.")
    view = json.loads(ws.evaluate(cdp.VIEW_JS, timeout=8) or "{}")
    if view.get("visible") == "hidden":
        raise RuntimeError(HIDDEN)
    params = {"format": fmt}
    if fmt == "jpeg":
        params["quality"] = quality
    w, h, dpr = view.get("w") or 0, view.get("h") or 0, view.get("dpr") or 1
    if max_w and w and h:
        params["clip"] = {"x": view.get("x") or 0, "y": view.get("y") or 0, "width": w, "height": h,
                          "scale": round(min(1.0, max_w / (w * dpr)), 4)}
    try:
        data = ws.call("Page.captureScreenshot", params, timeout=12).get("data") or ""
    except TimeoutError:
        raise RuntimeError("Edge did not paint the CTMS tab in time - is its window minimised? "
                           "Restore it; it can sit behind other windows.")
    return data, view


# Injected into the CTMS tab on demand (it is gone after every page load, and
# re-injecting is cheap). Everything it says comes back as JSON text.
#
# Frames matter: an old enterprise screen is often a FRAMESET, or keeps its real
# form in an IFRAME, and a plain querySelectorAll walks straight past both. It
# walks every same-origin frame and shadow root, and keeps each frame's offset
# so a number can be clicked where it really is on screen. A cross-origin frame
# cannot be read from here; it is reported, never silently skipped.
LIB_JS = r"""
(() => {
  if (window.__ctmsLib && window.__ctmsLib.v === 1) return 'ok';
  // Words that mean "this changes something". Labels are judged as a person
  // reads them; ids, names and onclick handlers after camelCase is split up.
  const WORDS = /\b(book|save|submit|confirm|delete|remove|send|despatch|dispatch|allocate|approve|accept|reject|decline|update|amend|apply|create|add|post|upload|finish|complete|commit|authori[sz]e|finali[sz]e|void|release|transfer|ok|yes|proceed|reserve|pay|issue|generate|raise|split|merge)\b/i;
  const NAV = /\b(search|find|look ?up|view|open|show|list|menu|home|back|previous|prev|next|first|last|filter|refresh|clear|reset|help|details?|more|less|expand|collapse|sort|page|print|export|download|close)\b/i;
  const HARD = /\b(book|save|submit|confirm|delete|send)\b/i;
  const SIGV = /\b(book|save|submit|confirm|delete|remove|send|despatch|dispatch|allocate|approve|commit|finali[sz]e|authori[sz]e|transfer|release|void)\b/i;
  // A bare "Cancel" closes a form; "Cancel order" / cancelBooking() undoes a job.
  const CANCEL = /\bcancel(l?ed|lation|s)?\s+(the\s+|this\s+)?(booking|order|job|delivery|collection|load|movement|request|vehicle|slot|run|trip|consignment)s?\b/i;
  const SEL = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=menuitem],' +
    '[role=menuitemcheckbox],[role=menuitemradio],[role=tab],[role=checkbox],[role=radio],[role=option],' +
    '[role=combobox],[role=textbox],[role=searchbox],[role=switch],[role=treeitem],[onclick],' +
    '[contenteditable=""],[contenteditable="true"],[tabindex]:not([tabindex="-1"])';
  const TEXTY = /^(text|search|email|number|tel|url|date|time|datetime-local|month|week)$/i;
  const clean = (s, n) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim().slice(0, n || 80);
  const words = (s) => String(s || '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_\-.():;,'"\/=?&#+]+/g, ' ');
  const win = (e) => e.ownerDocument.defaultView;
  const tag = (e) => (e.tagName || '').toUpperCase();
  const typ = (e) => String(e.type || '').toLowerCase();

  const isPw = (e) => tag(e) === 'INPUT' && (typ(e) === 'password'
    || /(current|new)-password/i.test(e.getAttribute('autocomplete') || '')
    || /passw|pwd|pass_?word/i.test((e.name || '') + ' ' + (e.id || '')));
  const isText = (e) => (tag(e) === 'INPUT' && TEXTY.test(typ(e) || 'text')) || tag(e) === 'TEXTAREA'
    || !!e.isContentEditable
    || (/^(textbox|searchbox|combobox)$/.test(e.getAttribute('role') || '') && !['SELECT', 'BUTTON', 'A'].includes(tag(e)));
  const isButtonish = (e) => ['BUTTON', 'A', 'SUMMARY'].includes(tag(e))
    || (tag(e) === 'INPUT' && /^(submit|button|reset|image)$/.test(typ(e)))
    || /^(button|link|menuitem|tab|option)$/.test(e.getAttribute('role') || '') || e.hasAttribute('onclick');

  const near = (e) => {
    const cell = e.closest('td,th');
    if (cell) {
      let p = cell.previousElementSibling;
      while (p && !clean(p.innerText)) p = p.previousElementSibling;
      if (p) return p.innerText;
    }
    let n = e.previousSibling, s = '';
    for (let i = 0; n && i < 6 && !s.trim(); i++, n = n.previousSibling) {
      // words before another field are that field's label, not this one's
      if (n.nodeType === 1 && (/^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(tag(n))
          || (n.querySelector && n.querySelector('input,select,textarea,button')))) break;
      s = n.nodeType === 3 ? n.textContent : (n.innerText || '');
    }
    return s;
  };
  const labelOf = (e) => {
    const d = e.ownerDocument;
    let s = e.getAttribute('aria-label');
    if (s && s.trim()) return clean(s);
    const lb = e.getAttribute('aria-labelledby');
    if (lb) {
      s = lb.split(/\s+/).map((id) => { const x = d.getElementById(id); return x ? (x.innerText || x.textContent) : ''; }).join(' ');
      if (s.trim()) return clean(s);
    }
    const t = tag(e), ty = typ(e);
    if (t === 'INPUT' && /^(submit|button|reset)$/.test(ty)) return clean(e.value || ty);
    if (t === 'INPUT' && ty === 'image') return clean(e.alt || e.title || e.value || 'image button');
    if (e.labels && e.labels.length) {
      s = [...e.labels].map((l) => l.innerText || l.textContent).join(' ');
      if (s.trim()) return clean(s);
    }
    if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(t)) {
      s = e.innerText || e.textContent || '';
      if (s.trim()) return clean(s);
      const img = e.querySelector && e.querySelector('img[alt],img[title],[title]');
      if (img) { s = img.getAttribute('alt') || img.getAttribute('title'); if (s && s.trim()) return clean(s); }
    }
    if (e.title) return clean(e.title);
    if (e.placeholder) return clean(e.placeholder);
    return clean(near(e), 50);
  };
  const roleOf = (e) => {
    const r = e.getAttribute('role');
    if (r) return r;
    const t = tag(e), ty = typ(e);
    if (t === 'A') return 'link';
    if (t === 'BUTTON' || t === 'SUMMARY') return 'button';
    if (t === 'SELECT') return e.multiple ? 'listbox' : 'dropdown';
    if (t === 'TEXTAREA') return 'textbox';
    if (t === 'LABEL') return 'label';
    if (t === 'INPUT') {
      if (/^(submit|button|reset|image)$/.test(ty)) return 'button';
      if (ty === 'checkbox' || ty === 'radio') return ty;
      if (ty === 'password') return 'password';
      if (ty === 'file') return 'file';
      if (ty === 'range') return 'slider';
      return 'textbox';
    }
    if (e.isContentEditable) return 'textbox';
    return 'clickable';
  };
  const describe = (e) => {
    if (!e) return 'nothing';
    const l = labelOf(e);
    return roleOf(e) + (l ? ' "' + l.slice(0, 60) + '"' : e.id ? ' #' + e.id : e.getAttribute('name') ? ' [name=' + e.getAttribute('name') + ']' : '');
  };
  const commitOf = (e) => {
    if (!e || !e.getAttribute) return false;
    const lab = labelOf(e);
    if (lab && ((WORDS.test(lab) && !(NAV.test(lab) && !HARD.test(lab))) || CANCEL.test(lab))) return true;
    const href = e.getAttribute('href') || '';
    const sig = words([e.id, e.getAttribute('name'), e.title, e.getAttribute('onclick'), e.getAttribute('onchange'),
                       /^javascript:/i.test(href) ? href : '', e.getAttribute('formaction')].join(' '));
    if (SIGV.test(sig) || CANCEL.test(sig)) return true;
    const t = tag(e);
    const submits = (t === 'BUTTON' && (e.getAttribute('type') || 'submit').toLowerCase() === 'submit')
      || (t === 'INPUT' && /^(submit|image)$/.test(typ(e)));
    if (submits && e.form) {
      if (SIGV.test(words((e.form.getAttribute('action') || '') + ' ' + e.form.id + ' ' + (e.form.getAttribute('name') || '')))) return true;
      if (!lab) return true;           // a submit button that says nothing: assume it does
    }
    return false;
  };
  const valueOf = (e) => {
    if (isPw(e)) return e.value ? '[hidden]' : '';
    const t = tag(e);
    if (t === 'SELECT') { const o = e.options[e.selectedIndex]; return o ? clean(o.text, 60) : ''; }
    if (t === 'INPUT' && /^(checkbox|radio|submit|button|reset|image)$/.test(typ(e))) return '';
    if (t === 'INPUT' || t === 'TEXTAREA') return clean(e.value, 120);
    if (e.isContentEditable) return clean(e.innerText, 120);
    return '';
  };
  const shown = (e, r) => {
    if (r.width < 2 || r.height < 2) return false;
    if (e.checkVisibility) return e.checkVisibility({ opacityProperty: true, visibilityProperty: true });
    const cs = win(e).getComputedStyle(e);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0;
  };

  // Every same-origin document, with where its top-left sits on screen and the
  // part of the screen it can show (its frame, cut by the frames around it).
  const documents = () => {
    const W = window.innerWidth, H = window.innerHeight, docs = [], opaque = [];
    const walk = (d, ox, oy, clip, path) => {
      docs.push({ d, ox, oy, clip, path });
      d.querySelectorAll('iframe,frame').forEach((f, i) => {
        const fr = f.getBoundingClientRect();
        const p = (path ? path + ' > ' : '') + (f.name || f.id || 'frame' + (i + 1));
        const c2 = { l: Math.max(clip.l, ox + fr.left), t: Math.max(clip.t, oy + fr.top),
                     r: Math.min(clip.r, ox + fr.right), b: Math.min(clip.b, oy + fr.bottom) };
        let cd = null;
        try { cd = f.contentDocument; } catch (err) { cd = null; }
        if (cd && cd.documentElement) walk(cd, ox + fr.left + f.clientLeft, oy + fr.top + f.clientTop, c2, p);
        else if (fr.width > 1 && fr.height > 1) {
          opaque.push({ frame: p, x: Math.round(ox + fr.left), y: Math.round(oy + fr.top),
                        w: Math.round(fr.width), h: Math.round(fr.height) });
        }
      });
    };
    walk(document, 0, 0, { l: 0, t: 0, r: W, b: H }, '');
    return { docs, opaque, W, H };
  };
  const rootsOf = (d) => {
    const roots = [d];
    for (let i = 0; i < roots.length; i++) {
      roots[i].querySelectorAll('*').forEach((e) => { if (e.shadowRoot && !roots.includes(e.shadowRoot)) roots.push(e.shadowRoot); });
    }
    return roots;
  };
  const signIn = (docs) => docs.some((g) => rootsOf(g.d).some((root) =>
    [...root.querySelectorAll('input')].some((e) => typ(e) === 'password' && shown(e, e.getBoundingClientRect()))));

  // Things that only say they are clickable through their cursor - old screens
  // put onclick handlers on table cells. Only where the pointer STARTS (cursor
  // is inherited), and not around or inside something already listed.
  const pointerOrigins = (root, picked) => {
    const out = [];
    root.querySelectorAll('div,span,td,th,tr,li,img,i,svg,label,p,b,strong,em,font').forEach((e) => {
      if (out.length >= 200 || picked.has(e)) return;
      if (tag(e) === 'LABEL' && e.control && !shown(e.control, e.control.getBoundingClientRect())) { out.push(e); return; }
      if (win(e).getComputedStyle(e).cursor !== 'pointer') return;
      const par = e.parentElement;
      if (par && win(par).getComputedStyle(par).cursor === 'pointer') return;
      if (e.closest(SEL) || e.querySelector(SEL)) return;
      out.push(e);
    });
    return out;
  };

  const layers = [];
  const unmark = () => {
    layers.splice(0).forEach((L) => { try { L.remove(); } catch (err) { /* page moved on */ } });
    return true;
  };

  const snapshot = (sid, marks) => {
    unmark();
    const { docs, opaque, W, H } = documents();
    const items = [], seen = new Set();
    for (const g of docs) {
      for (const root of rootsOf(g.d)) {
        const cands = [...root.querySelectorAll(SEL)];
        cands.push(...pointerOrigins(root, new Set(cands)));
        for (const e of cands) {
          if (seen.has(e)) continue;
          seen.add(e);
          if (tag(e) === 'INPUT' && typ(e) === 'hidden') continue;
          const r = e.getBoundingClientRect();
          if (!shown(e, r)) continue;
          const x = g.ox + r.left, y = g.oy + r.top;
          const iv = x + r.width > g.clip.l && x < g.clip.r && y + r.height > g.clip.t && y < g.clip.b;
          items.push({ e, g, r, x, y, iv });
        }
      }
    }
    let keep = items;
    if (items.length > 600) {
      const inView = new Set(items.filter((it) => it.iv).slice(0, 600));
      const rest = items.filter((it) => !inView.has(it)).slice(0, 600 - inView.size);
      const pick = new Set([...inView, ...rest]);
      keep = items.filter((it) => pick.has(it));
    }
    window.__ctmsSnap = { id: sid, els: keep.map((it) => it.e) };
    const els = keep.map((it, i) => {
      const e = it.e, o = { n: i + 1, r: roleOf(e), l: labelOf(e) };
      const v = valueOf(e); if (v) o.v = v;
      if (tag(e) === 'INPUT' && isText(e) && typ(e) !== 'text') o.t = typ(e);
      if (tag(e) === 'SELECT') o.o = [...e.options].slice(0, 25).map((x) => clean(x.text, 40));
      if (/^(checkbox|radio)$/.test(typ(e))) o.on = !!e.checked;
      if (e.disabled || e.getAttribute('aria-disabled') === 'true') o.dis = true;
      if (e.readOnly) o.ro = true;
      if (e.required) o.req = true;
      if (isPw(e)) o.pw = true;
      if (commitOf(e)) o.c = true;
      if (!it.iv) o.off = it.y + it.r.height <= it.g.clip.t ? 'above' : it.y >= it.g.clip.b ? 'below' : 'aside';
      o.x = Math.round(it.x); o.y = Math.round(it.y); o.w = Math.round(it.r.width); o.h = Math.round(it.r.height);
      if (it.g.path) o.f = it.g.path;
      if (e.id) o.id = String(e.id).slice(0, 60);
      if (e.getAttribute('name')) o.nm = String(e.getAttribute('name')).slice(0, 60);
      if (tag(e) === 'A') o.href = (e.getAttribute('href') || '').slice(0, 200);
      return o;
    });
    if (marks) {
      const byDoc = new Map();
      keep.forEach((it, i) => { if (it.iv) { if (!byDoc.has(it.g.d)) byDoc.set(it.g.d, []); byDoc.get(it.g.d).push([i + 1, it.r]); } });
      byDoc.forEach((list, d) => {
        const host = d.body || d.documentElement;
        if (!host || tag(host) === 'FRAMESET') return;
        const L = d.createElement('div');
        L.setAttribute('data-ctms-mark', '');
        L.style.cssText = 'position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;';
        list.forEach(([n, r]) => {
          const b = d.createElement('div');
          b.style.cssText = 'position:fixed;box-sizing:border-box;pointer-events:none;border:2px solid rgba(255,0,170,.85);'
            + 'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px;';
          const t = d.createElement('div');
          t.textContent = String(n);
          t.style.cssText = 'position:fixed;pointer-events:none;background:#d6007e;color:#fff;font:bold 11px/13px Arial,sans-serif;'
            + 'padding:0 3px;border-radius:3px;left:' + Math.max(0, r.left - 1) + 'px;top:' + (r.top >= 14 ? r.top - 14 : r.top) + 'px;';
          L.appendChild(b); L.appendChild(t);
        });
        host.appendChild(L);
        layers.push(L);
      });
    }
    const a = activeEl();
    return JSON.stringify({ id: sid, w: W, h: H, dpr: window.devicePixelRatio || 1, sx: window.scrollX, sy: window.scrollY,
      url: location.href, title: document.title, signIn: signIn(docs), els, opaque, total: items.length,
      focus: a.el ? describe(a.el) : a.opaque ? 'a frame the bridge cannot read' : '' });
  };

  // Where a numbered thing is NOW, on screen, ready for the mouse - after
  // scrolling it into view, and only if nothing is lying on top of it.
  const prepare = (n, sid, scroll, hit) => {
    const S = window.__ctmsSnap;
    if (!S || S.id !== sid) return JSON.stringify({ ok: false, why: 'stale', have: S ? S.id : '' });
    const e = S.els[n - 1];
    if (!e) return JSON.stringify({ ok: false, why: 'nosuch' });
    if (!e.isConnected) return JSON.stringify({ ok: false, why: 'gone' });
    const desc = describe(e), fw = win(e);
    let r = e.getBoundingClientRect();
    if (scroll && (r.top < 0 || r.left < 0 || r.bottom > fw.innerHeight || r.right > fw.innerWidth)) {
      e.scrollIntoView({ block: 'center', inline: 'center' });
      r = e.getBoundingClientRect();
    }
    let ox = 0, oy = 0, w = fw;
    try {
      while (w !== window && w.frameElement) {
        const fe = w.frameElement, fr = fe.getBoundingClientRect();
        ox += fr.left + fe.clientLeft; oy += fr.top + fe.clientTop; w = w.parent;
      }
    } catch (err) { return JSON.stringify({ ok: false, why: 'frame', desc }); }
    const rects = e.getClientRects(), rr = rects.length > 1 ? rects[0] : r;
    const lx = rr.left + rr.width / 2, ly = rr.top + rr.height / 2;
    const base = { desc, commit: commitOf(e), text: isText(e), pw: isPw(e), sel: tag(e) === 'SELECT',
                   dis: !!e.disabled || e.getAttribute('aria-disabled') === 'true', ro: !!e.readOnly };
    if (lx < 0 || ly < 0 || lx > fw.innerWidth || ly > fw.innerHeight) return JSON.stringify(Object.assign(base, { ok: false, why: 'offscreen' }));
    if (hit) {
      const root = e.getRootNode();
      const h = (root.elementFromPoint ? root : e.ownerDocument).elementFromPoint(lx, ly);
      const fine = h && (h === e || e.contains(h) || h.contains(e)
        || (e.labels && [...e.labels].some((l) => l === h || l.contains(h))));
      if (!fine) return JSON.stringify(Object.assign(base, { ok: false, why: 'covered', by: h ? describe(h) : 'nothing' }));
      const inner = h !== e && h.closest ? h.closest('a[href],button,input,[role=button],[onclick]') : null;
      if (inner && inner !== e && commitOf(inner)) base.commit = true;
    }
    return JSON.stringify(Object.assign(base, { ok: true, x: ox + lx, y: oy + ly }));
  };

  // What a click at a point on the screen would land on.
  const probe = (x, y) => {
    let d = document, ox = 0, oy = 0, e = d.elementFromPoint(x, y);
    while (e && (tag(e) === 'IFRAME' || tag(e) === 'FRAME')) {
      let cd = null;
      try { cd = e.contentDocument; } catch (err) { cd = null; }
      if (!cd) return JSON.stringify({ ok: true, opaque: true, commit: true, x, y,
        desc: 'a part of CTMS the bridge cannot read (frame ' + (e.name || e.id || '?') + ')' });
      const fr = e.getBoundingClientRect();
      ox += fr.left + e.clientLeft; oy += fr.top + e.clientTop;
      e = cd.elementFromPoint(x - ox, y - oy);
    }
    while (e && e.shadowRoot) { const inner = e.shadowRoot.elementFromPoint(x - ox, y - oy); if (!inner || inner === e) break; e = inner; }
    if (!e) return JSON.stringify({ ok: false, why: 'nothing' });
    const t = e.closest('a[href],button,input,select,textarea,[role=button],[role=link],[onclick]') || e;
    return JSON.stringify({ ok: true, x, y, desc: describe(t), commit: commitOf(t), text: isText(t), pw: isPw(t),
                            dis: !!t.disabled });
  };

  const activeEl = () => {
    let a = document.activeElement;
    while (a && (tag(a) === 'IFRAME' || tag(a) === 'FRAME')) {
      let cd = null;
      try { cd = a.contentDocument; } catch (err) { cd = null; }
      if (!cd) return { opaque: true };
      a = cd.activeElement;
    }
    while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
    if (!a || a === a.ownerDocument.body || a === a.ownerDocument.documentElement) return {};
    return { el: a };
  };
  // What Enter (or Space) would do from where the focus is now.
  const focusInfo = () => {
    const f = activeEl();
    if (f.opaque) return JSON.stringify({ opaque: true });
    const a = f.el;
    if (!a) return JSON.stringify({ none: true });
    const out = { desc: describe(a), pw: isPw(a), text: isText(a), button: isButtonish(a), commit: false, what: '' };
    if (out.button) { out.commit = commitOf(a); out.what = 'presses ' + out.desc; }
    else if (tag(a) !== 'TEXTAREA' && !a.isContentEditable && a.form) {
      const def = a.form.querySelector('button:not([type=button]):not([type=reset]),input[type=submit],input[type=image]');
      out.commit = def ? commitOf(def) : SIGV.test(words(a.form.getAttribute('action') || ''));
      out.what = 'submits the form' + (def ? ' (' + describe(def) + ')' : '');
    }
    return JSON.stringify(out);
  };

  const clearFor = (n) => {
    const e = (window.__ctmsSnap || { els: [] }).els[n - 1];
    if (!e) return false;
    if (e.isContentEditable) {
      const s = win(e).getSelection(), rg = e.ownerDocument.createRange();
      rg.selectNodeContents(e); s.removeAllRanges(); s.addRange(rg);
      return true;
    }
    try { e.select(); } catch (err) { /* number/date inputs */ }
    let all = false;
    try { all = e.selectionStart === 0 && e.selectionEnd === String(e.value || '').length; } catch (err) { all = false; }
    if (!all && e.value) {
      const proto = Object.getPrototypeOf(e), desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(e, ''); else e.value = '';
      e.dispatchEvent(new (win(e).Event)('input', { bubbles: true }));
    }
    return true;
  };

  const choose = (n, sid, want) => {
    const S = window.__ctmsSnap;
    if (!S || S.id !== sid) return JSON.stringify({ ok: false, why: 'stale' });
    const e = S.els[n - 1];
    if (!e || !e.isConnected) return JSON.stringify({ ok: false, why: 'gone' });
    if (tag(e) !== 'SELECT') return JSON.stringify({ ok: false, why: 'notselect', desc: describe(e) });
    const opts = [...e.options], w = String(want).trim().toLowerCase();
    let o = opts.find((x) => x.text.trim().toLowerCase() === w) || opts.find((x) => x.value.toLowerCase() === w);
    if (!o) {
      const part = opts.filter((x) => x.text.toLowerCase().includes(w));
      if (part.length === 1) o = part[0];
      else return JSON.stringify({ ok: false, why: part.length ? 'ambiguous' : 'nooption', desc: describe(e),
        options: (part.length ? part : opts).slice(0, 30).map((x) => clean(x.text, 40)) });
    }
    e.focus();
    const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(e), 'value');
    if (desc && desc.set) desc.set.call(e, o.value); else e.value = o.value;
    o.selected = true;
    const Ev = win(e).Event;
    e.dispatchEvent(new Ev('input', { bubbles: true }));
    e.dispatchEvent(new Ev('change', { bubbles: true }));
    return JSON.stringify({ ok: true, desc: describe(e), chosen: clean(o.text, 60) });
  };

  window.__ctmsLib = { v: 1, snapshot, prepare, probe, focusInfo, clearFor, choose, unmark,
    signIn: () => signIn(documents().docs) };
  return 'ok';
})()
"""

# name -> (key, code, Windows virtual key code, text it types)
KEYS = {
    "enter": ("Enter", "Enter", 13, "\r"), "return": ("Enter", "Enter", 13, "\r"),
    "tab": ("Tab", "Tab", 9, None), "escape": ("Escape", "Escape", 27, None), "esc": ("Escape", "Escape", 27, None),
    "backspace": ("Backspace", "Backspace", 8, None), "delete": ("Delete", "Delete", 46, None),
    "space": (" ", "Space", 32, " "), "home": ("Home", "Home", 36, None), "end": ("End", "End", 35, None),
    "pageup": ("PageUp", "PageUp", 33, None), "pagedown": ("PageDown", "PageDown", 34, None),
    "up": ("ArrowUp", "ArrowUp", 38, None), "arrowup": ("ArrowUp", "ArrowUp", 38, None),
    "down": ("ArrowDown", "ArrowDown", 40, None), "arrowdown": ("ArrowDown", "ArrowDown", 40, None),
    "left": ("ArrowLeft", "ArrowLeft", 37, None), "arrowleft": ("ArrowLeft", "ArrowLeft", 37, None),
    "right": ("ArrowRight", "ArrowRight", 39, None), "arrowright": ("ArrowRight", "ArrowRight", 39, None),
}
KEYS.update({f"f{i}": (f"F{i}", f"F{i}", 111 + i, None) for i in range(1, 13)})
MODS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "win": 4, "cmd": 4, "shift": 8}
# Paste could hand CTMS whatever is on the work PC's clipboard - his password,
# say. The rest act on the browser itself, not the page: close it, print it,
# open DevTools on it.
BLOCKED_KEYS = {"ctrl+v", "shift+insert", "ctrl+shift+v", "ctrl+w", "ctrl+f4", "ctrl+shift+w", "alt+f4",
                "ctrl+p", "ctrl+s", "ctrl+o", "ctrl+n", "ctrl+t", "ctrl+shift+n", "ctrl+l", "ctrl+shift+i",
                "ctrl+shift+j", "ctrl+u", "f12", "ctrl+h", "ctrl+j", "ctrl+d", "ctrl+shift+delete", "f11"}

WHY = {
    "stale": "The page has changed since that picture - look again (see) and use the new numbers.",
    "nosuch": "There is no [{n}] in the latest picture - look again (see).",
    "gone": "[{n}] is not on the page any more (the page redrew) - look again (see).",
    "covered": "[{n}] {desc} is covered by {by} - close that first, or scroll.",
    "offscreen": "Could not bring [{n}] {desc} on screen to click it - try scroll first.",
    "frame": "[{n}] is in a frame the bridge cannot reach any more - look again (see).",
}


class Driver:
    """One attached CTMS tab, driven. The bridge makes a new one per attach."""

    SEE_MAX_W = 1600

    def __init__(self, ws):
        self.ws = ws
        self.snap_no = 0
        self.snap = None          # {"id", "ppc" (picture pixels per CSS pixel)} of the latest see
        self.dialog = None        # an alert/confirm/prompt open in the tab right now
        self.inflight = {}        # page and data requests still running: id -> started
        self.loading = set()      # frames part-way through loading

    # ---- what the browser tells us ----
    def on_event(self, msg):
        m, p = msg.get("method") or "", msg.get("params") or {}
        if m == "Page.javascriptDialogOpening":
            self.dialog = {"type": p.get("type") or "alert", "message": str(p.get("message") or "")[:500],
                           "default": str(p.get("defaultPrompt") or "")[:200]}
        elif m == "Page.javascriptDialogClosed":
            self.dialog = None
        elif m == "Page.frameStartedLoading":
            self.loading.add(p.get("frameId"))
        elif m == "Page.frameStoppedLoading":
            self.loading.discard(p.get("frameId"))
        elif m == "Page.frameNavigated" and not (p.get("frame") or {}).get("parentId"):
            self.snap = None          # every number from before is meaningless now
        elif m == "Network.requestWillBeSent":
            if p.get("type") in ("Document", "XHR", "Fetch"):
                self.inflight[p.get("requestId")] = time.time()
        elif m in ("Network.loadingFinished", "Network.loadingFailed"):
            self.inflight.pop(p.get("requestId"), None)

    def _dialog_open(self):
        return bool(self.dialog)

    def _dialog_text(self):
        d = self.dialog or {}
        return (f"A {d.get('type') or 'dialog'} box is open in CTMS: \"{d.get('message', '')[:200]}\". "
                f"Answer it with dialog accept or dialog dismiss.")

    # ---- the page script ----
    def _js(self, call, timeout=15):
        """Run one __ctmsLib call (injecting the library first if the page lost it)."""
        if self.dialog:
            raise Refused(self._dialog_text())
        r = self.ws.call("Runtime.evaluate", {"expression": LIB_JS + ";\n" + call, "returnByValue": True},
                         timeout=timeout, abort=self._dialog_open)
        if r is None:
            raise Refused(self._dialog_text())
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError("The CTMS page would not run the bridge's script: "
                               + ((d.get("exception") or {}).get("description") or d.get("text") or "?")[:200])
        return (r.get("result") or {}).get("value")

    def _check_page(self):
        if self._js("window.__ctmsLib.signIn()"):
            raise Refused("This is a sign-in page (a password box is showing). Sign in yourself on the "
                          "work PC - the bridge never clicks or types on it.")

    def _prepare(self, ref, snap, scroll=True, hit=True):
        try:
            n = int(ref)
        except (TypeError, ValueError):
            raise Refused(f"'{ref}' is not a number from the picture.")
        info = json.loads(self._js(f"window.__ctmsLib.prepare({n}, {json.dumps(str(snap or ''))}, "
                                   f"{'true' if scroll else 'false'}, {'true' if hit else 'false'})") or "{}")
        if not info.get("ok"):
            msg = WHY.get(info.get("why"), "Could not use [{n}].")
            raise Refused(msg.format(n=n, desc=info.get("desc", ""), by=info.get("by", "something")))
        info["desc"] = f"[{n}] {info.get('desc', '')}"
        return info

    def _focus(self):
        return json.loads(self._js("window.__ctmsLib.focusInfo()") or "{}")

    # ---- input ----
    def _mouse(self, x, y, clicks=1):
        call = self.ws.call
        call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"}, timeout=5)
        for n in range(1, clicks + 1):
            call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left",
                                              "buttons": 1, "clickCount": n}, timeout=8, abort=self._dialog_open)
            if self.dialog:
                return
            call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left",
                                              "buttons": 0, "clickCount": n}, timeout=8, abort=self._dialog_open)
            if self.dialog:
                return

    def _press(self, key, code, vk, text=None, mods=0):
        base = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                "modifiers": mods}
        down = dict(base, type="keyDown", text=text, unmodifiedText=text) if text else dict(base, type="rawKeyDown")
        self.ws.call("Input.dispatchKeyEvent", down, timeout=8, abort=self._dialog_open)
        if not self.dialog:
            self.ws.call("Input.dispatchKeyEvent", dict(base, type="keyUp"), timeout=8, abort=self._dialog_open)

    def _char(self, ch):
        if not ch.isascii():
            self.ws.call("Input.insertText", {"text": ch}, timeout=8, abort=self._dialog_open)
            return
        up = ch.upper()
        if "A" <= up <= "Z":
            code, vk = "Key" + up, ord(up)
        elif ch.isdigit():
            code, vk = "Digit" + ch, ord(ch)
        elif ch == " ":
            code, vk = "Space", 32
        else:
            code, vk = "", 0
        self._press(ch, code, vk, text=ch)

    def settle(self, max_wait=8.0, quiet=0.35):
        """Wait for the page to finish what the last action started: a page
        load, data still loading, a script still drawing. A dialog box ends
        the wait at once - it is the next thing to report."""
        t0, calm = time.time(), None
        time.sleep(0.15)
        while time.time() - t0 < max_wait:
            self.ws.drain()
            if self.dialog:
                return
            now = time.time()
            busy = bool(self.loading) or any(now - t < 15 for t in self.inflight.values())
            if not busy:
                try:
                    busy = self.ws.evaluate("document.readyState", timeout=3, abort=self._dialog_open) != "complete"
                except (TimeoutError, RuntimeError):
                    busy = True
            if busy:
                calm = None
            elif calm is None:
                calm = now
            elif now - calm >= quiet:
                return
            time.sleep(0.1)

    # ---- looking ----
    def see(self, marks=True, picture=True, quality=70, max_w=None):
        """The screen as Claude needs it: numbered things, a picture, the words."""
        out = {"dialog": self.dialog}
        if self.dialog:
            out["note"] = self._dialog_text()
            return out
        self.snap_no += 1
        sid = f"s{self.snap_no}"
        snap = json.loads(self._js(f"window.__ctmsLib.snapshot({json.dumps(sid)}, "
                                   f"{'true' if marks and picture else 'false'})", timeout=30) or "{}")
        ppc = None
        try:
            if picture:
                try:
                    data, view = grab(self.ws, "jpeg", max_w or self.SEE_MAX_W, quality, self.dialog)
                    w, h = jpeg_size(base64.b64decode(data))
                    out.update(img=data, img_w=w, img_h=h)
                    ppc = (w / view["w"]) if w and view.get("w") else None
                except RuntimeError as e:
                    out["picture_error"] = str(e)
        finally:
            if marks and picture:
                try:
                    self._js("window.__ctmsLib.unmark()", timeout=5)
                except Exception:
                    pass
        self.snap = {"id": sid, "ppc": ppc}
        try:
            text = self.ws.evaluate(cdp.TEXT_JS, timeout=20, abort=self._dialog_open) or ""
        except TimeoutError:
            text = ""
        out.update(snap=sid, url=snap.get("url", ""), title=snap.get("title", ""),
                   view={"w": snap.get("w"), "h": snap.get("h"), "dpr": snap.get("dpr")},
                   ppc=ppc, sign_in=bool(snap.get("signIn")), elements=snap.get("els") or [],
                   total=snap.get("total", 0), opaque=snap.get("opaque") or [],
                   focus=snap.get("focus") or "", text=text[:30000], dialog=self.dialog)
        return out

    # ---- acting ----
    def click(self, ref=None, at=None, snap=None, commit=False, double=False):
        self._check_page()
        if ref is not None:
            info = self._prepare(ref, snap)
        else:
            if not at or len(at) != 2:
                raise Refused("Give a number from the picture, or a point as x,y.")
            if not self.snap or self.snap["id"] != snap or not self.snap.get("ppc"):
                raise Refused("A point only makes sense against the latest picture - look again (see).")
            x, y = at[0] / self.snap["ppc"], at[1] / self.snap["ppc"]
            info = json.loads(self._js(f"window.__ctmsLib.probe({x:.1f}, {y:.1f})") or "{}")
            if not info.get("ok"):
                raise Refused("There is nothing at that point of the page.")
            info["desc"] = f"the point {int(at[0])},{int(at[1])} ({info.get('desc', '')})"
        if info.get("dis"):
            raise Refused(f"{info['desc']} is disabled - CTMS is not offering it right now.")
        if info.get("commit") and not commit:
            raise NeedsCommit(f"{info['desc']} looks like it would save, book, submit or delete something. "
                              f"Not clicked - ask Delali, and re-run with commit if he says go.")
        self._mouse(info["x"], info["y"], 2 if double else 1)
        self.settle()
        return ("Double-clicked " if double else "Clicked ") + info["desc"]

    def type_text(self, text, ref=None, snap=None, enter=False, append=False, paste=False, commit=False):
        text = str(text or "")
        self._check_page()
        if ref is not None:
            info = self._prepare(ref, snap)
            target = info["desc"]
            if info.get("pw"):
                raise Refused("That is a password box. The bridge never types into one - he signs in himself.")
            if not info.get("text"):
                raise Refused(f"{target} is not somewhere to type. Use click, or select for a dropdown.")
            if info.get("dis") or info.get("ro"):
                raise Refused(f"{target} is {'disabled' if info.get('dis') else 'read-only'} - CTMS will not take typing there.")
            self._mouse(info["x"], info["y"], 1)          # focus it the way a person does
            if self.dialog:
                return f"Clicked into {target}, and a dialog box opened"
            if not append:
                self._js(f"window.__ctmsLib.clearFor({int(ref)})")
        else:
            f = self._focus()
            if f.get("opaque"):
                raise Refused("The cursor is in a part of CTMS the bridge cannot read, so it cannot check "
                              "what it would be typing into. Give the field's number instead.")
            if f.get("none") or not f.get("text"):
                raise Refused("Nothing to type into has the cursor - give the field's number.")
            if f.get("pw"):
                raise Refused("The cursor is in a password box. The bridge never types into one.")
            target = f.get("desc") or "the field with the cursor"
        if "\n" in text or "\r" in text:
            raise Refused("No line breaks in typed text - use --enter to press Enter afterwards.")
        if paste:
            self.ws.call("Input.insertText", {"text": text}, timeout=10, abort=self._dialog_open)
        else:
            for ch in text:
                self._char(ch)
                if self.dialog:
                    break
        detail = f"Typed {json.dumps(text)} into {target}"
        if enter and not self.dialog:
            try:
                detail += "; then " + self.key("Enter", commit=commit, settle=False)
            except Refused as e:
                # the typing happened - say so, or the next try types it twice
                raise type(e)(f"{detail}, but did not press Enter: {e}")
        self.settle()
        return detail

    def key(self, combo, commit=False, settle=True):
        parts = [p.strip().lower() for p in str(combo or "").split("+") if p.strip()]
        if not parts:
            raise Refused("Which key?")
        name, mods = parts[-1], 0
        for m in parts[:-1]:
            if m not in MODS:
                raise Refused(f"'{m}' is not a modifier key (ctrl, shift, alt).")
            mods |= MODS[m]
        if "+".join(parts) in BLOCKED_KEYS or (name in ("v", "insert") and mods & 2) or (name == "insert" and mods & 8):
            raise Refused(f"{combo} is not allowed: it pastes from the work PC's clipboard, or acts on the "
                          f"browser rather than CTMS.")
        if name in KEYS:
            key, code, vk, text = KEYS[name]
        elif len(name) == 1 and name.isascii() and name.isprintable():
            key, code, vk, text = name, ("Key" + name.upper()) if name.isalpha() else "", ord(name.upper()), name
        else:
            raise Refused(f"'{combo}' is not a key the bridge knows.")
        if mods & (1 | 2 | 4):
            text = None                    # ctrl+a selects, it does not type an "a"
        self._check_page()
        if name in ("enter", "return", "space") and not mods & (1 | 2 | 4):
            f = self._focus()
            if f.get("pw"):
                raise Refused("The cursor is in a password box - that would be signing in. He does that himself.")
            risky = f.get("opaque") or (f.get("commit") and (name != "space" or f.get("button")))
            if risky and not commit:
                what = ("goes to a part of CTMS the bridge cannot read" if f.get("opaque")
                        else f.get("what") or f.get("desc", ""))
                raise NeedsCommit(f"{key} here {what} - that looks like it would save, book or submit. "
                                  f"Not pressed - ask Delali, and re-run with commit if he says go.")
        self._press(key, code, vk, text, mods)
        if settle:
            self.settle()
        return "Pressed " + "+".join(p.capitalize() for p in parts)

    def select(self, ref, option, snap=None, commit=False):
        self._check_page()
        info = self._prepare(ref, snap, hit=False)
        if not info.get("sel"):
            raise Refused(f"{info['desc']} is not a dropdown list - click it to open it, then click the option.")
        if info.get("dis"):
            raise Refused(f"{info['desc']} is disabled.")
        if info.get("commit") and not commit:
            raise NeedsCommit(f"Changing {info['desc']} looks like it would save or submit straight away. "
                              f"Not changed - ask Delali, and re-run with commit if he says go.")
        r = json.loads(self._js(f"window.__ctmsLib.choose({int(ref)}, {json.dumps(str(snap or ''))}, "
                                f"{json.dumps(str(option))})") or "{}")
        if not r.get("ok"):
            why = r.get("why")
            if why in ("ambiguous", "nooption"):
                raise Refused(f"{info['desc']} has {'more than one' if why == 'ambiguous' else 'no'} option matching "
                              f"\"{option}\". Options: " + " | ".join(r.get("options") or []))
            raise Refused(WHY.get(why, "Could not change [{n}].").format(n=ref, desc="", by=""))
        self.settle()
        return f"Chose \"{r.get('chosen')}\" in {info['desc']}"

    def scroll(self, direction="down", amount=None, ref=None, snap=None):
        direction = (direction or "down").lower()
        if direction == "to":
            if ref is None:
                raise Refused("scroll to needs a number.")
            info = self._prepare(ref, snap, scroll=True, hit=False)
            time.sleep(0.3)
            return f"Scrolled {info['desc']} into view"
        if direction not in ("up", "down", "left", "right"):
            raise Refused("Scroll up, down, left, right - or to a number.")
        view = json.loads(self.ws.evaluate(cdp.VIEW_JS, timeout=8, abort=self._dialog_open) or "{}")
        w, h = view.get("w") or 800, view.get("h") or 600
        x, y = w / 2, h / 2
        if ref is not None:
            info = self._prepare(ref, snap, scroll=False, hit=False)
            x, y = info["x"], info["y"]
        size = int(amount) if amount else int((h if direction in ("up", "down") else w) * 0.8)
        dx = {"left": -size, "right": size}.get(direction, 0)
        dy = {"up": -size, "down": size}.get(direction, 0)
        self.ws.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y,
                                                  "deltaX": dx, "deltaY": dy}, timeout=8)
        time.sleep(0.45)                        # smooth scrolling takes a moment
        return f"Scrolled {direction} {size}px"

    def hover(self, ref, snap=None):
        info = self._prepare(ref, snap)
        self.ws.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": info["x"], "y": info["y"],
                                                  "button": "none"}, timeout=5)
        self.settle(max_wait=2)
        return f"Pointed at {info['desc']}"

    def _current_url(self):
        return str(self.ws.evaluate("location.href", timeout=8, abort=self._dialog_open) or "")

    def goto(self, url, commit=False):
        if self.dialog:
            raise Refused(self._dialog_text())
        cur = self._current_url()
        target = urljoin(cur, str(url or "").strip())
        t, c = urlsplit(target), urlsplit(cur)
        if t.scheme not in ("http", "https"):
            raise Refused("goto only opens CTMS web pages.")
        if (t.hostname or "").lower() != (c.hostname or "").lower():
            raise Refused(f"goto stays on the CTMS site ({c.hostname or '?'}) - not {t.hostname or '?'}.")
        sig = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", t.path + " " + t.query)
        if re.search(r"\b(book|save|submit|confirm|delete|remove|send|cancel|commit|update)\b",
                     re.sub(r"[_\-./=?&]+", " ", sig), re.I) and not commit:
            raise NeedsCommit("That address looks like it does something (save, book, delete...) rather "
                              "than just showing a page. Not opened - ask Delali, and re-run with commit.")
        self.ws.call("Page.navigate", {"url": target}, timeout=30)
        self.settle(max_wait=20)
        return "Opened " + target

    def history(self, step, commit=False):
        if self.dialog:
            raise Refused(self._dialog_text())
        h = self.ws.call("Page.getNavigationHistory", timeout=8)
        entries, i = h.get("entries") or [], int(h.get("currentIndex") or 0) + step
        if not 0 <= i < len(entries):
            raise Refused("There is nothing to go " + ("back" if step < 0 else "forward") + " to.")
        e = entries[i]
        if e.get("transitionType") == "form_submit" and not commit:
            raise NeedsCommit("That page was the answer to a submitted form - going to it again can send "
                              "the form again. Not done - ask Delali, and re-run with commit.")
        self.ws.call("Page.navigateToHistoryEntry", {"entryId": e["id"]}, timeout=15)
        self.settle(max_wait=15)
        return ("Went back to " if step < 0 else "Went forward to ") + (e.get("title") or "the previous page")

    def reload(self, commit=False):
        if self.dialog:
            raise Refused(self._dialog_text())
        h = self.ws.call("Page.getNavigationHistory", timeout=8)
        entries, i = h.get("entries") or [], int(h.get("currentIndex") or 0)
        if 0 <= i < len(entries) and entries[i].get("transitionType") == "form_submit" and not commit:
            raise NeedsCommit("This page is the answer to a submitted form - reloading it can send the "
                              "form again (a second booking). Not reloaded - ask Delali first.")
        self.ws.call("Page.reload", {}, timeout=15)
        self.settle(max_wait=20)
        return "Reloaded the page"

    def answer_dialog(self, accept, text=None, commit=False):
        d = self.dialog
        if not d:
            raise Refused("No dialog box is open.")
        if accept and d.get("type") != "alert" and not commit:
            raise NeedsCommit(f"OK on \"{d.get('message', '')[:160]}\" would go ahead with it. Not answered - "
                              f"ask Delali, and re-run with commit if he says go (or dismiss it).")
        params = {"accept": bool(accept)}
        if accept and text is not None and d.get("type") == "prompt":
            params["promptText"] = str(text)
        self.ws.call("Page.handleJavaScriptDialog", params, timeout=10)
        self.dialog = None
        self.settle()
        return f"{'Pressed OK on' if accept else 'Dismissed'} the {d.get('type')} box \"{d.get('message', '')[:120]}\""

    def wait(self, seconds=None, text=None, timeout=10):
        if text:
            limit = min(float(timeout or 10), 60)
            deadline = time.time() + limit
            while time.time() < deadline:
                self.ws.drain()
                if self.dialog:
                    return "A dialog box opened while waiting"
                page = self.ws.evaluate(cdp.TEXT_JS, timeout=10, abort=self._dialog_open) or ""
                if str(text).lower() in page.lower():
                    return f"\"{text}\" is on the page"
                time.sleep(0.5)
            raise Refused(f"\"{text}\" did not appear within {limit:g}s.")
        s = min(max(float(seconds or 2), 0.0), 30.0)
        time.sleep(s)
        self.ws.drain()
        return f"Waited {s:g}s"
