# Guardian AI — High-Level Overview

> Multi-agent adversarial compliance engine for telecom marketing content.

---

## 1. Problem Statement

Telecom marketing teams operate under enormous pressure: ship punchy creative
fast, while staying within FCC/FTC truth-in-advertising rules **and** the
carrier's own brand bible (claim hierarchy, mandatory disclosures, channel
limits, audience tone). Today this is enforced by a slow human pipeline —
copywriter → brand reviewer → legal → ops — that breaks down at scale.

The cost of getting it wrong is real:

- **51%+ of marketing assets require revision** for compliance before launch.
- The FCC issued **$200M in carrier fines in 2024** for location-data
  misrepresentation; a **$10.22M multi-state AG settlement** in May 2024
  targeted "free phone" ads from AT&T, Verizon, and T-Mobile.
- Manual review cycles add **2–3 days** per asset, killing time-to-market for
  promos and short-window campaigns.

The fundamental gap: today's compliance review is **serial, opinion-driven, and
unauditable**. There is no system that simultaneously red-teams a piece of copy
from every angle (legal, brand, audience, technical accuracy, ops) and emits a
provable, citation-backed verdict in seconds.

---

## 2. Approach

Guardian AI applies an **adversarial multi-agent** pattern, modeled after a
courtroom: five specialized critic agents review the same content **in parallel**,
each owning a distinct failure mode. A Resolver agent then aggregates their
verdicts, rewrites the content, and the loop continues until every critic
approves (or a max-iterations cap is hit).

Two design principles make the verdicts trustworthy:

1. **Tool-grounded reasoning.** Every critic is paired with a curated toolkit
   of deterministic Python functions — offer registry lookups, regulation
   keyword search, character counters, CTA/UTM validators, price-accuracy
   checks. Critics cannot fabricate violations; they must cite a `rule_id` or
   `section_id` that a tool surfaced.
2. **Approval ratchet.** Once a critic approves a piece of content, only a
   structural regression (caught by a deterministic validator) can flip them
   back to "revise." Stylistic LLM second-guessing is demoted to soft
   feedback. This prevents the well-known oscillation problem where two
   critics disagree forever.

### The 5 Critics

| Agent | Lane | Primary Skills |
|-------|------|----------------|
| ⚖️  **FCC Enforcer**     | FCC/FTC truth-in-advertising | `compliance_lookup`, `offer_verification` |
| 🛡️ **Brand Guardian**    | Voice, tone, claim hierarchy, terminology | `compliance_lookup`, `content_analysis` |
| 👥 **Persona Simulator** | Audience comprehension & resonance         | `offer_verification`                     |
| 🔬 **Technical Lead**    | Spec accuracy vs. offer registry           | `offer_verification`                     |
| 📋 **Ops Strategist**    | Channel limits, CTAs, attribution, UTMs    | `channel_validation`                     |

### The Resolver
After every parallel critic round, the Resolver receives the original content
plus all 5 verdicts and rewrites the content using `content_generation` tools
(template-based: apply disclosure, truncate to channel limit, inject UTM,
swap brand-violating phrases). It also produces a 1–10 score and a "do not
regress" instruction set listing critics that have already approved, so future
rounds make minimum-edit improvements rather than restructuring.

---

## 3. End-to-End Flow

```
       ┌──────────────────────────────────────────────────────────────────┐
user ─►│  Upload page (channel, audience, content)                        │
       └───────────────────────────┬──────────────────────────────────────┘
                                   │ WebSocket /ws/review
                                   ▼
                       ┌────────────────────┐
                       │  Intake Parser     │  tools: lookup_offer,
                       │                    │         extract_claims,
                       │  → channel/audience│         identify_channel
                       │  → offer auto-detect│
                       │  → claim list       │
                       └─────────┬──────────┘
                                 │
                ┌────────────────┴────────────────┐
                │   PARALLEL CRITIC ROUND         │
                │  (5 agents, ~2-4 s each)        │
                │                                 │
                │  ⚖️  FCC Enforcer               │
                │  🛡️  Brand Guardian              │
                │  👥 Persona Simulator           │
                │  🔬 Technical Lead              │
                │  📋 Ops Strategist               │
                │                                 │
                │  Each emits:                    │
                │    verdict: APPROVE | REVISE    │
                │    score:   1-10                │
                │    violations: [{rule_id,       │
                │                  severity,      │
                │                  span,          │
                │                  suggestion}]   │
                └────────────────┬────────────────┘
                                 │  WS: critic events streamed live
                                 ▼
                       ┌────────────────────┐
                       │   Resolver Agent   │  tools: apply_disclosure,
                       │                    │         truncate_for_channel,
                       │  → revised_content │         inject_utm,
                       │  → score 1-10      │         swap_brand_terms
                       │  → diff/changelog  │
                       └─────────┬──────────┘
                                 │  WS: iteration event
                                 ▼
                  ┌────────────────────────────┐
                  │   Convergence Check        │
                  │   all 5 APPROVE  ──► done  │
                  │   else if iter < max ──►  loop with revised content
                  │   else ──► done (capped)   │
                  └─────────────┬──────────────┘
                                │
                                ▼
                  ┌────────────────────────────┐
                  │   User Gate (UI)           │
                  │   • Accept this version    │
                  │   • Edit & re-review       │
                  │   • Run another round       │
                  └────────────────────────────┘
                                │
                                ▼
                            Report page
                            (full audit trail,
                            score progression chart,
                            diff against original)
```

