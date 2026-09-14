"""SQLite persistence and demo seed data for ScopeGuard.

Render's free tier uses an ephemeral filesystem, so the database is re-seeded
on every boot. That is deliberate: the demo is deterministic and a judge who
opens the live link three weeks from now sees exactly what the video showed.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("SCOPEGUARD_DB", "/tmp/scopeguard.db")


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project TEXT NOT NULL,
    hourly_rate REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    payment_behaviour TEXT NOT NULL,      -- prompt | slow | disputes
    relationship_note TEXT
);

CREATE TABLE IF NOT EXISTS sows (
    client_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    deliverables TEXT NOT NULL,           -- JSON: [{clause, text}]
    exclusions TEXT NOT NULL,             -- JSON: [{clause, text}]
    revision_policy TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    body TEXT NOT NULL,
    received_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    client_id TEXT NOT NULL,
    action TEXT NOT NULL,                 -- escalate | stood_down | routine
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    clause_cited TEXT,
    clause_text TEXT,
    estimated_hours REAL,
    amount REAL,
    draft TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | dismissed | logged
    tool_trace TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    original TEXT NOT NULL,
    edited TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_audit(event, detail):
    with conn() as c:
        c.execute(
            "INSERT INTO audit (event, detail, created_at) VALUES (?,?,?)",
            (event, detail, now_iso()),
        )


# --------------------------------------------------------------------------
# Demo dataset
# --------------------------------------------------------------------------
# Twelve messages across three clients. Exactly one is a clear scope breach,
# one is a borderline request the Verifier is expected to stand down, and the
# remaining ten are routine traffic that proves the noise filter works.

CLIENTS = [
    ("meridian", "Meridian Studios", "Marketing site redesign", 85.0, "USD",
     "prompt", "Pays within 7 days. Good long-term relationship, two prior projects."),
    ("halcyon", "Halcyon Foods", "Brand refresh + packaging", 75.0, "USD",
     "disputes", "Has disputed two invoices before. Needs everything documented in writing."),
    ("northwind", "Northwind Legal", "Website maintenance retainer", 95.0, "USD",
     "slow", "Pays around day 45. Low-touch client, rarely asks for extras."),
]

SOWS = [
    ("meridian", "Meridian Studios - Marketing Site Redesign",
     [
         {"clause": "2.1", "text": "Design and build of five (5) page templates: Home, About, Services, Case Studies, Contact."},
         {"clause": "2.2", "text": "Responsive layouts for desktop, tablet and mobile breakpoints."},
         {"clause": "2.3", "text": "Integration with the client's existing contact form provider."},
     ],
     [
         {"clause": "3.2", "text": "Blog, news or any content-management functionality is expressly excluded from this agreement and is not covered by the fixed fee."},
         {"clause": "3.3", "text": "E-commerce, payment processing and user account systems are excluded."},
         {"clause": "3.4", "text": "Ongoing hosting, maintenance and content population are excluded."},
     ],
     "Two (2) rounds of minor revisions per template are included. Minor revisions cover copy edits, colour adjustments and image swaps within an approved layout."),

    ("halcyon", "Halcyon Foods - Brand Refresh",
     [
         {"clause": "2.1", "text": "Primary logo, secondary lockup and one monogram mark."},
         {"clause": "2.2", "text": "Colour palette, typography system and a 12-page brand guidelines PDF."},
         {"clause": "2.3", "text": "Packaging artwork for three (3) SKUs."},
     ],
     [
         {"clause": "3.1", "text": "Additional SKUs beyond the three specified are billed separately at the standard hourly rate."},
         {"clause": "3.2", "text": "Motion graphics, animation and video assets are excluded."},
     ],
     "Three (3) rounds of revisions are included per deliverable. Revisions cover colour, spacing, scale and typographic adjustments to an approved concept."),

    ("northwind", "Northwind Legal - Maintenance Retainer",
     [
         {"clause": "2.1", "text": "Up to eight (8) hours per month of site maintenance, security patching and content updates."},
         {"clause": "2.2", "text": "Monthly uptime and performance report."},
     ],
     [
         {"clause": "3.1", "text": "New feature development and redesign work are excluded from the retainer."},
     ],
     "Retainer hours do not roll over. Work beyond eight hours per month is quoted separately."),
]

MESSAGES = [
    # --- routine noise -----------------------------------------------------
    ("meridian", "Dana Whitfield", "Morning! Just confirming we're still on for the Thursday review call at 3pm.", 0),
    ("meridian", "Dana Whitfield", "Logo files received, thanks. The SVG works perfectly on our end.", 0),
    ("northwind", "Alan Reyes", "Received the uptime report for August. All looks good, nothing needed from us.", 0),
    ("halcyon", "Priya Raman", "Quick note - our office is closed Monday for a public holiday, so expect slower replies.", 0),
    ("meridian", "Dana Whitfield", "Could you resend the invoice PDF? It got buried in my inbox.", 0),
    ("northwind", "Alan Reyes", "Approving the security patch schedule you proposed. Go ahead whenever suits you.", 0),
    ("halcyon", "Priya Raman", "The packaging proofs look great. Sending them to print this week.", 0),
    ("meridian", "Dana Whitfield", "Can you make the hero headline a slightly darker shade of navy? Feels a bit washed out.", 0),
    ("northwind", "Alan Reyes", "No updates needed this month. Speak in September.", 0),
    ("halcyon", "Priya Raman", "Thanks for the quick turnaround on the monogram.", 0),

    # --- the borderline case the Verifier should stand down ---------------
    ("halcyon", "Priya Raman",
     "One small thing - on the secondary lockup, could we try a slightly wider letter-spacing and "
     "bump the mark up a few pixels? Just want to see it before we lock the guidelines.", 0),

    # --- the clear scope breach: the hero of the demo ----------------------
    ("meridian", "Dana Whitfield",
     "Quick one before we go live - can you also add a blog section? Nothing fancy, just a listing "
     "page and article template so marketing can publish updates themselves. Should be simple since "
     "the design system is already built. Hoping to have it for the launch.", 0),
]


def init_db(force_reseed=False):
    """Create the schema and seed demo data if the database is empty.

    Render's free tier has an ephemeral filesystem, so a cold start produces a
    freshly seeded database automatically. Within a running instance state is
    preserved, so a judge who approves a change order does not lose it.
    """
    if force_reseed and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with conn() as c:
        c.executescript(SCHEMA)
        row = c.execute("SELECT COUNT(*) n FROM clients").fetchone()
        if row["n"]:
            return
        for cl in CLIENTS:
            c.execute(
                "INSERT INTO clients (id,name,project,hourly_rate,currency,payment_behaviour,relationship_note)"
                " VALUES (?,?,?,?,?,?,?)", cl)
        for cid, title, deliv, excl, rev in SOWS:
            c.execute(
                "INSERT INTO sows (client_id,title,deliverables,exclusions,revision_policy)"
                " VALUES (?,?,?,?,?)",
                (cid, title, json.dumps(deliv), json.dumps(excl), rev))
        for cid, sender, body, proc in MESSAGES:
            c.execute(
                "INSERT INTO messages (client_id,sender,body,received_at,processed)"
                " VALUES (?,?,?,?,?)", (cid, sender, body, now_iso(), proc))
    log_audit("system", "Database initialised with demo dataset (3 clients, 12 messages).")


# --------------------------------------------------------------------------
# Read helpers used by the agent tools
# --------------------------------------------------------------------------

def get_sow(client_id):
    with conn() as c:
        r = c.execute("SELECT * FROM sows WHERE client_id=?", (client_id,)).fetchone()
        if not r:
            return None
        return {
            "title": r["title"],
            "deliverables": json.loads(r["deliverables"]),
            "exclusions": json.loads(r["exclusions"]),
            "revision_policy": r["revision_policy"],
        }


def get_client(client_id):
    with conn() as c:
        r = c.execute("SELECT * FROM clients WHERE client_id=?".replace("client_id", "id"),
                      (client_id,)).fetchone()
        return dict(r) if r else None


def unprocessed_messages(limit=20):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE processed=0 ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def mark_processed(message_id):
    with conn() as c:
        c.execute("UPDATE messages SET processed=1 WHERE id=?", (message_id,))


def save_decision(d):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO decisions (message_id,client_id,action,confidence,reasoning,"
            "clause_cited,clause_text,estimated_hours,amount,draft,status,tool_trace,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d["message_id"], d["client_id"], d["action"], d["confidence"], d["reasoning"],
             d.get("clause_cited"), d.get("clause_text"), d.get("estimated_hours"),
             d.get("amount"), d.get("draft"),
             "pending" if d["action"] == "escalate" else "logged",
             json.dumps(d.get("tool_trace", [])), now_iso()))
        return cur.lastrowid


def pending_decisions():
    with conn() as c:
        rows = c.execute(
            "SELECT d.*, c.name AS client_name, m.body AS message_body, m.sender AS sender "
            "FROM decisions d JOIN clients c ON c.id=d.client_id "
            "JOIN messages m ON m.id=d.message_id "
            "WHERE d.status='pending' ORDER BY d.id DESC").fetchall()
        return [dict(r) for r in rows]


def decision_log(limit=40):
    with conn() as c:
        rows = c.execute(
            "SELECT d.*, c.name AS client_name, m.body AS message_body "
            "FROM decisions d JOIN clients c ON c.id=d.client_id "
            "JOIN messages m ON m.id=d.message_id "
            "ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_decision(decision_id):
    with conn() as c:
        r = c.execute(
            "SELECT d.*, c.name AS client_name, c.currency AS currency, m.body AS message_body "
            "FROM decisions d JOIN clients c ON c.id=d.client_id "
            "JOIN messages m ON m.id=d.message_id WHERE d.id=?", (decision_id,)).fetchone()
        return dict(r) if r else None


def set_decision_status(decision_id, status, draft=None):
    with conn() as c:
        if draft is not None:
            c.execute("UPDATE decisions SET status=?, draft=? WHERE id=?",
                      (status, draft, decision_id))
        else:
            c.execute("UPDATE decisions SET status=? WHERE id=?", (status, decision_id))


def save_voice_sample(client_id, original, edited):
    with conn() as c:
        c.execute(
            "INSERT INTO voice_samples (client_id,original,edited,created_at) VALUES (?,?,?,?)",
            (client_id, original, edited, now_iso()))


def stats():
    with conn() as c:
        processed = c.execute("SELECT COUNT(*) n FROM messages WHERE processed=1").fetchone()["n"]
        escalated = c.execute(
            "SELECT COUNT(*) n FROM decisions WHERE action='escalate'").fetchone()["n"]
        stood_down = c.execute(
            "SELECT COUNT(*) n FROM decisions WHERE action='stood_down'").fetchone()["n"]
        protected = c.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM decisions WHERE action='escalate'").fetchone()["s"]
        pending = c.execute(
            "SELECT COUNT(*) n FROM decisions WHERE status='pending'").fetchone()["n"]
        return {
            "processed": processed,
            "quiet": max(processed - escalated, 0),
            "escalated": escalated,
            "stood_down": stood_down,
            "protected": protected or 0.0,
            "pending": pending,
        }


def audit_log(limit=30):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
