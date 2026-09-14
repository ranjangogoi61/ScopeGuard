"""ScopeGuard web application.

One page, server-rendered, no build step and no JavaScript framework - partly
because it keeps the failure surface small, and partly because this project was
built entirely from an Android phone, where `npm run build` is not an option.
"""

import html
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import agent
import store

app = FastAPI(title="ScopeGuard", docs_url=None, redoc_url=None)

LAST_CYCLE = {"at": None, "result": None}


@app.on_event("startup")
def _startup():
    store.init_db(force_reseed=False)


# --------------------------------------------------------------------------
# Presentation helpers
# --------------------------------------------------------------------------

def e(s):
    return html.escape(str(s or ""))


CSS = """
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#15181d; --muted:#6b7280; --line:#e3e6ea;
  --accent:#1f5eff; --warn:#b45309; --warnbg:#fffbeb; --warnline:#f5d98e;
  --ok:#0f7b56; --okbg:#ecfdf5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:20px 16px 64px}
header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:21px;margin:0;letter-spacing:-.02em}
.badge{font-size:11px;font-weight:600;padding:3px 8px;border-radius:999px;
 background:#eef1f5;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tagline{color:var(--muted);font-size:14px;margin:0 0 18px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat .n{font-size:22px;font-weight:650;letter-spacing:-.02em}
.stat .l{font-size:12px;color:var(--muted);margin-top:2px}
.stat.hero .n{color:var(--accent)}
.bar{display:flex;gap:8px;align-items:center;margin-bottom:22px;flex-wrap:wrap}
button,.btn{font:inherit;font-weight:560;border-radius:8px;border:1px solid var(--line);
 background:var(--card);color:var(--ink);padding:9px 14px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.approve{background:var(--ok);border-color:var(--ok);color:#fff}
.small{font-size:13px;color:var(--muted)}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
 margin:26px 0 10px;font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:16px;margin-bottom:14px}
.card.alert{border-color:var(--warnline)}
.who{font-weight:620;margin-bottom:2px}
.msg{background:#f2f4f7;border-radius:8px;padding:12px;margin:10px 0;
 font-size:14px;white-space:pre-wrap}
.clause{background:var(--warnbg);border:1px solid var(--warnline);border-left:3px solid var(--warn);
 border-radius:8px;padding:12px;margin:12px 0}
.clause .k{font-size:11px;font-weight:700;color:var(--warn);text-transform:uppercase;
 letter-spacing:.05em;margin-bottom:4px}
.clause .t{font-size:14px}
.price{display:flex;justify-content:space-between;align-items:baseline;
 border-top:1px solid var(--line);border-bottom:1px solid var(--line);
 padding:10px 0;margin:12px 0}
.price .amt{font-size:20px;font-weight:650;letter-spacing:-.02em}
.draft{border:1px dashed var(--line);border-radius:8px;padding:12px;font-size:14px;
 white-space:pre-wrap;background:#fcfcfd}
.actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
details{margin-top:12px}
summary{cursor:pointer;font-size:13px;color:var(--accent);font-weight:560}
.trace{margin-top:10px;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
 background:#0f1115;color:#d7dce3;border-radius:8px;padding:12px;overflow-x:auto}
.trace .tn{color:#7fb4ff}
.trace .tr{color:#9aa6b2}
.logrow{display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.logrow:last-child{border-bottom:0}
.pill{flex:none;font-size:11px;font-weight:650;padding:2px 7px;border-radius:5px;height:fit-content}
.pill.escalate{background:var(--warnbg);color:var(--warn)}
.pill.stood_down{background:#eef2ff;color:#4338ca}
.pill.routine{background:#f2f4f7;color:var(--muted)}
.empty{color:var(--muted);font-size:14px;padding:18px;text-align:center;
 background:var(--card);border:1px dashed var(--line);border-radius:12px}
textarea{width:100%;font:inherit;padding:10px;border:1px solid var(--line);
 border-radius:8px;min-height:120px}
footer{margin-top:34px;color:var(--muted);font-size:12.5px;line-height:1.7}
"""


