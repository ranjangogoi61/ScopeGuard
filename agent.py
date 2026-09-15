"""ScopeGuard agent layer, built on the Strands Agents SDK.

Three specialised agents, each with one responsibility, one tool chain and
one typed output:

    ScopeAnalyst  - reads the signed SOW and decides whether an incoming
                    request falls outside it, citing the specific clause.
    Verifier      - argues AGAINST escalating. It exists because the real
                    failure mode of this product is crying wolf, not missing
                    a breach. If the request is covered by a general clause,
                    the escalation is suppressed.
    Drafter       - writes the reply in the freelancer's voice, calibrated by
                    the client's payment history.

Orchestration is deterministic Python. The agents do the reasoning; the
control flow does not, because a scope decision should be reproducible.
Change-order pricing is plain arithmetic in a tool - never model arithmetic.
"""

import json
import os
import threading

from pydantic import BaseModel, Field
from strands import Agent, tool

import store

# --------------------------------------------------------------------------
# Tool-invocation trace
# --------------------------------------------------------------------------
# Every tool call is recorded so the UI can show exactly what the agent did to
# reach a decision. This is what makes the agent inspectable rather than a
# black box that emits text.

_local = threading.local()


def _trace_reset():
    _local.trace = []


def _trace_add(tool_name, args, result_summary):
    if not hasattr(_local, "trace"):
        _local.trace = []
    _local.trace.append({
        "tool": tool_name,
        "args": args,
        "result": result_summary,
    })


def _trace_get():
    return list(getattr(_local, "trace", []))


# --------------------------------------------------------------------------
# Typed outputs
# --------------------------------------------------------------------------

class ScopeVerdict(BaseModel):
    out_of_scope: bool = Field(description="True if the request is not covered by the signed SOW")
    confidence: float = Field(description="Confidence between 0.0 and 1.0")
    clause_cited: str = Field(description="The SOW clause number that excludes this work, e.g. '3.2'. Empty string if in scope.")
    clause_text: str = Field(description="The exact text of the cited clause. Empty string if in scope.")
    reasoning: str = Field(description="Two sentences maximum explaining the decision.")
    estimated_hours: float = Field(description="Estimated hours of additional work. 0 if in scope.")


class VerifierVerdict(BaseModel):
    agrees_with_escalation: bool = Field(description="False if this should NOT be escalated to the human")
    counter_argument: str = Field(description="The strongest argument that this request is actually covered by the agreement.")
    confidence: float = Field(description="Confidence in this verdict between 0.0 and 1.0")


class DraftOutput(BaseModel):
    message: str = Field(description="The reply to the client. Warm, professional, under 150 words.")
    tone_used: str = Field(description="One of: warm, warm-firm, firm-documented")


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

@tool
def get_scope_of_work(client_id: str) -> str:
    """Retrieve the signed scope of work for a client, including deliverables,
    exclusions with clause numbers, and the revision policy."""
    sow = store.get_sow(client_id)
    if not sow:
        _trace_add("get_scope_of_work", {"client_id": client_id}, "no SOW found")
        return "No scope of work on file for this client."
    _trace_add("get_scope_of_work", {"client_id": client_id},
               f"{sow['title']} - {len(sow['deliverables'])} deliverables, {len(sow['exclusions'])} exclusions")
    lines = [f"SCOPE OF WORK: {sow['title']}", "", "DELIVERABLES (included):"]
    for d in sow["deliverables"]:
        lines.append(f"  Clause {d['clause']}: {d['text']}")
    lines.append("")
    lines.append("EXCLUSIONS (not included):")
    for e in sow["exclusions"]:
        lines.append(f"  Clause {e['clause']}: {e['text']}")
    lines.append("")
    lines.append(f"REVISION POLICY: {sow['revision_policy']}")
    return "\n".join(lines)


@tool
def get_client_context(client_id: str) -> str:
    """Retrieve the client's rate, payment behaviour and relationship history.
    Payment behaviour is used to calibrate how firm the reply should be."""
    c = store.get_client(client_id)
    if not c:
        _trace_add("get_client_context", {"client_id": client_id}, "not found")
        return "No client record found."
    _trace_add("get_client_context", {"client_id": client_id},
               f"{c['name']}, rate {c['currency']} {c['hourly_rate']}/hr, pays: {c['payment_behaviour']}")
    return (
        f"CLIENT: {c['name']}\n"
        f"PROJECT: {c['project']}\n"
        f"RATE: {c['currency']} {c['hourly_rate']} per hour\n"
        f"PAYMENT BEHAVIOUR: {c['payment_behaviour']}\n"
        f"RELATIONSHIP: {c['relationship_note']}"
    )


@tool
def calculate_change_order(client_id: str, estimated_hours: float) -> str:
    """Calculate the price of a change order. Deterministic arithmetic -
    the model must never compute pricing itself."""
    c = store.get_client(client_id)
    if not c:
        return "Unknown client."
    amount = round(float(estimated_hours) * float(c["hourly_rate"]), 2)
    _trace_add("calculate_change_order",
               {"client_id": client_id, "estimated_hours": estimated_hours},
               f"{c['currency']} {amount:,.2f} ({estimated_hours}h x {c['hourly_rate']})")
    return f"{estimated_hours} hours x {c['currency']} {c['hourly_rate']}/hr = {c['currency']} {amount:,.2f}"


