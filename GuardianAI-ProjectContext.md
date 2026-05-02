# Guardian AI — Project Context

> Multi-agent adversarial compliance engine for telecom marketing content.
> 3-day hackathon build for the "AI Agents in Marketing Operations" track.

For the polished narrative version, see
[docs/Guardian-AI-Overview.md](docs/Guardian-AI-Overview.md). This file is the
working context — kept tight and current for in-IDE reference.

---

## 1. Project Overview

### The Problem
Telecom marketing must ship punchy creative ("$0 iPhone with trade-in") while
honoring complex FCC/FTC truth-in-advertising rules and the carrier's brand
bible (claim hierarchy, mandatory disclosures, channel limits, audience tone).
The disconnect between creative, legal, brand, and ops teams produces:

- 51%+ of marketing documents requiring manual revisions for compliance.
- FCC/FTC fines: **$200M** against major carriers in 2024 (location data);
  **$10.22M** multi-state AG settlement (May 2024) against AT&T / Verizon /
  T-Mobile for misleading "free phone" ads.
- 2–3 day cycle time per asset killing time-to-market.

### The Solution
A **courtroom-style multi-agent system with deterministic tools**. The user
uploads content (SMS, Email, LinkedIn, Landing Page, or Press Release).
**Five specialized critic agents** review it in parallel — each red-teaming a
distinct failure mode using curated Python tool functions. A **Resolver agent**
aggregates verdicts and rewrites the content. The loop runs until all 5
critics APPROVE or the configured iteration cap is hit. A **User Gate** lets
the human accept any version, edit it, or fire another round.

### Core Differentiators
- **Tool-grounded agents** — every violation cites a `rule_id` / `section_id`
  surfaced by a deterministic Python function. No hallucinated flags.
- **Approval ratchet** — once a critic approves, only a structural regression
  caught by a deterministic validator can flip them back. Stylistic LLM
  second-guessing is demoted to soft feedback. Eliminates the oscillation
  problem where two critics disagree forever.
- **Adversarial review in seconds**, not 2–3 days.
- **Live streaming** of per-critic verdicts over WebSocket.
- **Auditable trail** — full per-round verdict + tool-call trace + diff.

---

## 2. Architecture

### High-Level Flow

```
user → Intake Parser → PARALLEL CRITIC ROUND (5 agents):
                          ⚖️  FCC Enforcer       — compliance_lookup + offer_verification
                          🛡️  Brand Guardian      — compliance_lookup + content_analysis
                          👥 Persona Simulator    — offer_verification
                          🔬 Technical Lead       — offer_verification
                          📋 Ops Strategist       — channel_validation
                       ↓
                       Resolver Agent (content_generation: disclosure, truncate, UTM, term-swap)
                       ↓
                       Convergence check (all APPROVE? OR iter == cap?)
                       ↓ no → loop with revised content + prior_state (approval ratchet)
                       ↓ yes → User Gate (Accept | Edit | Re-run)
                       ↓
                       Report page (audit trail, score chart, diff)
```

### LangGraph topology
`intake → fan_out_critics → aggregate → resolver → gate → (loop|end)`

The fan-out node dispatches 5 critic nodes concurrently via `asyncio.gather`.
State is a Pydantic model carrying iterations, prior approvals, audit trail.

### WebSocket protocol (`/ws/review`)
| Event       | Payload                                | UI effect                                       |
|-------------|----------------------------------------|-------------------------------------------------|
| `intake`    | parsed channel/audience/offer/claims   | populates Original panel                        |
| `critic`    | one critic's verdict                   | flips that agent card from thinking → verdict   |
| `iteration` | resolver output for the round          | adds row to score chart, updates Resolver panel |
| `done`      | final response + audit trail           | reveals User Gate                               |
| `error`     | error message                          | banner                                          |

---

## 3. Tech Stack

### Backend
- Python 3.10+
- FastAPI + Uvicorn (REST + WebSocket)
- LangGraph (state machine), LangChain (LLM client + tool calling)
- Pydantic v2
- Azure OpenAI (`gpt-5.4-beta` deployment) — also supports OpenAI; chat-completions w/ tools
- Pytest (smoke + eval harness in `backend/app/eval/`)