### Backend orchestration
The flow above is encoded as a **LangGraph** state machine:

```
intake → fan_out_critics → aggregate → resolver → gate → (loop|end)
```

The fan-out node dispatches 5 critic nodes concurrently using `asyncio.gather`.
Aggregate collects their verdicts; Resolver runs once per round; Gate decides
whether to loop. State is threaded as a Pydantic model (iterations, prior
approvals, audit trail).

### Frontend orchestration
The frontend opens a **WebSocket** to `/ws/review` and streams events:

| Event       | Payload                                    | UI effect                              |
|-------------|--------------------------------------------|----------------------------------------|
| `intake`    | parsed channel/audience/offer/claims       | populates Original panel               |
| `critic`    | one critic's verdict                       | flips that agent card from thinking → verdict |
| `iteration` | resolver output for the round              | adds a row to score chart, updates Resolver panel |
| `done`      | final response + audit trail               | reveals User Gate                      |
| `error`     | error message                              | banner                                 |

The UI is a 3-pane dashboard:
- **Original** (left): the input content, channel, audience.
- **Agent Courtroom** (center): the 5 agent cards, each with live thinking
  pips → verdict badge → cited violations.
- **Resolver** (right): each round's rewrite, score, and changelog.

A user can drag the dividers to resize panes. After each round the User Gate
appears so the human can pick any version (original or any round's rewrite)
and either accept it as final, edit it, or fire another adversarial round.

---

## 4. Tech Stack

### Backend
- **Python 3.10+**
- **FastAPI** — REST + WebSocket transport
- **Uvicorn** — ASGI server
- **LangGraph** — state machine for the multi-agent loop
- **LangChain** — LLM client abstraction + tool-calling
- **Pydantic v2** — typed state, request/response models
- **OpenAI / Azure OpenAI** — `gpt-4o-mini` class model, chat completions with
  tool-calling
- **Pytest** — smoke + eval harness

### Frontend
- **React 18 + TypeScript**
- **Vite 5** — dev server + bundler
- **react-router-dom v6** — `/`, `/review`, `/report`
- **WebSockets** (browser-native) — live streaming of critic events
- **Pure CSS** (no UI framework) — dark theme, agent-tinted accents

### Data assets (`backend/app/data/`)
| File                            | Purpose                                  |
|---------------------------------|------------------------------------------|
| `regulatory_rules.json`         | FCC/FTC rule catalog with `rule_id`s     |
| `carrier_brand_guidelines.json` | NovaTel brand bible (voice, claim tiers, mandatory disclosures) |
| `offers_registry.csv`           | Active offers (price, eligibility, credit period, fine print)   |
| `channel_audience_matrix.json`  | Per-channel format constraints + audience tone targets          |
| `good_content_samples.json`     | Eval set: known-clean copy                |
| `violation_content_samples.json`| Eval set: known-violating copy with expected `rule_id`s         |
| `source_content_assets.json`    | Real-world source copy per offer/channel  |

### Skills (deterministic toolkits in `backend/app/skills/`)
- `compliance_lookup` — keyword/category search over FCC/FTC + brand JSON
- `offer_verification` — match claims (price, speed, term) against `offers_registry.csv`
- `content_analysis` — superlative/forbidden-term detection, tone classification
- `channel_validation` — character/length limits, mandatory elements, CTA + UTM validators
- `content_generation` — template rewrites (disclosure, truncation, UTM injection, term swap)

---

## 5. What Makes Guardian AI Different

| Property                  | Single-LLM "compliance prompt"          | Guardian AI                                   |
|---------------------------|-----------------------------------------|-----------------------------------------------|
| Hallucinated violations   | Frequent                                | Impossible — every flag cites a tool-verified `rule_id` |
| Coverage                  | Whatever fits in one prompt             | 5 specialized lanes, each with its own toolkit |
| Auditability              | Opaque                                  | Full per-round verdict, tool-call trace, diff |
| Convergence behavior      | Re-prompt loops forever                 | Approval ratchet + iteration cap              |
| Latency on a 600-char SMS | 4–8 s (single call)                     | 4–6 s per round (5 critics in parallel)       |
| Human override            | Re-prompt the LLM                       | Pick any version, edit inline, force a round  |

---

## 6. Status

End-to-end working slice:
- ✅ Intake parser with offer auto-detect.
- ✅ 5 critics with deterministic fallbacks (so a flaky LLM never produces an empty verdict).
- ✅ Resolver with template tools + score model.
- ✅ Approval ratchet across rounds.
- ✅ Live-streaming UI with resizable panes, score progression chart, audit trail.
- ✅ Eval harness over `violation_content_samples.json` for regression testing.

Build target: NovaTel Wireless (synthetic carrier) — extensible to any operator
by swapping the JSON/CSV data files in `backend/app/data/`.