# --------------------------------------------------------------------------
# Model provider
# --------------------------------------------------------------------------
# Primary: Google Gemini via Strands' LiteLLM provider. Free tier, no card,
# 1,500 requests/day - which comfortably covers a three-and-a-half week
# judging window without the demo dying halfway through.
#
# Also supported: Amazon Bedrock. Set SCOPEGUARD_PROVIDER=bedrock and supply
# AWS credentials; Strands defaults to Bedrock natively. Gemini is the default
# here only because it needs no payment method, which matters when the person
# building this does not have one.

def build_model():
    provider = os.environ.get("SCOPEGUARD_PROVIDER", "gemini").lower()

    if provider == "bedrock":
        from strands.models import BedrockModel
        return BedrockModel(
            model_id=os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        ), "amazon-bedrock"

    from strands.models.litellm import LiteLLMModel
    api_key = os.environ.get("GEMINI_API_KEY", "")
    model_id = os.environ.get("GEMINI_MODEL_ID", DEFAULT_GEMINI_MODEL)
    return LiteLLMModel(
        client_args={"api_key": api_key},
        model_id=model_id,
        params={"temperature": 0.2, "max_tokens": 1200},
    ), model_id


# Candidate models, tried in order by /selftest. Google retires older Gemini
# model ids over time, so the deployment should not hard-depend on one name.
DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL_ID", "gemini/gemini-2.5-flash")

CANDIDATE_MODELS = [
    "gemini/gemini-2.5-flash",
    "gemini/gemini-2.0-flash",
    "gemini/gemini-2.5-flash-lite",
    "gemini/gemini-1.5-flash",
]