### Frontend
- React 18 + TypeScript + Vite 5
- react-router-dom v6 (`/`, `/review`, `/report`)
- Native WebSockets for live streaming
- Pure CSS, dark theme, agent-tinted accents
- Resizable 3-pane review layout (Original / Courtroom / Resolver) with
  widths persisted in `localStorage`

### Data assets (`backend/app/data/`)
- `regulatory_rules.json` — FCC/FTC rule catalog
- `carrier_brand_guidelines.json` — NovaTel brand bible
- `offers_registry.csv` — active offers (price, eligibility, credit period, fine print)
- `channel_audience_matrix.json` — per-channel format constraints + audience tones
- `good_content_samples.json` / `violation_content_samples.json` — eval sets
- `source_content_assets.json` — real-world source copy per offer/channel

### Skills (deterministic toolkits in `backend/app/skills/`)
- `compliance_lookup` — keyword/category search over FCC/FTC + brand JSON
- `offer_verification` — match claims (price, speed, term) against `offers_registry.csv`
- `content_analysis` — superlative/forbidden-term detection, tone classification,
  price-accuracy check, "unlimited" qualifier audit
- `channel_validation` — character/length limits, mandatory elements
  (offer-aware: "(if applicable)" elements skip when offer registry says N/A),
  CTA + UTM validators
- `content_generation` — template rewrites (disclosure, truncation, UTM injection, term swap)

---

## 4. Supported Channels & Audiences

**Channels** (UI dropdown): SMS, Email, LinkedIn, Landing Page, Press Release.
The backend `intake.py` normalizes display labels ("Landing Page",
"Press Release") to internal keys (`landing_page`, `press_release`).

**Audiences**: Consumer (General), Executive (VP+), Small Business Owner,
Technical (IT/Ops).

**Offer**: auto-detected by Intake Parser from content; no manual selection in UI.

---

## 5. Convergence & Iteration

- Iteration cap is configurable via `GUARDIAN_MAX_ITERATIONS` env var
  (default in `app/config.py`).
- Convergence: round ends when all 5 critics return `APPROVE` OR cap hit.
- Approval ratchet: `build_prior_state(iterations)` walks all prior rounds and
  for each critic emits `{approved, ever_approved, prev_rule_ids}`. The runner
  uses this in Precision pass #3 to demote LLM HARD violations to SOFT for
  any critic that has ever approved, unless a deterministic validator also
  flagged the same `rule_id`. The Resolver receives a `DO-NOT-REGRESS`
  instruction listing those critics so it makes minimum edits.

---

## 6. Frontend UX

- **Upload page** (`/`): hero + tagline + 5-agent tile strip, content textarea,
  channel + audience filters (offer auto-detected). No sample buttons.
- **Review page** (`/review`): 3 resizable panes
  - **Original** (left): input content, channel/audience pills.
  - **Agent Courtroom** (center): 5 agent cards, live thinking pips →
    verdict badge → cited violations. Score progression chart appears after
    round 1.
  - **Resolver** (right): each round's rewrite, score, changelog.
  - User Gate appears at bottom after each completed round.
- **Report page** (`/report`): full audit trail + per-iteration verdict
  matrix + diff against original.

---

## 7. Status

✅ Intake parser with offer auto-detect.
✅ 5 critics with deterministic fallbacks (so a flaky LLM never produces an empty verdict).
✅ Resolver with template tools + score model.
✅ Approval ratchet end-to-end (runner + critics + resolver + routes + state_graph).
✅ Verified-rule audit anchors in Ops/Brand fallbacks (validate_utm, validate_cta, check_price_accuracy, check_unlimited_qualifier).
✅ Live-streaming UI with resizable panes, score progression chart, audit trail.
✅ Eval harness over `violation_content_samples.json` for regression testing.

Build target: NovaTel Wireless (synthetic carrier). Extensible to any operator
by swapping the JSON/CSV data files in `backend/app/data/`.
