# Guardian AI

> Multi-agent adversarial compliance engine for telecom marketing content.

Guardian AI reviews marketing content (SMS, Email, LinkedIn, Landing Pages,
Press Releases) against FCC/FTC regulations and the carrier's brand bible.
**Five specialized critic agents** run **in parallel**, each red-teaming a
different failure mode using a curated toolkit of deterministic Python
functions. A **Resolver agent** aggregates their verdicts and rewrites the
content. A **User Gate** then lets a human accept, edit, or re-run.

📖 **Documentation**
- [docs/Guardian-AI-Overview.md](docs/Guardian-AI-Overview.md) — narrative summary
- [docs/Guardian-AI-Worked-Example.md](docs/Guardian-AI-Worked-Example.md) — one SMS submission traced end-to-end through every layer
- [docs/Guardian-AI-Architect-Deep-Dive.md](docs/Guardian-AI-Architect-Deep-Dive.md) — full architect-grade walkthrough
- [GuardianAI-ProjectContext.md](GuardianAI-ProjectContext.md) — quick in-IDE context

---

## Architecture at a glance

```
                   ┌─────────────────────────────────────────────┐
   user ──► Intake ─►  ┌──► ⚖️  FCC Enforcer       ┐
                       ├──► 🛡️  Brand Guardian      │
                       ├──► 👥 Persona Simulator   ├──► Resolver ──► User Gate
                       ├──► 🔬 Technical Lead      │       ▲
                       └──► 📋 Ops Strategist      ┘       │
                                                            │
                              converged?  ◄─── loop (cap) ──┘
```

- **LangGraph topology:** `intake → fan_out_critics → aggregate → resolver → gate → (loop|end)`
- **Approval ratchet:** once a critic approves, only a deterministic regression can re-block them. Stops oscillation.
- **Tool-grounded:** every cited `rule_id` traces back to a Python tool call in the audit trail.
- **Live streaming:** per-critic verdicts stream over WebSocket as they complete.

## Tech stack

- **Backend** — Python 3.10+, FastAPI + Uvicorn, LangGraph, LangChain, Pydantic v2
- **Frontend** — React 18 + TypeScript + Vite 5, react-router-dom v6
- **LLM** — Azure OpenAI (`gpt-5.4-beta` deployment, function-calling, `temperature=0`); also supports OpenAI
- **Data** — JSON + CSV ground truth in [backend/app/data/](backend/app/data/) (FCC/FTC rules, brand bible, 15-offer registry, channel matrix, eval samples)

## Repo layout

```
GuardianAI/
├── docs/                                  Architecture docs
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   └── app/
│       ├── main.py                        FastAPI entrypoint
│       ├── config.py                      env-driven config
│       ├── api/routes.py                  REST + WebSocket endpoints
│       ├── graph/state_graph.py           LangGraph topology
│       ├── agents/
│       │   ├── intake.py                  parse channel/audience/offer/claims
│       │   ├── llm.py                     OpenAI/Azure client factory
│       │   ├── runner.py                  generic critic runner + approval ratchet
│       │   ├── critics.py                 5 critic dispatchers + deterministic fallbacks
│       │   └── resolver.py                aggregator + rewriter
│       ├── skills/                        5 deterministic toolkits
│       ├── models/schemas.py              Pydantic schemas
│       ├── eval/run_eval.py               precision/recall harness
│       └── data/                          source JSON/CSV
└── frontend/
    └── src/
        ├── main.tsx                       router + ReviewProvider
        ├── api/client.ts                  REST + WebSocket helpers
        ├── state/ReviewContext.tsx        global review state
        ├── pages/
        │   ├── UploadPage.tsx             channel/audience filters + content editor
        │   ├── ReviewPage.tsx             3-pane resizable live view
        │   └── ReportPage.tsx             audit trail + diff + export
        ├── components/
        │   ├── TopBar.tsx
        │   ├── AgentCourtroom.tsx         5-card live verdict grid
        │   ├── AgentCard.tsx
        │   ├── OriginalContentPanel.tsx
        │   ├── ResolverPanel.tsx
        │   ├── DiffView.tsx               word-level LCS diff
        │   ├── ScoreProgressionChart.tsx
        │   └── UserGate.tsx
        └── types/index.ts                 TS mirror of Pydantic models
```

## The 5 critics

| Agent | Lane (rule_ids) | Tools |
|---|---|---|
| ⚖️  **FCC Enforcer** | `FTC-001..020` | compliance_lookup + offer_verification + `validate_mandatory_elements` |
| 🛡️  **Brand Guardian** | `BRAND-1xx, 2xx, 3xx, 6xx` | compliance_lookup + content_analysis + cta/utm validation |
| 👥 **Persona Simulator** | `BRAND-5xx` | brand search §5 + `check_audience_fit` + `get_channel_spec` |
| 🔬 **Technical Lead** | `BRAND-7xx, 8xx` | offer_verification suite + `extract_claims` |
| 📋 **Ops Strategist** | `BRAND-4xx, 6xx` | channel_validation suite |

Each critic has a **deterministic fallback** that runs the same skills
directly — so the system produces useful output even with no LLM key.

## Skills (toolkits)

