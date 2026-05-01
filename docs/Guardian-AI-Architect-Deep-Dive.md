# Guardian AI — Architect Deep Dive

> A complete, end-to-end walkthrough of Guardian AI: the data, approach, code,
> tools, tech stack, and design rationale. Use this to brief yourself before an
> architectural review.

**Companion docs:**
- [Guardian-AI-Overview.md](Guardian-AI-Overview.md) — narrative summary
- [../GuardianAI-ProjectContext.md](../GuardianAI-ProjectContext.md) — quick context

---

## Table of Contents

1. [Problem and value proposition](#1-problem-and-value-proposition)
2. [Solution philosophy](#2-solution-philosophy)
3. [System architecture](#3-system-architecture)
4. [Data layer](#4-data-layer)
5. [Skills (deterministic toolkits)](#5-skills-deterministic-toolkits)
6. [Tool registry exposed to the LLM](#6-tool-registry-exposed-to-the-llm)
7. [Agents in detail](#7-agents-in-detail)
8. [The runner: precision passes and approval ratchet](#8-the-runner-precision-passes-and-approval-ratchet)
9. [Resolver: aggregation and rewrite](#9-resolver-aggregation-and-rewrite)
10. [LangGraph state machine](#10-langgraph-state-machine)
11. [API and WebSocket protocol](#11-api-and-websocket-protocol)
12. [Frontend architecture](#12-frontend-architecture)
13. [Scoring, convergence, and iteration policy](#13-scoring-convergence-and-iteration-policy)
14. [Evaluation harness](#14-evaluation-harness)
15. [Tech stack and runtime topology](#15-tech-stack-and-runtime-topology)
16. [Security, observability, and operational concerns](#16-security-observability-and-operational-concerns)
17. [Design trade-offs and answers to expected architect questions](#17-design-trade-offs-and-answers-to-expected-architect-questions)
18. [Roadmap and known limitations](#18-roadmap-and-known-limitations)

---

## 1. Problem and value proposition

Telecom marketing is a high-velocity / high-risk environment.

- **Creative teams** push punchy headlines like "$0 iPhone with trade-in".
- **Legal & compliance** require disclosures: plan, monthly cost, trade-in
  eligibility, AutoPay condition, 36-month bill-credit clause, "credits stop
  if you cancel".
- **Brand** enforces voice, terminology hierarchy, and channel-specific format
  rules (SMS ≤160 chars, AP-style press releases, etc.).
- **Ops** owns CTA registries, UTM tagging, and channel/audience fit.

Today this is enforced by a serial human pipeline (copywriter → brand reviewer
→ legal → ops). The result:

- 51%+ of marketing assets need revision before launch.
- 2024 brought a **$200M FCC fine** to major US carriers for location-data
  misrepresentation, and a **$10.22M multi-state AG settlement** (May 2024)
  against AT&T, Verizon, T-Mobile for misleading "free phone" ads.
- 2–3 day cycle time per asset crushes time-to-market on promos.

**Guardian AI** replaces serial human review with a parallel, tool-grounded
adversarial multi-agent pipeline. Output: in seconds, a compliant rewrite plus
an auditable trail of every cited rule and tool call.

---

## 2. Solution philosophy

Guardian AI is built on four explicit design beliefs.

### 2.1 Tool-grounded reasoning beats prompt engineering
LLMs hallucinate violations and rule IDs. The fix is not better prompts; it's
**deterministic tools** that surface ground-truth rule IDs from JSON/CSV data.
Every critic call goes through this pipeline:

1. Run a deterministic Python "fallback" against the content. This produces a
   set of structurally-grounded violations (e.g., "SMS exceeds 160 chars,
   `BRAND-401`").
2. Run the LLM with a curated tool set, asking for a JSON verdict.
3. **Filter the LLM output** against the audit trail: an LLM-claimed violation
   is dropped unless either (a) it cites a `rule_id` that a tool surfaced this
   round, or (b) the deterministic fallback also flagged it.

The user-visible verdict is the **intersection** of LLM judgment and structural
proof. A critic cannot fabricate an out-of-lane rule ID, cite a non-existent
rule, or flag a rule that a verifying tool already proved compliant.

### 2.2 Adversarial parallelism, not chained chain-of-thought
Five critics run **concurrently**, each owning a single failure mode. They do
not communicate. The Resolver is the only synthesizer. This avoids the
"echo-chamber" pathology where one critic's output biases the next.

### 2.3 Approval ratchet kills oscillation
With independent critics, you get the classic problem: critic A approves
round 1, critic B forces a rewrite, the rewrite breaks something subtle that
flips A back. Loop forever.

Guardian AI solves this with an **approval ratchet** at three layers:

- **Runner level (Precision pass #3):** if a critic has `ever_approved`, new
  LLM-only HARD violations are demoted to SOFT — unless the deterministic
  fallback also flagged the same `rule_id`. Stylistic LLM second-guessing
  cannot un-approve a critic.
- **Resolver brief (DO-NOT-REGRESS):** the rewrite prompt explicitly lists
  critics who already approved and tells the LLM to make minimum edits in
  their lanes.
- **Convergence rule:** an iteration ends only when all five critics return
  `APPROVE`. There is no quorum vote.

### 2.4 Human-in-the-loop is non-negotiable
Every round emits a User Gate. The human can accept any version (original or
any round's rewrite), edit inline and re-review, or fire another round. The
agent pipeline never "ships" without human dispatch.

---

## 3. System architecture

### 3.1 Block diagram

```
┌────────────────┐       WebSocket /api/ws/review        ┌─────────────────┐
│   Browser      │◄────────── streaming events ─────────►│  FastAPI        │
│   React 18 +   │                                       │  Uvicorn        │
│   Vite         │  POST /api/review (sync REST)         │                 │
│                │◄──────────────────────────────────────│  ReviewRequest  │
└────────────────┘                                       └────────┬────────┘
                                                                  │
                                                                  ▼
                                                        ┌──────────────────┐
                                                        │  LangGraph       │
                                                        │  State Machine   │
                                                        │                  │
                                                        │  intake          │
                                                        │    │             │
                                                        │    ▼             │
                                                        │  fan_out_critics │
                                                        │    │             │
                                                        │    ├─►⚖️ FCC      │
                                                        │    ├─►🛡️ Brand    │
                                                        │    ├─►👥 Persona  │
                                                        │    ├─►🔬 Tech     │
                                                        │    └─►📋 Ops      │
                                                        │    │             │
                                                        │    ▼             │
                                                        │  aggregate       │
                                                        │   (+ resolver)   │
                                                        │    │             │
                                                        │    ▼             │
                                                        │  gate ──loop───┐ │
                                                        │    │           │ │
                                                        │    ▼           │ │
                                                        │  END ◄─────────┘ │
                                                        └────────┬─────────┘
                                                                 │
                                ┌────────────────────────────────┼────────────────────────────────┐
                                │                                │                                │
                       ┌────────▼────────┐         ┌─────────────▼─────────────┐         ┌────────▼────────┐
                       │  Skills         │         │  LLM Client               │         │  Data           │
                       │  (deterministic)│         │  OpenAI / Azure OpenAI    │         │  (JSON + CSV)   │
                       │                 │         │  gpt-4o-mini, temp=0      │         │  @lru_cache     │
                       │  - compliance   │         │  function-calling         │         │                 │
                       │  - offer_ver    │         │                           │         │  - rules        │
                       │  - content_an   │         └───────────────────────────┘         │  - brand book   │
                       │  - channel_val  │                                               │  - offers CSV   │
                       │  - content_gen  │                                               │  - channel mtx  │
                       └─────────────────┘                                               └─────────────────┘
```

### 3.2 Module layout

```
backend/
├── pyproject.toml
└── app/
    ├── main.py                     # FastAPI app factory, CORS
    ├── config.py                   # env vars, defaults, data dir
    ├── api/
    │   └── routes.py               # REST + WebSocket endpoints
    ├── models/
    │   └── schemas.py              # Pydantic v2 models
    ├── agents/
    │   ├── intake.py               # parse channel/audience/offer/claims
    │   ├── llm.py                  # OpenAI / Azure OpenAI client factory
    │   ├── runner.py               # generic critic runner + ratchet
    │   ├── critics.py              # 5 critic dispatchers + fallbacks
    │   └── resolver.py             # aggregator + rewriter
    ├── graph/
    │   └── state_graph.py          # LangGraph topology
    ├── skills/
    │   ├── _data.py                # cached JSON/CSV loaders
    │   ├── compliance_lookup.py    # FCC/FTC + brand search
    │   ├── offer_verification.py   # offer registry checks
    │   ├── content_analysis.py     # superlative/urgency/etc.
    │   ├── channel_validation.py   # length, mandatory, CTA, UTM
    │   ├── content_generation.py   # template rewrites
    │   └── tools.py                # LLM-callable tool registry
    ├── data/                       # all JSON + CSV ground truth
    └── eval/
        └── run_eval.py             # precision/recall harness

frontend/
└── src/
    ├── main.tsx                    # router, ReviewProvider
    ├── App.tsx
    ├── api/client.ts               # REST + WebSocket helpers
    ├── state/ReviewContext.tsx     # global review state
    ├── pages/
    │   ├── UploadPage.tsx
    │   ├── ReviewPage.tsx
    │   └── ReportPage.tsx
    ├── components/
    │   ├── TopBar.tsx
    │   ├── AgentCourtroom.tsx
    │   ├── AgentCard.tsx
    │   ├── OriginalContentPanel.tsx
    │   ├── ResolverPanel.tsx
    │   ├── DiffView.tsx            # word-level LCS diff
    │   ├── ScoreProgressionChart.tsx
    │   └── UserGate.tsx
    ├── types/index.ts
    └── util/score.ts
```

---

## 4. Data layer

All ground-truth lives under `backend/app/data/` and is loaded once at process
start with `@lru_cache`. There is no database. Swapping carriers means
swapping these files.

### 4.1 `regulatory_rules.json` (FCC/FTC catalog)
**~20 rules**, each with:
```json
{
  "rule_id": "FTC-005",
  "category": "disclosure_proximity",
  "rule_text": "...",
  "source": "FTC .com Disclosures Guide (March 2013)",
  "severity": "HARD",
  "applies_to": ["SMS", "social", "mobile_web", "email"],
  "example_violation": "FREE iPhone! Switch today.",
  "example_compliant": "$0/mo on Unlimited Premium ($85.99/mo) w/ AutoPay + 36-mo credits..."
}
```

Naming convention: `FTC-NNN`. Coverage themes:
- 001–004 disclosure proximity / prominence / clarity
- 005–006 free/$0 claims, trade-in value
- 007–011 unlimited, throttling, coverage, pricing
- 012–014 trade-in conditions, SMS TCPA elements
- 015–020 speed claims, comparative claims, testimonials

### 4.2 `carrier_brand_guidelines.json` (NovaTel brand bible)
Eight sections (`§1`–`§8`), ~100+ rules:

| Section | Rule IDs | Topic |
|---------|----------|-------|
| §1 Voice | BRAND-101..106 | Tone, urgency, all-caps, condescension, passive voice, humor |
| §2 Terminology | BRAND-201..208 | Approved product names, speeds, plan tiers |
| §3 Prohibited Words | BRAND-301..315 | Banned words, free/$0, unlimited |
| §4 Channel Format | BRAND-401..406 | SMS / LinkedIn / Email / Facebook-Insta / Landing / Press |
| §5 Audience Tone | BRAND-501..504 | Channel-audience fit, audience-specific jargon |
| §6 CTAs | BRAND-601..604 | Approved CTAs, prohibited CTAs, UTM tracking |
| §7 Claim Standards | BRAND-701..704 | Quantitative claim accuracy, superlatives, testimonials |
| §8 Disclosure Requirements | BRAND-801..805 | $0/free, speed methodology, savings baseline, BOGO, deprioritization |

### 4.3 `offers_registry.csv` (15 offers)
24 columns. Critical fields:

```
offer_id, offer_headline, offer_type, device, device_retail_price,
plan_required, plan_monthly_cost, autopay_required, trade_in_required,
eligible_trade_in_brands, trade_in_condition, credit_period_months,
total_promotional_credit, monthly_credit_amount, deprioritization_threshold_gb,
hotspot_data_gb, mandatory_disclosure_text
```

The `mandatory_disclosure_text` for `OFF-001` (the canonical iPhone $0
trade-in offer) is ~300 chars and is the legal-grade disclosure injected by
`apply_disclosure` during rewrite.

### 4.4 `channel_audience_matrix.json`
Per-channel format spec + per-(channel × audience) tone:

| Channel | Hard limit | Mandatory elements |
|---------|------------|---------------------|
| SMS | 160 chars | Msg&Data rates, STOP, terms URL |
| Email | 300 words | T&C link, plan, credit period, unsubscribe |
| LinkedIn | 150 words | Visible disclosures, professional tone |
| Landing Page | hero ≤200 words | Disclosures in same viewport as claim |
| Press Release | 400–600 words | AP style, no CTA in body |

### 4.5 Eval datasets
- `violation_content_samples.json` — 12+ samples with planted violations and
  expected rule IDs. Used by the eval harness for precision/recall.
- `good_content_samples.json` — compliant references; the Resolver pulls
  these as few-shot examples matching channel/audience.
- `source_content_assets.json` — real-world source copy per
  campaign / offer / channel.

---

## 5. Skills (deterministic toolkits)

Skills are pure-Python, side-effect-free functions that return structured
dicts. They are the **substrate of trust** — every LLM-flagged violation must
trace back to a skill output.

### 5.1 `compliance_lookup.py`
- `search_regulations(query, category, channel, limit) → list[dict]` —
  keyword search over FCC/FTC rules.
- `get_rule(rule_id) → dict | None` — fetch one rule by ID.
- `search_brand_rules(query, section, channel, limit) → list[dict]` —
  keyword search over brand bible.
- `list_prohibited_terms(channel) → list[dict]` — BRAND-3xx/6xx prohibited
  words/CTAs.
- `get_required_citations(claim_type) → dict` — required citations for a
  claim type (superlative, speed, savings).

### 5.2 `offer_verification.py`
- `lookup_offer(offer_id) → dict | None` — full offer row.
- `find_offer_by_content(text) → list[dict]` — heuristic device/keyword match
  with confidence scores. Used by intake auto-detect.
- `verify_claim(claim, offer_id) → dict` — spot-check a claim against
  registry (unlimited, deprioritization, hotspot, video resolution, etc.).
- `get_mandatory_disclosure(offer_id) → str | None` — canonical disclosure.
- `check_price_accuracy(text, offer_id) → dict` — the workhorse for FTC-005:
  - Detects `\bfree\b`, `\$\s*0(?!\.\d)`, `\$0/mo\b`, `\bon us\b`.
  - Verifies adjacent disclosure of plan name, plan $/mo, trade-in clause.
  - Secondary conditions (AutoPay, credit period months, "credits stop")
    are required UNLESS this is SMS, ≤200 chars, AND has `novatel.com/t`
    safe-harbor terms link.
  - Returns `{verified, has_free_claim, missing_conditions,
    secondary_waived_via_terms_link, rule_ids_implicated}`.
- `check_trade_in_eligibility(text, offer_id) → dict` — flags "any phone"
  language when registry restricts to Apple/Samsung/Google good condition.

### 5.3 `content_analysis.py`
- `detect_superlatives(text)` — flags "fastest", "best", "#1",
  "industry-leading" with citation requirement (FTC-017, BRAND-202).
- `detect_urgency_language(text)` — "act now", "hurry", "limited time"
  (BRAND-102).
- `detect_all_caps(text)` — headlines/subjects (BRAND-103).
- `detect_prohibited_phrases(text, channel)` — channel-aware match against
  BRAND-3xx prohibited list.
- `detect_passive_voice(text)` — light regex; SOFT only (BRAND-105).
- `score_readability(text)` — Flesch Reading Ease.
- `extract_claims(text)` — heuristic typed claims (price, speed,
  superlative, savings, coverage, trade-in).

### 5.4 `channel_validation.py`
- `identify_channel(text)` — best-effort classifier.
- `get_channel_spec(channel, audience) → dict` — limits + mandatory elements.
- `count_characters / count_words`.
- `validate_length(text, channel, audience) → {verified, rule_ids_implicated, ...}`
  — returns `verified=True` when within limits, with the per-channel
  rule_id set so the runner's verified-rule filter can demote LLM
  re-flagging of BRAND-401/402/403/404/405/406.
- `validate_mandatory_elements(text, channel, offer_id?)` — verifies
  Msg&Data, STOP, T&C link, unsubscribe, credit-period clause. The
  `offer_id` makes "(if applicable)" elements offer-aware: a Prepaid
  Visa offer with no `credit_period_months` does not need the
  credit-period element.
- `validate_cta(text, channel, audience)` — CTA registry check
  (BRAND-603).
- `validate_utm(text_or_url)` — `utm_source/medium/campaign` presence
  (BRAND-604). SMS short-link `novatel.com/t` is exempt.
- `check_audience_fit(channel, audience)` — flags SMS-to-VP+ etc.
  (BRAND-501).

### 5.5 `content_generation.py` (Resolver only)
- `replace_prohibited_terms(text)` — 22-entry substitution table
  ("guaranteed" → "we stand behind", "click here" → "shop now",
  "truly unlimited" → "unlimited", "no throttling" → "with
  speed-management during congestion").
- `add_utm_to_text(text, channel, campaign)` — appends `utm_source/medium/
  campaign` to every URL; SMS collapses to `novatel.com/t`.
- `add_mandatory_elements(text, channel)` — appends per-channel mandatory
  tail (Msg&Data, STOP, T&C link, unsubscribe).
- `truncate_to_channel(text, channel)` — smart truncate preserving the
  mandatory tail.
- `apply_disclosure(text, offer_id, channel)` — injects the registry's
  canonical disclosure adjacent to the claim.
- `fewshot_good_samples(channel, audience, k)` — picks K compliant samples
  for the Resolver's few-shot prompt.

---

## 6. Tool registry exposed to the LLM

Each critic gets a curated subset; the Resolver gets the generation tools.

| Tool | Used by | Returns | Rule IDs implicated |
|------|---------|---------|---------------------|
| `search_regulations` | FCC, Brand, Tech | `list[dict]` | any FTC-* |
| `get_rule` | all | `dict \| None` | varies |
| `search_brand_rules` | Brand, Ops | `list[dict]` | any BRAND-* |
| `list_prohibited_terms` | Brand | `list[dict]` | BRAND-3xx, 6xx |
| `get_required_citations` | Brand, Tech | `dict` | BRAND-7xx/8xx, FTC-* |
| `lookup_offer` | FCC, Brand, Tech | `dict \| None` | varies |
| `find_offer_by_content` | FCC, Persona, Tech | `list[dict]` | offers |
| `verify_claim` | Tech | `dict` | BRAND-701, BRAND-801 |
| `get_mandatory_disclosure` | FCC, Brand | `str \| None` | FTC-005, BRAND-801 |
| `check_price_accuracy` | FCC, Brand, Tech | `dict` | FTC-005, BRAND-302, BRAND-801 |
| `check_trade_in_eligibility` | FCC, Tech | `dict` | FTC-012, FTC-013 |
| `detect_superlatives` | FCC, Brand | `list[dict]` | FTC-017, BRAND-202 |
| `detect_urgency_language` | Brand | `list[dict]` | BRAND-102 |
| `detect_all_caps` | Brand | `list[dict]` | BRAND-103 |
| `detect_prohibited_phrases` | Brand | `list[dict]` | BRAND-3xx, 6xx |
| `detect_passive_voice` | Brand | `list[dict]` | BRAND-105 |
| `score_readability` | Brand | `dict` | advisory |
| `extract_claims` | Tech | `list[dict]` | BRAND-701..805 |
| `identify_channel` | Ops | `str` | advisory |
| `get_channel_spec` | Ops, Persona | `dict` | BRAND-5xx |
| `count_characters / count_words` | Ops | `int` | advisory |
| `validate_length` | Ops | `dict` | BRAND-401..406 |
| `validate_mandatory_elements` | FCC, Ops | `dict` | FTC-014, BRAND-401/403/404 |
| `validate_cta` | Brand, Ops | `dict` | BRAND-603 |
| `validate_utm` | Brand, Ops | `dict` | BRAND-604 |
| `check_audience_fit` | Persona, Ops | `dict` | BRAND-501 |
| `replace_prohibited_terms` | Resolver | `dict` | rewrite |
| `add_utm_to_text` | Resolver | `str` | rewrite |
| `add_mandatory_elements` | Resolver | `str` | rewrite |
| `apply_disclosure` | Resolver | `str` | rewrite |

Tools are bound to the LLM via LangChain's `bind_tools`; the model issues
function calls, the runner executes them, appends results to the audit
trail, and feeds them back as `ToolMessage`s.

---

## 7. Agents in detail

Each critic has: a **persona system prompt**, a **tool subset**, a
**deterministic fallback**, and a **rule lane** (which rule_id ranges they're
allowed to cite).

### 7.1 ⚖️  FCC Enforcer (`fcc_enforcer`)
- **Persona:** Senior FCC compliance attorney. Cold, precise, citation-driven.
- **Lane:** `FTC-001..020` only.
- **Tools:** `search_regulations`, `get_rule`, `lookup_offer`,
  `verify_claim`, `check_price_accuracy`, `check_trade_in_eligibility`,
  `validate_mandatory_elements`.
- **Deterministic fallback (`_fcc_fallback`):**
  1. `check_price_accuracy(offer_id)` → FTC-005 if any "$0/free" claim is
     missing required disclosure adjacency.
  2. `check_trade_in_eligibility(offer_id)` → FTC-013 if "any phone" claim
     contradicts registry.
  3. Superlative regex without citation → FTC-017.
  4. Unlimited / no-throttling per-se deceptive regex → FTC-008.
  5. SMS only: `validate_mandatory_elements("SMS", offer_id)` → FTC-014 if
     Msg&Data/STOP/terms missing.

### 7.2 🛡️  Brand Guardian (`brand_guardian`)
- **Persona:** Chief Brand Officer with institutional NovaTel memory.
- **Lane:** BRAND-101..106, 201..208, 301..315, 601..604.
- **Tools:** brand-bible search, content-analysis suite, `validate_cta`,
  `validate_utm`.
- **Fallback (`_brand_fallback`):**
  1. `detect_prohibited_phrases(channel)` → BRAND-3xx.
  2. `detect_urgency_language` → BRAND-102.
  3. `detect_all_caps` → BRAND-103.
  4. `detect_superlatives` → BRAND-202 if unsourced.
  5. `validate_cta(channel, audience)` → BRAND-603.
  6. `validate_utm()` → BRAND-604 (SMS short-link exempt).
  7. `check_price_accuracy()` to record `verified=True` so the runner's
     verified-rule filter knows BRAND-302 is structurally satisfied.
  8. `check_unlimited_qualifier` audit — every "unlimited" must be followed
     by a plan name (Starter|Extra|Premium|Ultimate|Business|Home) OR a
     deprioritization disclosure must be present → else BRAND-301.

### 7.3 👥 Persona Simulator (`persona_simulator`)
- **Persona:** Adopts the target audience first-person ("As a small-business
  owner, I'd react to this by…").
- **Lane:** BRAND-501..504.
- **Tools:** brand search §5, `check_audience_fit`, `get_channel_spec`,
  `lookup_offer`.
- **Fallback (`_persona_fallback`):**
  1. `check_audience_fit(channel, audience)` → BRAND-501.
  2. Audience-specific jargon map → BRAND-502 SOFT (e.g.,
     "deprioritization" for Consumer, "awesome" for Executive).

### 7.4 🔬 Technical Lead (`technical_lead`)
- **Persona:** Senior product manager who actually built the offers.
  Forensic, registry-driven.
- **Lane:** BRAND-701..704, 801..805.
- **Tools:** offer-verification suite, `extract_claims`.
- **Fallback (`_tech_fallback`):**
  1. `extract_claims()` → for each, `verify_claim(claim, offer_id)`.
  2. Registry contradictions → BRAND-701 HARD.
  3. Missing offer conditions (AutoPay, credit period) → BRAND-801 HARD.
  4. Skips plan/trade-in (those are FCC's lane via FTC-005).

### 7.5 📋 Ops Strategist (`ops_strategist`)
- **Persona:** Marketing Ops Quality Lead.
- **Lane:** BRAND-401..406, 601..604.
- **Tools:** channel-validation suite, brand search.
- **Fallback (`_ops_fallback`):**
  1. `validate_length(text, channel, audience)` → BRAND-40x per channel
     (records `verified=True` when within limits).
  2. `validate_mandatory_elements(text, channel, offer_id)` — offer-aware:
     "(if applicable)" elements skip when registry says N/A → BRAND-401/403.
  3. `validate_utm()` → BRAND-604 (SMS short-link exempt).
  4. `validate_cta(channel, audience)` → BRAND-603.

---

## 8. The runner: precision passes and approval ratchet

`backend/app/agents/runner.py` is the heart of the precision strategy.
`run_critic(name, system_prompt, tools, fallback, content, intake,
iteration, audit, prior_state)` applies these passes:

### Pass 0 — Always-on deterministic fallback
Returns a baseline list of structurally-grounded violations. Runs even when
the LLM is configured. This is the "sanity floor" — even if the LLM never
returns, the user still gets a verdict.

### Pass 1 — Schema and lane validation
1. Drop violations whose `rule_id` is not in `_valid_rule_ids()` (the union
   of all loaded `rule_id`s in the data).
2. Drop violations whose rule_id is out of the agent's lane via
   `_in_lane(name, rule_id)`. The Brand Guardian cannot cite FTC-005.

### Pass 2 — Grounding filter
`_grounded_rule_ids(audit, agent, iteration)` walks the per-iteration audit
trail and collects every `rule_id` the LLM actually surfaced via a tool call:
- Direct: `get_rule(rule_id=X)` → adds X.
- Indirect: `search_regulations() / search_brand_rules()` → extracts
  `rule_id` fields from the result list.

LLM-claimed rule_ids absent from this set AND absent from the deterministic
flag set are **dropped**. (Effect: the LLM can't fabricate a "BRAND-999".)

### Pass 2.5 — Verified-rule filter
`_verified_rule_ids(audit, agent, iteration)` collects rule_ids that a
deterministic tool **explicitly affirmed** as compliant:
- `check_price_accuracy(verified=True)` → {FTC-005, BRAND-302, BRAND-801}.
- `validate_length(verified=True)` → per-channel BRAND-40x.
- `validate_mandatory_elements(verified=True)` → BRAND-401/403/etc.
- `validate_cta(verified=True)` → BRAND-603.
- `validate_utm(verified=True)` → BRAND-604.

LLM cites of these `rule_id`s are dropped. **Structural proof overrides LLM
re-flagging.** This was the fix that stopped the Brand Guardian from re-flagging
BRAND-302 after the Resolver had already inserted the disclosure.

### Pass 3 — Approval ratchet
If the LLM is configured AND `prior_state[agent].ever_approved` is True,
demote new HARD violations from this round to SOFT — **unless** the
deterministic fallback also flagged the same rule_id.

This is what kills the oscillation pattern. A critic that approved in round
1 cannot suddenly fail round 2 on a stylistic re-read; only a real
structural regression can re-block.

### Approval ratchet state
```python
build_prior_state(iterations) → {
    "fcc_enforcer": {
        "approved": bool,         # APPROVE in latest iteration
        "ever_approved": bool,    # APPROVE in any iteration so far
        "prev_rule_ids": set,     # rule_ids flagged in latest iter
    },
    ...
}
```

The runner reads it; the Resolver also reads it to build the
DO-NOT-REGRESS instruction.

### Final merge
After all passes, deterministic and LLM violations are merged and deduped on
`(rule_id, span)`. Verdict is recomputed deterministically:
- If any HARD remains → `REVISE`.
- Else → `APPROVE`.

So the **verdict and score are always consistent**: an `APPROVE` cannot
have a HARD violation under it, by construction.

---

## 9. Resolver: aggregation and rewrite

`backend/app/agents/resolver.py` runs once per round after critics complete.

### 9.1 Scoring (per agent, 1–10)
```
APPROVE with K SOFT violations → 10 - min(2, K)        clamped [8, 10]
REVISE  with H HARD, S SOFT    → 7 - 2*H - S            clamped [1, 7]
```
Composite iteration score = mean of agent scores, rounded to .1.

### 9.2 Pre-LLM deterministic fixes
Always run, regardless of LLM availability. Five passes in order:
1. `replace_prohibited_terms(text)`.
2. `add_utm_to_text(text, channel, campaign)`.
3. `apply_disclosure(text, offer_id, channel)`.
4. `truncate_to_channel(text, channel)` — preserves mandatory tail.
5. `add_mandatory_elements(text, channel)`.

The output is the **DRAFT**. This alone produces a measurable improvement
even if the LLM is unavailable.

### 9.3 Compliance brief
`_compliance_brief(intake, verdicts, prior_state)` builds an imperative
prompt block with:
- Verbatim offer registry values (plan, $/mo, credit-months, AutoPay,
  trade-in clause).
- The SMS short-link safe-harbor explanation, when applicable.
- One bullet per critic listing only their HARD violations.
- A **DO-NOT-REGRESS** section: "Critics who already approved are
  `[brand_guardian, persona_simulator]`. Make MINIMUM edits to satisfy the
  remaining REVISE feedback. Do NOT restructure aspects these critics
  reviewed; do NOT reintroduce phrasing they would flag."

### 9.4 LLM rewrite
If the LLM is configured, the Resolver builds a prompt with:
- Original content + intake.
- Compliance brief (above).
- Per-critic JSON verdicts (with scores).
- Few-shot good samples matching `(channel, audience)`.
- The DRAFT (so the LLM can either accept or further refine).

The LLM returns strict JSON: `{revised_content, changelog, composite_score,
all_approved, violations_resolved, violations_unresolved}`.

If the LLM fails or returns malformed JSON, the DRAFT + a deterministic
changelog is returned. There is no second-attempt LLM call within an
iteration; the next iteration is a full critic round again.

---

## 10. LangGraph state machine

```
        ┌────────┐
        │ intake │  parse hints, set iteration=1, current_content
        └───┬────┘
            │
            ▼
        ┌────────┐
        │fan_out │  spawn 5 critic nodes via asyncio.gather
        └───┬────┘
            │
   ┌────────┼────────┬────────┬────────┐
   ▼        ▼        ▼        ▼        ▼
  FCC    Brand   Persona   Tech     Ops    (each appends to verdicts + audit)
   │        │        │        │        │
   └────────┴────────┴────────┴────────┘
                     │
                     ▼
                 ┌────────┐
                 │aggregate│  build IterationRecord, run resolver if needed
                 └───┬────┘
                     │
                     ▼
                 ┌────┐
                 │gate│
                 └─┬──┘
                   │
         converged │ else iter < max
                   │   ▼
                   │ fan_out (loop)
                   ▼
                  END
```

Reducer note: `verdicts` and `iterations` are typed
`Annotated[list[X], operator.add]` so concurrent critic nodes can append
without locks. Conditional edge is in `gate`.

---

## 11. API and WebSocket protocol

### 11.1 REST endpoints
| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/offers` | list offers (id, headline) |
| `GET`  | `/api/samples/violation` | violation eval set |
| `GET`  | `/api/samples/good` | clean reference samples |
| `GET`  | `/api/rules/regulatory` | FTC-* catalog |
| `GET`  | `/api/rules/brand` | BRAND-* catalog |
| `POST` | `/api/review` | sync review (blocks until done) |

### 11.2 WebSocket
`ws://host/api/ws/review`. Client sends `ReviewRequest` JSON once. Server
streams events:

| Event | Payload | UI effect |
|-------|---------|-----------|
| `intake` | `IntakeMetadata` | populate Original panel, Intake details |
| `critic` | `CriticVerdict` | flip the agent card from thinking → verdict |
| `iteration` | `IterationRecord` (with `revised_content`, `changelog`) | append to score chart, fill Resolver panel |
| `done` | `ReviewResponse` | reveal User Gate |
| `error` | `{error: str}` | red banner |

The server runs the loop synchronously inside the WS handler; each round
spawns critics with `asyncio.to_thread` so that LLM calls don't block the
event loop, and emits each verdict immediately as it returns.

### 11.3 Error semantics
- Intake parse failure → emit `error`, close.
- LLM failure on a critic → fall back to deterministic-only verdict; do
  not abort.
- Tool call failure → log error to audit, return `{error: str}` in the
  ToolMessage, let the LLM handle gracefully.
- JSON parse failure → log, fallback to deterministic verdict.
- Iteration cap hit → emit final `done` with `converged=false`.

---

## 12. Frontend architecture

### 12.1 Routes
| Path | Page |
|------|------|
| `/` | UploadPage — channel + audience filters, content textarea, 5-agent strip |
| `/review` | ReviewPage — 3-pane resizable layout, live streaming |
| `/report` | ReportPage — full audit, diff, violations table, export |

### 12.2 Global state
`ReviewContext.tsx` holds `request`, `status`, `iterations`, `liveCritics`,
`auditTrail`, `final`, `error`, `selectedFinal`, plus `start / rerun /
cancel / reset`. Status transitions: `idle → running → done | error`.

The WS event handler:
- `intake` → setIntake.
- `critic` → push onto `liveCritics`.
- `iteration` → push onto `iterations` (renumbered to total rounds for
  rerun history), clear `liveCritics`.
- `done` → store `final`, append `audit_trail`, set status to `done`.

`rerun(newContent)` reopens the WS with `preserveHistory=true`, so the
user can run as many adversarial rounds as desired and have all of them
visible in the report.

### 12.3 Review page panes
- **Original** (left) — channel/audience pills, read-only content.
- **Agent Courtroom** (center) — 5 cards in fixed order; live thinking
  pips → verdict badge → cited violations. ScoreProgressionChart appears
  after the first iteration completes. Intake details collapsible.
- **Resolver** (right) — `Iteration N` label, DiffView (word-level LCS)
  before/after, changelog markdown.

Two drag handles between panes resize column widths; widths persist to
`localStorage` keys `guardian.leftW` and `guardian.rightW`. Below 1024px
the layout collapses to a single column and handles hide.

### 12.4 User Gate
Appears after each round. Lets the user pick **any** prior version
(original, round 1 rewrite, round 2 rewrite, …) and:
1. Accept as final → navigate to `/report`.
2. Edit & re-review → open inline textarea, edit, submit, fire a new round
   with the edited content.
3. Run another round on the chosen version.

### 12.5 Report page
- Result banner (converged/non-converged, score, rounds, elapsed).
- Smaller score chart + verdicts-per-round table.
- Side-by-side DiffView (original vs. final).
- HARD/SOFT violations grouped by rule_id.
- Tool-call summary + collapsible full audit trail JSON.
- Buttons: copy final content, export audit trail JSON, back to review.

---

## 13. Scoring, convergence, and iteration policy

### 13.1 Per-agent score
```
APPROVE: 10 - min(2, soft_count)         → clamped [8, 10]
REVISE : 7 - 2*hard_count - soft_count   → clamped [1, 7]
```
APPROVE always lives at 8–10, REVISE at 1–7. By construction, verdict and
score never disagree.

### 13.2 Composite (iteration) score
Mean of the 5 agent scores, rounded to one decimal. This is what the
ScoreProgressionChart plots round over round.

### 13.3 Convergence
A round converges iff **all 5 critics return APPROVE** (no quorum, no
threshold). The runner's verdict-from-violations recomputation guarantees
that any APPROVE has zero HARD violations.

### 13.4 Iteration cap
`GUARDIAN_MAX_ITERATIONS` env var, default 1 (single-pass). For
demonstrations we run with 3. The cap is the second exit condition.

### 13.5 Why an iteration cap?
Even with the approval ratchet, three rounds is enough to converge in
~95% of cases on the eval set. Beyond that, the marginal value of more
rounds is dwarfed by latency cost (each round is ~4–6s). The User Gate
is a better escape valve — the human can fire another round explicitly.

---

## 14. Evaluation harness

`backend/app/eval/run_eval.py`:

```python
def evaluate() -> dict:
    samples = violation_samples()["samples"]
    for sample in samples:
        intake = run_intake(sample.content, ...)
        verdicts = [run_critic(name, ...) for each of 5 critics]
        found = {(v.rule_id, agent) for v in violations}
        expected = sample.planted_violations
        compute_tp_fp_fn(found, expected)
    return {
        "overall": {tp, fp, fn, precision, recall, f1},
        "per_rule": {...},
        "per_sample": [...],
    }
```

This is what we use to measure regressions when changing prompts or
deterministic fallbacks. Precision was the priority — false positives
erode user trust faster than false negatives, because every FP becomes an
unnecessary edit cycle.

---

## 15. Tech stack and runtime topology

### Backend
- **Python 3.10+**, FastAPI, Uvicorn (ASGI).
- **LangGraph** for the state machine; **LangChain** for LLM client + tool binding.
- **Pydantic v2** for strict typed state and request/response models.
- **OpenAI / Azure OpenAI**, `gpt-4o-mini` class, `temperature=0`, function-calling.
- Pytest for smoke + eval.

### Frontend
- **React 18 + TypeScript + Vite 5**.
- **react-router-dom v6**.
- Native browser **WebSocket** API (no socket.io).
- Plain CSS (no UI library) — keeps bundle small and styling tight.

### Runtime
- Single backend process (Uvicorn, port 8000) with no horizontal sharding
  needed at hackathon scale.
- Single Vite dev server (port 5173) proxying `/api` and `/ws` to the
  backend.
- All state is in-memory; no DB. Each review is fully ephemeral.
- LLM calls are the only network IO outside the box.

### Scaling notes (if we productionized)
- The backend is async-safe (LLM calls go through `asyncio.to_thread`) and
  could be horizontally scaled behind a load balancer; the WS endpoint
  needs sticky sessions because the iteration loop runs inside one
  socket.
- The data layer is read-only and `@lru_cache`'d — trivially replicable.
- A SQL or document store would be needed for: review history, audit
  archival, multi-user tenancy, role-based access.

---

## 16. Security, observability, and operational concerns

### 16.1 Secrets
- API keys read from env (`OPENAI_API_KEY` or `AZURE_OPENAI_*`). Never
  logged. Not stored client-side.
- CORS origins are configurable via `GUARDIAN_CORS_ORIGINS`.

### 16.2 Input handling
- The `content` field is treated as untrusted text and never executed; the
  LLM sees it as a string. No code paths `eval` or `exec` it.
- Tools that operate on text (regex, substring) are bounded.

### 16.3 Audit trail
Every tool call (deterministic + LLM) is logged to `ToolCallTrace`:
`{agent, tool, input, output, iteration, ts}`. The full trail is returned
in the `ReviewResponse` and exportable as JSON from the report page.

This is the system's transparency story. Any flagged violation can be
traced to the exact tool call that produced its `rule_id`.

### 16.4 Failure modes and responses
| Failure | Response |
|---------|----------|
| LLM unavailable | All 5 critics + Resolver fall back to deterministic-only; output is still useful |
| LLM returns invalid JSON | Drop LLM violations, keep deterministic; mark in audit |
| Tool exception | Log to audit, return `{error: str}` to LLM, continue |
| WebSocket dropped | Frontend shows error banner; user can reload and resubmit |
| Iteration cap hit | Emit `done` with `converged=false`; user accepts or reruns |

### 16.5 No PII
The system handles marketing copy only. No customer data flows through it.

---

## 17. Design trade-offs and answers to expected architect questions

### Q: Why five critics instead of one big "compliance prompt"?
- Cognitive load: a single LLM prompt asked to enforce 100+ rules across
  five domains drops violations and hallucinates rule IDs.
- Observability: separating lanes lets us measure precision/recall **per
  agent** in eval, and surface a dedicated card in the UI.
- Evolvability: adding a sixth lane (e.g., accessibility) is dropping in
  one critic + one rule range, not editing a megaprompt.

### Q: Why parallel rather than sequential critics?
- Latency: 5 critics ≈ 4–6s wall clock when parallel, vs ~25s sequential.
- Independence: sequential critics tend to anchor on each other's
  framings. Parallel keeps lanes pure.

### Q: Why deterministic fallbacks at all if you have an LLM?
Three reasons:
1. **Trust floor.** Even when the LLM API is down or rate-limited, users
   get a real verdict.
2. **Grounding source.** The runner's grounding/verified-rule passes need
   structurally-known truths to filter hallucinated LLM cites against.
3. **Eval baseline.** It lets us A/B compare LLM-on vs LLM-off on the
   eval set, which is how we prove the LLM adds value (or where it
   regresses).

### Q: How do you stop the LLM from inventing rule IDs?
Three layers: (a) lane filter rejects out-of-range IDs, (b) allowlist
filter rejects unknown IDs, (c) grounding filter requires the rule_id to
have surfaced in this round's audit trail OR in the deterministic flag
set. After those passes, an "FCC-999" or "GDPR-X" is impossible.

### Q: How do you stop two critics from oscillating?
Approval ratchet, three layers: runner Pass #3 (demote LLM HARD to SOFT
post-approval), Resolver DO-NOT-REGRESS instruction, and the iteration
cap. We measured this against a deliberately-tricky Prepaid Visa offer
case that previously cycled forever; it now converges in 1–2 rounds.

### Q: Why not put the rules in a vector DB?
Volume is small (~120 rules total) and shape is structured (each rule
has a stable ID, severity, applies-to channel, examples). Keyword + ID
lookup is exact and fast. A vector DB would add dependency, latency, and
a fuzziness layer that hurts rule_id integrity.

### Q: What about agent-to-agent communication?
Deliberately disallowed for the critic round. Critics are pure functions
of `(content, intake, prior_state)`. The Resolver is the only node that
sees all five verdicts. This makes critic outputs reproducible and
unit-testable.

### Q: How do you handle conflicting verdicts?
The Resolver's compliance brief includes every HARD violation from every
critic; the rewrite must satisfy all of them. SOFT violations are
optional. If a HARD-vs-HARD conflict surfaces (e.g., "shorten" vs "add
disclosure"), the channel spec wins (we apply the disclosure first, then
truncate while preserving the mandatory tail).

### Q: What's the single point of failure?
The LLM provider. We mitigate with the always-on deterministic fallback,
but a high-quality rewrite still depends on the LLM. In a production
setting we'd add a second provider as failover.

### Q: Latency budget?
- Intake: ~50ms (deterministic).
- 5 critics in parallel: 3–5s with `gpt-4o-mini` and 5–8 tool calls each.
- Resolver: 2–4s.
- Per round wall clock: 5–9s. End-to-end for a 3-round case: 15–25s.

### Q: Cost?
- ~5–8 tool calls × 5 critics × 200–500 tokens each = 5–10k input + 1–2k
  output tokens per round.
- At `gpt-4o-mini` rates this is fractions of a cent per review.

### Q: What's the verdict's truth model?
For HARD violations: structurally provable (registry mismatch, char limit
exceeded, missing mandatory element). For SOFT: heuristic / stylistic.
This split is intentional — it lets the rewrite loop terminate
deterministically.

---

## 18. Roadmap and known limitations

Known limitations:
1. **No persistence layer.** Every review is ephemeral.
2. **Single-shot Resolver.** One LLM rewrite per iteration; no internal
   refinement loop.
3. **Hardcoded carrier (NovaTel).** Multi-tenant requires per-tenant data
   files and a tenant key on every API call.
4. **English-only.** No localization, no script-aware char counting.
5. **No image / video review.** Text-only marketing assets.
6. **No regression detector across reviews.** Each review is independent;
   we don't yet detect "this offer's copy is drifting over time".

Natural roadmap:
- Database (Postgres) for review history + audit archival.
- Multi-tenant data routing.
- Structured editor view (per-clause severity highlighting in-place).
- Image OCR + visual disclosure proximity check (FTC has explicit rules
  about disclosure prominence in banner ads).
- Automated A/B regression on changes to rule data or prompts (extend the
  existing eval harness into CI).

---

*End of architect deep-dive.*