def trim(text, limit):
    """Truncate on a word boundary so the log never cuts mid-word."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "…"


def money(cur, amt):
    sym = {"USD": "$", "INR": "₹", "GBP": "£", "EUR": "€"}.get(cur or "USD", "")
    return f"{sym}{amt:,.0f}"


def render_trace(trace):
    if not trace:
        return ""
    rows = []
    for i, t in enumerate(trace, 1):
        args = ", ".join(f"{k}={v}" for k, v in (t.get("args") or {}).items())
        rows.append(
            f'<div>{i}. <span class="tn">{e(t["tool"])}</span>({e(args)})<br>'
            f'&nbsp;&nbsp;&nbsp;<span class="tr">→ {e(t["result"])}</span></div>')
    return ('<details><summary>Show the agent\'s working '
            f'({len(trace)} tool calls)</summary>'
            f'<div class="trace">{"".join(rows)}</div></details>')


def render_card(d):
    import json as _json
    trace = _json.loads(d.get("tool_trace") or "[]")
    cur = "USD"
    amt = d.get("amount") or 0
    clause = ""
    if d.get("clause_cited"):
        clause = (f'<div class="clause"><div class="k">Conflicts with SOW clause '
                  f'{e(d["clause_cited"])}</div><div class="t">"{e(d["clause_text"])}"</div></div>')
    price = ""
    if amt:
        price = (f'<div class="price"><span class="small">Change order · '
                 f'{e(d.get("estimated_hours"))} hours estimated</span>'
                 f'<span class="amt">{money(cur, amt)}</span></div>')
    draft = f'<div class="draft">{e(d.get("draft"))}</div>' if d.get("draft") else ""
    return f"""
    <div class="card alert">
      <div class="who">{e(d['client_name'])} <span class="small">· {e(d['sender'])}</span></div>
      <div class="small">Confidence {float(d['confidence']):.0%} · verified by second agent</div>
      <div class="msg">{e(d['message_body'])}</div>
      {clause}
      <div class="small">{e(d['reasoning'])}</div>
      {price}
      {draft}
      <form method="post" action="/decision/{d['id']}/approve" class="actions">
        <button class="approve" type="submit">Approve &amp; send</button>
        <a class="btn" href="/decision/{d['id']}/edit">Edit</a>
        <button formaction="/decision/{d['id']}/dismiss" type="submit">Dismiss</button>
      </form>
      {render_trace(trace)}
    </div>"""


def page(body):
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ScopeGuard</title><style>{CSS}</style></head><body><div class="wrap">{body}</div></body></html>"""


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard():
    s = store.stats()
    pending = store.pending_decisions()
    log = store.decision_log(25)

    cards = "".join(render_card(d) for d in pending) if pending else (
        '<div class="empty">Nothing needs you right now.<br>'
        'ScopeGuard is watching and will interrupt only when a real decision appears.</div>')

    rows = []
    for d in log:
        label = {"escalate": "escalated", "stood_down": "stood down",
                 "routine": "handled quietly"}.get(d["action"], d["action"])
        rows.append(
            f'<div class="logrow"><span class="pill {e(d["action"])}">{e(label)}</span>'
            f'<span><b>{e(d["client_name"])}</b> — {e(trim(d["reasoning"], 190))}</span></div>')
    logs = "".join(rows) or '<div class="small">No cycles run yet.</div>'

    last = LAST_CYCLE["at"] or "never"
    ready = agent.provider_ready()
    warn = "" if ready else (
        '<div class="clause"><div class="k">Model provider not configured</div>'
        '<div class="t">Set GEMINI_API_KEY in the environment and run a cycle.</div></div>')

    return page(f"""
<header><h1>ScopeGuard</h1><span class="badge">Demo data</span></header>
<p class="tagline">ScopeGuard decides what deserves your attention.
You decide what gets said.</p>
{warn}
<div class="stats">
  <div class="stat"><div class="n">{s['processed']}</div><div class="l">messages processed</div></div>
  <div class="stat"><div class="n">{s['quiet']}</div><div class="l">handled without you</div></div>
  <div class="stat hero"><div class="n">{s['pending']}</div><div class="l">needs you</div></div>
  <div class="stat"><div class="n">{money('USD', s['protected'])}</div><div class="l">value protected</div></div>
</div>
<form method="post" action="/cycle" class="bar">
  <button class="primary" type="submit">Run cycle now</button>
  <span class="small">Runs automatically every 10 minutes · last run: {e(last)}</span>
</form>
<h2>Needs your decision</h2>
{cards}
<h2>Decision log</h2>
<div class="card">{logs}</div>
<footer>
  Two Strands agents reason about every message: <b>ScopeAnalyst</b> reads the signed
  scope of work and cites the clause a request breaches; <b>Verifier</b> argues against
  escalating, so the queue stays quiet. Pricing is deterministic Python, never model
  arithmetic. Nothing is ever sent without a human pressing approve.<br><br>
  Demo dataset. Inbox and outbound sending are adapter interfaces — see the README
  for exactly what is real and what is stubbed.
</footer>""")


