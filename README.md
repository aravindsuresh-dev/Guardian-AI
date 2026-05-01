# 🛡️ Guardian AI

> Multi-agent adversarial compliance engine for telecom marketing content.

Guardian AI reviews marketing content (SMS, email, social, landing pages, press
releases) against FCC/FTC regulations and the carrier's brand bible. Five
specialized critic agents run **in parallel**, each red-teaming a different
failure mode using a curated toolkit of deterministic Python functions. A
Resolver agent aggregates their verdicts and rewrites the content. The loop
runs up to 3 iterations until all 5 critics return APPROVE.

```
                 ┌──────────────────────────────────────┐
   user ──►  Intake Parser  ──►  ┌──► 🔴 FCC Enforcer       ┐
                                  ├──► 🟡 Brand Guardian    │
                                  ├──► 🟢 Persona Simulator ├──► Resolver ──► User Gate ─┐
                                  ├──► 🔵 Technical Lead    │                            │
                                  └──► 🟣 Ops Strategist    ┘                            │
                                                                 ▲                       │
                                            converged?  ◄────────┘                       │
                                                ▲                                        │
                                                └────── loop (max 3) ◄──────────────────-┘
```

## Stack

- **Backend** — Python 3.10+, FastAPI, LangGraph, LangChain, Pydantic v2
- **Frontend** — React 18 + TypeScript + Vite
- **LLM** — OpenAI or Azure OpenAI (chat-completions w/ tool-calling)
- **Data** — JSON + CSV ground-truth (FCC/FTC rules, brand bible, offer registry,
  channel matrix, eval samples) — see [backend/app/data/](backend/app/data)

## Repo layout

```
GuardianAI/
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   └── app/
│       ├── main.py               FastAPI entrypoint
│       ├── config.py
│       ├── api/                  REST + WebSocket routes
│       ├── graph/                LangGraph state machine (parallel critics + loop)
│       ├── agents/               5 critics + intake + resolver + LLM factory
│       ├── skills/               5 deterministic toolkits
│       ├── models/               Pydantic schemas
│       ├── eval/                 Eval harness vs. planted-violation samples
│       └── data/                 Source JSON/CSV
└── frontend/
    └── src/
        ├── App.tsx               Editor + live verdict stream + gate
        ├── components/
        │   ├── CriticCard.tsx
        │   └── IterationView.tsx
        ├── api/client.ts         REST + WebSocket clients
        └── types/                Shared TS types mirroring Pydantic
```

## Skills (toolkits)

| # | Skill | Used by | Tools |
|---|---|---|---|
| 1 | Compliance Lookup | FCC Enforcer, Brand Guardian | `search_regulations`, `get_rule`, `search_brand_rules`, `list_prohibited_terms`, `get_required_citations` |
| 2 | Offer Verification | FCC Enforcer, Persona Simulator, Technical Lead | `lookup_offer`, `find_offer_by_content`, `verify_claim`, `get_mandatory_disclosure`, `check_price_accuracy`, `check_trade_in_eligibility` |
| 3 | Content Analysis | Brand Guardian | `extract_claims`, `detect_superlatives`, `detect_urgency_language`, `detect_all_caps`, `detect_prohibited_phrases`, `detect_passive_voice`, `score_readability` |
| 4 | Channel Format Validation | Ops Strategist | `identify_channel`, `get_channel_spec`, `count_characters/words`, `validate_mandatory_elements`, `validate_cta`, `validate_utm`, `check_audience_fit`, `validate_length` |
| 5 | Content Generation | Resolver | `replace_prohibited_terms`, `add_utm_to_text`, `add_mandatory_elements`, `truncate_to_channel`, `apply_disclosure`, `fewshot_good_samples`, `generate_changelog` |

Every tool is also exposed as a LangChain `@tool` in
[`backend/app/skills/tools.py`](backend/app/skills/tools.py) for LLM tool-calling.

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

# Optional but recommended for full capability
cp .env.example .env       # then add OPENAI_API_KEY (or Azure vars)

# Smoke tests (no LLM needed)
pytest -q

# Eval harness — runs all 12 violation samples and prints precision/recall
python -m app.eval.run_eval

# Run the API (auto-reload)
uvicorn app.main:app --reload --port 8000
```

Health check: <http://localhost:8000/health>
OpenAPI docs:  <http://localhost:8000/docs>

### 2. Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 — proxies /api and /ws to :8000
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/review` | Run the full review graph synchronously, return `ReviewResponse` |
| WS   | `/api/ws/review` | Stream `intake` / `critic` / `iteration` / `done` events as the graph runs |
| POST | `/api/intake` | Just the intake parser (channel/audience/offer/claims) |
| GET  | `/api/offers` | Offer registry (15 offers) |
| GET  | `/api/samples/{violation,good}` | Test samples |
| GET  | `/api/rules/{regulatory,brand}` | Rule corpora |

## Without an LLM key

The system still works! Each critic has a **deterministic fallback** that runs
the same skills directly. The eval shows ~F1 0.5 with perfect recall on many
HARD rules (SMS TCPA, prohibited terms, all-caps, urgency, UTM, CTA). Adding
an OpenAI/Azure key boosts coverage on judgment-heavy rules (BRAND-7xx
substantiation, FTC-011/-018/-020) and produces a polished resolver rewrite.

## Data flow & convergence

- **Severity:** rules are HARD or SOFT. `GUARDIAN_BLOCK_ON=HARD` (default)
  treats only HARD violations as blocking; set `ALL` to require literal
  APPROVE on all 5 critics.
- **Iterations:** `GUARDIAN_MAX_ITERATIONS=3` (default).
- **Audit trail:** every tool call (input + output + agent + iteration) is
  captured in `ReviewResponse.audit_trail`.
- **Changelog:** every iteration includes a markdown `changelog` listing the
  rule_ids addressed.

## Eval

```bash
python -m app.eval.run_eval
```

Scores precision/recall/F1 per rule_id against the planted violations in
`violation_content_samples.json`. Use this as your CI / regression bar.

## Roadmap (post-hackathon)

- Diff view in the UI (highlight rule_id spans inline)
- Persistent audit storage (SQLite/Postgres) for compliance auditors
- Custom-rule authoring UI
- Multi-brand support (swap brand bibles per tenant)
- Foundry continuous-eval harness over `violation_content_samples.json`
