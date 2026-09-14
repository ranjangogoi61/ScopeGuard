# ScopeGuard

**An autonomous agent that watches a freelancer's client inbox against their signed scope of work, and interrupts them only when a real decision appears.**

Built with the [Strands Agents SDK](https://strandsagents.com) for the AWS **Agents for Humans** hackathon — Professional Agents track.

- **Live demo:** _(add your Render URL)_
- **Demo video:** _(add your YouTube link)_

> ScopeGuard decides what deserves your attention. You decide what gets said.

---

## The problem

Freelancers lose an average of **204 hours and roughly $6,800 a year** to admin — and that figure is from a 2026 survey that already accounts for AI tools being in their toolkit ([Smallpdf Freelancer Freedom Index, n=397](https://www.contentgrip.com/freelancer-admin-ai-gap/)). Separately, **75% of small business owners have tried AI and still lose ten working weeks a year** to the same work.

A large share of that loss has a specific shape: a client asks for "one quick extra thing" that the contract does not cover. The freelancer notices. They say yes anyway — because saying *"that falls outside our agreement"* to someone who pays you is socially expensive, and the request is always small enough that pushing back feels disproportionate. Industry estimates put the cost of this at **$7,800–$15,600 per freelancer per year** (directional — these figures come from vendor analyses rather than a controlled survey).

Every freelancer platform on the market — Bonsai, Moxie, Plutio, Harlow — **stores** the contract. None of them **watch** incoming work against it.

This is not a tracking problem. It is a problem of who has to say the uncomfortable thing.

## What ScopeGuard does

It runs in the background on the client inbox. Most messages it reads, classifies, and silently ignores — scheduling notes, thanks, invoice queries, approved revisions. **The silence is the product.**

When a request genuinely falls outside the signed agreement, it:

1. cites the **exact SOW clause** that excludes the work, quoted verbatim,
2. prices the change order from the freelancer's rate card,
3. drafts the reply, with firmness calibrated to that client's payment history,
4. and puts **one** decision card in front of the human: Approve, Edit, or Dismiss.

**It never sends anything on its own.** That is not a nice-to-have safety feature — it is the entire trust model. A tool that reads private client messages and makes judgment calls about a contract only works if the human holds the last word.

---

## How Strands Agents is used

Three specialised agents, each with one responsibility, one tool chain, and one typed output. Orchestration is deterministic Python — the agents do the reasoning, the control flow does not, because a contractual decision should be reproducible.

### Agents

| Agent | Responsibility | Tools it calls | Typed output |
|---|---|---|---|
| **ScopeAnalyst** | Reads the signed SOW and decides whether a request falls outside it, citing the clause | `get_scope_of_work`, `get_client_context` | `ScopeVerdict` |
| **Verifier** | Argues **against** escalating. Suppresses the interrupt if any reading of the agreement covers the request | `get_scope_of_work` | `VerifierVerdict` |
| **Drafter** | Writes the reply in the freelancer's voice, calibrated by payment history | `get_client_context` | `DraftOutput` |

**Why the Verifier exists.** The real failure mode of this product is not missing a breach — it is crying wolf. An agent that interrupts too often gets switched off, and then it protects nothing. So a second agent is given the opposite job: find any credible argument that the request is already covered. In the demo dataset it stands down a borderline letter-spacing request on the grounds that the revision policy explicitly permits spacing and scale adjustments to an approved concept. That decision is logged, not hidden.

### Tools (`@tool`)

| Tool | Kind | Notes |
|---|---|---|
| `get_scope_of_work(client_id)` | data | Deliverables, exclusions with clause numbers, revision policy |
| `get_client_context(client_id)` | data | Rate, payment behaviour, relationship history |
| `calculate_change_order(client_id, hours)` | **deterministic** | Plain Python arithmetic. The model never computes pricing |

### Structured output

Every agent returns a Pydantic model via Strands' `structured_output()`, never free text. `ScopeVerdict` carries `out_of_scope`, `confidence`, `clause_cited`, `clause_text`, `reasoning` and `estimated_hours`. Typed output is what makes the audit log trustworthy — you can assert on it.

### Tool-invocation trace

Every tool call is recorded and rendered in the UI under **"Show the agent's working."** A judge — or a user — can see precisely which tools ran, in what order, and what each returned. The agent is inspectable rather than a black box that emits text.

### Model provider

Primary: **Google Gemini** through Strands' `LiteLLMModel`. Free tier, no payment card, 1,500 requests/day — which comfortably survives a three-and-a-half week judging window without the demo going dark.

Also supported: **Amazon Bedrock** via Strands' native `BedrockModel`. Set `SCOPEGUARD_PROVIDER=bedrock` and supply AWS credentials.

Gemini is the default here for an honest reason: this project was built by a solo developer without access to a payment card, and AWS account creation requires one. The SDK, the agent architecture, the tool contracts and the structured outputs are entirely provider-agnostic — switching is one environment variable.

---

## Architecture

![Architecture](docs/architecture.svg)

```
cron ping (every 10 min)  ──►  POST /cycle
                                   │
                          unprocessed messages
                                   ▼
                            ScopeAnalyst  ──► get_scope_of_work, get_client_context
                                   │           ScopeVerdict {out_of_scope, clause, confidence}
                     in scope ◄────┴────► out of scope
                         │                     │
                  log quietly            Verifier ──► get_scope_of_work
                  (no interrupt)               │       VerifierVerdict
                                    stands down│agrees
                                       │       │
                               log "stood down"│
                                               ▼
                                   calculate_change_order  (deterministic)
                                               ▼
                                          Drafter  ──► get_client_context
                                               ▼
                                     ESCALATION QUEUE
                                               ▼
                              Approve  │  Edit  │  Dismiss
                                       ▼
                             logged · edit stored as voice sample
```

### Why there is an external ping

Render's free tier spins a web service down after roughly 15 minutes of inactivity, and an in-process scheduler dies with it. An agent that claims to "run in the background" while its process is asleep is making a claim it cannot back up.

So background execution is driven by a free external cron job (cron-job.org) calling `POST /cycle` every 10 minutes. It keeps the claim true and removes cold starts for anyone opening the live link. Constraint-driven, and documented rather than hidden.

---

## What is real and what is stubbed

Stated plainly, because overclaiming is worse than a narrow scope.

| Component | Status |
|---|---|
| Strands agent chain, tools, structured output, tool trace | **Real** — this is the substance of the project |
| Scope analysis, clause citation, verification, drafting | **Real** — live model calls |
| Change-order pricing | **Real** — deterministic Python |
| Approval / edit / dismiss flow, audit log, voice samples | **Real** — persisted to SQLite |
| Background cycle | **Real** — external cron ping |
| **Inbox ingestion** | **Seeded dataset.** `InboxAdapter` is an interface; the Gmail/IMAP implementation is not built |
| **Outbound sending** | **Stubbed.** Approval marks the message sent and logs it; no email leaves the system |
| Multi-user auth | Not built — single-tenant demo |
| Bedrock AgentCore deployment | Not built — documented as roadmap |

The demo dataset is three clients and twelve messages: one clear scope breach, one borderline request the Verifier stands down, and ten pieces of routine traffic that prove the noise filter works. It is labelled **Demo data** in the interface.

---

## Run it locally

```bash
git clone https://github.com/ranjangogoi61/scopeguard.git
cd scopeguard
pip install -r requirements.txt
export GEMINI_API_KEY=your_key_here        # free, no card: aistudio.google.com
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` and press **Run cycle now**.

`GET /healthz` reports database state, provider credentials, and the last cycle result.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Required for the default provider |
| `SCOPEGUARD_PROVIDER` | `gemini` | `gemini` or `bedrock` |
| `GEMINI_MODEL_ID` | `gemini/gemini-2.0-flash` | LiteLLM model id |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Used when provider is `bedrock` |
| `SCOPEGUARD_DB` | `/tmp/scopeguard.db` | SQLite path |

---

## Roadmap

Each would be built the same way: one modular agent, one responsibility, one human decision point.

- **Memory Agent** — learns each client's communication pattern and negotiating style over time.
- **Risk Agent** — flags which clients repeatedly push scope, before the next project is signed.
- **Evidence Agent** — assembles the full paper trail behind a change order for disputes.
- **Follow-up Agent** — schedules approved reminders and chases unanswered change orders.
- **Payment Chaser** — deliberately *not* in the MVP. Invoice chasing is a commodity feature, and building it would have diluted the one thing this project does that nothing else does.
- Real inbox ingestion (Gmail/IMAP OAuth), outbound sending, multi-tenant auth, Bedrock AgentCore deployment.

---

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built with [Strands Agents](https://strandsagents.com) by AWS. Developed entirely on an Android phone.