@app.post("/cycle")
def cycle():
    res = agent.run_cycle()
    LAST_CYCLE["at"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
    LAST_CYCLE["result"] = res
    return RedirectResponse("/", status_code=303)


@app.get("/decision/{did}/edit", response_class=HTMLResponse)
def edit_form(did: int):
    d = store.get_decision(did)
    if not d:
        return RedirectResponse("/", status_code=303)
    return page(f"""
<header><h1>Edit reply</h1></header>
<div class="card">
  <div class="who">{e(d['client_name'])}</div>
  <div class="msg">{e(d['message_body'])}</div>
  <form method="post" action="/decision/{did}/edit">
    <textarea name="draft">{e(d.get('draft'))}</textarea>
    <div class="actions">
      <button class="approve" type="submit">Save &amp; approve</button>
      <a class="btn" href="/">Cancel</a>
    </div>
  </form>
  <div class="small" style="margin-top:10px">Your edit is stored as a voice sample so
  future drafts sound more like you.</div>
</div>""")


@app.post("/decision/{did}/edit")
def edit_save(did: int, draft: str = Form(...)):
    d = store.get_decision(did)
    if d:
        if draft.strip() != (d.get("draft") or "").strip():
            store.save_voice_sample(d["client_id"], d.get("draft") or "", draft)
        store.set_decision_status(did, "approved", draft=draft)
        store.log_audit("approved", f"Human edited and approved reply to {d['client_name']}.")
    return RedirectResponse("/", status_code=303)


@app.post("/decision/{did}/approve")
def approve(did: int):
    d = store.get_decision(did)
    if d:
        store.set_decision_status(did, "approved")
        store.log_audit("approved", f"Human approved the change order reply to {d['client_name']}.")
    return RedirectResponse("/", status_code=303)


@app.post("/decision/{did}/dismiss")
def dismiss(did: int):
    d = store.get_decision(did)
    if d:
        store.set_decision_status(did, "dismissed")
        store.log_audit("dismissed", f"Human dismissed the escalation for {d['client_name']}.")
    return RedirectResponse("/", status_code=303)


@app.get("/healthz")
def healthz():
    """Self-diagnostic. Exists so that a failure at 3am costs one message, not three."""
    try:
        s = store.stats()
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        s, db_ok = {"error": str(exc)}, False
    return JSONResponse({
        "status": "ok" if db_ok and agent.provider_ready() else "degraded",
        "database": "ok" if db_ok else "error",
        "model_provider": os.environ.get("SCOPEGUARD_PROVIDER", "gemini"),
        "provider_credentials": "present" if agent.provider_ready() else "MISSING",
        "last_cycle": LAST_CYCLE["at"],
        "last_cycle_result": LAST_CYCLE["result"],
        "stats": s,
    })