def try_model(model_id: str) -> dict:
    """Make one trivial call against a model id and report what happened."""
    from strands.models.litellm import LiteLLMModel
    api_key = os.environ.get("GEMINI_API_KEY", "")
    try:
        m = LiteLLMModel(
            client_args={"api_key": api_key},
            model_id=model_id,
            params={"temperature": 0, "max_tokens": 32},
        )
        a = Agent(model=m, system_prompt="Reply with exactly one word.",
                  callback_handler=None)
        r = a("Say OK")
        return {"model": model_id, "ok": True, "reply": str(r)[:80]}
    except Exception as exc:  # noqa: BLE001
        return {"model": model_id, "ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def provider_ready():
    provider = os.environ.get("SCOPEGUARD_PROVIDER", "gemini").lower()
    if provider == "bedrock":
        return bool(os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"))
    return bool(os.environ.get("GEMINI_API_KEY"))


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------

SCOPE_ANALYST_PROMPT = """You are ScopeAnalyst, a contract analyst working for a freelancer.

You are given an incoming client message. Your only job is to decide whether the
request falls OUTSIDE the signed scope of work.

Always call get_scope_of_work first to read the actual agreement before deciding.

Rules:
- A request is OUT OF SCOPE only if it asks for work that the deliverables do not
  cover, or that an exclusion clause explicitly names.
- Cosmetic adjustments to already-approved work (colour, spacing, copy edits,
  image swaps, letter-spacing, small positional nudges) are IN SCOPE when the
  revision policy allows revisions. Do not flag these.
- Scheduling notes, thanks, confirmations, invoice queries and general chat are
  IN SCOPE. They are not requests for work at all.
- If out of scope, cite the exact clause number and quote its text verbatim.
- Estimate the additional hours realistically for a professional doing this work.

Be conservative. A false alarm costs the freelancer a client relationship."""

VERIFIER_PROMPT = """You are Verifier. ScopeAnalyst has flagged a client request as
outside the signed scope of work and wants to interrupt the freelancer about it.

Your job is to argue AGAINST that escalation.

Call get_scope_of_work and look hard for any reading of the agreement under which
this request is already covered - a deliverable that implies it, a revision policy
that permits it, or an ambiguity that favours the client.

Set agrees_with_escalation to False if you find a credible argument that this is
already covered. Set it to True only if the request is clearly additional work
that the freelancer would be doing for free.

You exist to protect the freelancer from crying wolf. An agent that interrupts
too often gets switched off, and then it protects nothing."""

DRAFTER_PROMPT = """You write replies on behalf of a freelancer to their client.

The request is outside the signed scope of work. Write a reply that:
- Thanks them and stays warm. This is a relationship, not a dispute.
- States plainly that the request falls outside the agreement, referencing the
  clause naturally (not like a lawyer).
- Gives the price and the estimated hours as a change order.
- Offers to proceed as soon as they confirm.

Calibrate firmness using the client's payment behaviour, which you must look up
with get_client_context:
- "prompt"   -> tone warm. A light, easy ask.
- "slow"     -> tone warm-firm. Be clear about the number and the timeline.
- "disputes" -> tone firm-documented. Put the scope reference and the figure in
                writing explicitly, so there is a record. Still polite.

Never invent a price. Use exactly the figure you are given.
Under 150 words. No subject line. No placeholder brackets."""


def _agent(system_prompt, tools, output_model):
    model, _ = build_model()
    return Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        structured_output_model=output_model,
        callback_handler=None,
    )


# --------------------------------------------------------------------------
# The cycle
# --------------------------------------------------------------------------

def analyse_message(msg):
    """Run one message through the agent chain. Returns a decision dict."""
    _trace_reset()
    client_id = msg["client_id"]

    # Retrieval is performed deterministically through the same @tool functions,
    # so the tool trace stays complete while the model is left to do only the
    # reasoning. Some providers reject a tool call when a structured output
    # schema is being enforced; resolving retrieval first avoids that entirely
    # and makes the chain reproducible.
    sow_text = get_scope_of_work(client_id=client_id)
    ctx_text = get_client_context(client_id=client_id)

    analyst = _agent(SCOPE_ANALYST_PROMPT, [], ScopeVerdict)
    verdict = analyst.structured_output(
        ScopeVerdict,
        f"{sow_text}\n\n{ctx_text}\n\n"
        f"Incoming message from {msg['sender']}:\n\"{msg['body']}\"\n\n"
        f"Decide whether this request falls outside the scope of work above."
    )

    if not verdict.out_of_scope:
        return {
            "message_id": msg["id"], "client_id": client_id, "action": "routine",
            "confidence": verdict.confidence,
            "reasoning": verdict.reasoning or "Routine message. No contractual action required.",
            "tool_trace": _trace_get(),
        }

    # Second opinion before we are allowed to interrupt a human.
    verifier = _agent(VERIFIER_PROMPT, [], VerifierVerdict)
    check = verifier.structured_output(
        VerifierVerdict,
        f"{sow_text}\n\nClient message:\n\"{msg['body']}\"\n\n"
        f"ScopeAnalyst says this is out of scope, citing clause {verdict.clause_cited}: "
        f"\"{verdict.clause_text}\"\nIts reasoning: {verdict.reasoning}\n\n"
        f"Argue against escalating this to the freelancer."
    )
    _trace_add("Verifier", {"client_id": client_id},
               ("agrees - escalate" if check.agrees_with_escalation
                else "disagrees - stand down"))

    if not check.agrees_with_escalation:
        return {
            "message_id": msg["id"], "client_id": client_id, "action": "stood_down",
            "confidence": check.confidence,
            "reasoning": f"ScopeAnalyst flagged clause {verdict.clause_cited}, but Verifier stood it "
                         f"down: {check.counter_argument}",
            "clause_cited": verdict.clause_cited, "clause_text": verdict.clause_text,
            "tool_trace": _trace_get(),
        }

    # Deterministic pricing, then the draft.
    c = store.get_client(client_id)
    amount = round(float(verdict.estimated_hours) * float(c["hourly_rate"]), 2)
    calculate_change_order(client_id=client_id, estimated_hours=verdict.estimated_hours)

    drafter = _agent(DRAFTER_PROMPT, [], DraftOutput)
    draft = drafter.structured_output(
        DraftOutput,
        f"{ctx_text}\n\nClient name: {c['name']}\n\n"
        f"Their message:\n\"{msg['body']}\"\n\n"
        f"This is outside the agreement. Clause {verdict.clause_cited} states: "
        f"\"{verdict.clause_text}\"\n"
        f"Estimated additional work: {verdict.estimated_hours} hours.\n"
        f"Change order price: {c['currency']} {amount:,.2f}\n\n"
        f"Write the reply now."
    )
    _trace_add("Drafter", {"client_id": client_id}, f"tone: {draft.tone_used}")

    return {
        "message_id": msg["id"], "client_id": client_id, "action": "escalate",
        "confidence": verdict.confidence, "reasoning": verdict.reasoning,
        "clause_cited": verdict.clause_cited, "clause_text": verdict.clause_text,
        "estimated_hours": verdict.estimated_hours, "amount": amount,
        "draft": draft.message, "tool_trace": _trace_get(),
    }


def run_cycle(limit=20):
    """Process every unread message. Called by the scheduler ping and by the
    'Run cycle' button in the UI."""
    if not provider_ready():
        store.log_audit("cycle", "Skipped: no model provider credentials configured.")
        return {"processed": 0, "escalated": 0, "error": "no_provider"}

    msgs = store.unprocessed_messages(limit)
    processed = escalated = stood_down = 0
    for m in msgs:
        try:
            d = analyse_message(m)
        except Exception as exc:  # noqa: BLE001
            store.log_audit("error", f"Message {m['id']} failed: {type(exc).__name__}: {exc}")
            continue
        store.save_decision(d)
        store.mark_processed(m["id"])
        processed += 1
        if d["action"] == "escalate":
            escalated += 1
        elif d["action"] == "stood_down":
            stood_down += 1

    store.log_audit(
        "cycle",
        f"Processed {processed} messages. Escalated {escalated}. "
        f"Stood down {stood_down}. Handled quietly {processed - escalated}.")
    return {"processed": processed, "escalated": escalated, "stood_down": stood_down}