| # | Skill | Tools |
|---|---|---|
| 1 | `compliance_lookup` | `search_regulations`, `get_rule`, `search_brand_rules`, `list_prohibited_terms`, `get_required_citations` |
| 2 | `offer_verification` | `lookup_offer`, `find_offer_by_content`, `verify_claim`, `get_mandatory_disclosure`, `check_price_accuracy`, `check_trade_in_eligibility` |
| 3 | `content_analysis` | `extract_claims`, `detect_superlatives`, `detect_urgency_language`, `detect_all_caps`, `detect_prohibited_phrases`, `detect_passive_voice`, `score_readability` |
| 4 | `channel_validation` | `identify_channel`, `get_channel_spec`, `count_characters/words`, `validate_length`, `validate_mandatory_elements`, `validate_cta`, `validate_utm`, `check_audience_fit` |
| 5 | `content_generation` (Resolver) | `replace_prohibited_terms`, `add_utm_to_text`, `add_mandatory_elements`, `truncate_to_channel`, `apply_disclosure`, `fewshot_good_samples` |

All tools are LangChain-bound in [`backend/app/skills/tools.py`](backend/app/skills/tools.py)
for LLM tool-calling.

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

# Optional but recommended for full capability
cp .env.example .env       # then add OPENAI_API_KEY (or AZURE_OPENAI_* vars)

# Smoke tests (no LLM needed)
pytest -q

# Eval harness — precision/recall over planted-violation samples
python -m app.eval.run_eval

# Run the API (auto-reload)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check: <http://127.0.0.1:8000/health>
OpenAPI docs: <http://127.0.0.1:8000/docs>

### 2. Frontend

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173 — proxies /api and /ws to :8000
```

### 3. Try a review

Open the UI, pick a channel + audience, paste content, hit **Run Review**.
Watch the 5 critic cards stream verdicts in real time, see the Resolver
rewrite, then accept / edit / re-run via the User Gate.

- The 3-pane review layout (Original · Courtroom · Resolver) is **resizable**;
  drag the vertical handles between panes. Widths persist in `localStorage`.
- The **User Gate** lets you pick any prior version (Original or any round's
  rewrite) as the basis for accept / edit-and-rerun / another round. The
  original content is preserved across re-runs so the report's Before/After
  diff always compares the true first input against the final output.

Or hit the API directly:

```bash
curl -s -X POST http://127.0.0.1:8000/api/review \
  -H "Content-Type: application/json" \
  -d '{
    "content": "FREE iPhone 17 Pro!!! Switch today, get it free forever.",
    "channel": "sms",
    "audience": "new_customers"
  }' | jq
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/review` | Run the full review graph synchronously, return `ReviewResponse` |
| `WS`   | `/api/ws/review` | Stream `intake` / `critic` / `iteration` / `done` / `error` events live |
| `GET`  | `/api/offers` | Offer registry (15 offers) |
| `GET`  | `/api/samples/violation` | Planted-violation eval samples |
| `GET`  | `/api/samples/good` | Compliant reference samples |
| `GET`  | `/api/rules/regulatory` | FTC-* catalog |
| `GET`  | `/api/rules/brand` | BRAND-* catalog |

## Configuration

Env vars (see `backend/.env.example`):

| Var | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | _unset_ | enables OpenAI mode |
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_DEPLOYMENT` | _unset_ | enables Azure OpenAI mode |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name (only used when `OPENAI_API_KEY` is set) |
| `AZURE_OPENAI_DEPLOYMENT` | _unset_ | Azure deployment name (e.g. `gpt-5.4-beta`) |
| `AZURE_OPENAI_API_VERSION` | `2024-12-01-preview` | Azure API version |
| `GUARDIAN_MAX_ITERATIONS` | `1` | iteration cap (raise to 3 for full convergence demos) |
| `GUARDIAN_BLOCK_ON` | `HARD` | what counts as blocking (`HARD` or `ALL`) |
| `GUARDIAN_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | CORS allowlist |

## Without an LLM key

The system still works. Each critic falls back to its deterministic skill
pipeline; the Resolver applies its 5-pass deterministic rewrite (term swap,
UTM injection, disclosure injection, channel truncation, mandatory tail).
Adding an OpenAI/Azure key boosts judgment-heavy lanes (BRAND-7xx
substantiation, FTC-011/-018/-020) and produces polished rewrites.

## Convergence & audit

- **Severity:** rules are `HARD` or `SOFT`. `GUARDIAN_BLOCK_ON=HARD` (default)
  treats only HARD as blocking; set `ALL` to require literal APPROVE on all 5
  critics.
- **Iterations:** capped by `GUARDIAN_MAX_ITERATIONS`.
- **Approval ratchet:** three layers — runner Pass #3 demotes new LLM-only
  HARD violations from already-approved critics to SOFT; the Resolver brief
  includes a DO-NOT-REGRESS instruction; the iteration cap is the hard exit.
- **Audit trail:** every tool call (input + output + agent + iteration) is
  captured in `ReviewResponse.audit_trail` and exportable from the report
  page as JSON.
- **Changelog:** every iteration includes a markdown `changelog` listing the
  rule_ids addressed.

## Eval

```bash
cd backend
python -m app.eval.run_eval
```

Reports precision / recall / F1 per `rule_id` against the planted violations
in `violation_content_samples.json`. Use this as the regression bar when
changing prompts or deterministic fallbacks.

---

_Built for the AI Agents in Marketing Operations track, Microsoft Hackathon 2026._
