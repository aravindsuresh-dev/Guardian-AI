# Guardian AI — End-to-End Worked Example

> A single SMS submission traced through every layer: intake → 5 critic
> agents (skills + tools + LLM) → resolver → gate. Use this to understand
> exactly how skills, tools, and the LLM combine.

## The example input

A user pastes this in the upload page and selects **Channel: SMS,
Audience: New Customers, Offer ID: (auto-detect)**.

```
FREE iPhone 17 Pro!!! No catch, just switch today and get it absolutely
free forever. Limited time only! novatel.com
```

Frontend opens a WebSocket to `/api/ws/review` and sends:

```json
{
  "content": "FREE iPhone 17 Pro!!! No catch, just switch today and get it absolutely free forever. Limited time only! novatel.com",
  "channel": "sms",
  "audience": "new_customers",
  "offer_id": null
}
```

---

## STAGE 1 — Intake (`agents/intake.py`)

Pure deterministic. No LLM. Runs in ~50ms.

**Inputs processed:**
- Channel string `"sms"` → normalized to `"SMS"`
- Audience `"new_customers"` (already canonical)
- `offer_id=null` triggers **auto-detect** via
  `offer_verification.find_offer_by_content(text)`. The function scans the
  text for device keywords + offer-type keywords and ranks matches.

**Skill call: `find_offer_by_content`**
```python
# scans for: "iphone 17 pro" → matches OFF-001's device field
# scans for: "free", "$0", "trade" → matches OFF-001's offer_type=trade_in
[
  {"offer_id": "OFF-001", "confidence": 0.92,
   "headline": "Get iPhone 17 Pro on us with eligible trade-in"},
  {"offer_id": "OFF-007", "confidence": 0.31, ...}
]
```
Highest-confidence match wins → `offer_id="OFF-001"`.

**Skill call: `extract_claims`**
- "FREE iPhone 17 Pro" → claim_type=`price`, value=`$0`
- "absolutely free forever" → claim_type=`price`, modifier=`forever`
- "Limited time only" → claim_type=`urgency`

**WebSocket emit:**
```json
{ "type": "intake",
  "intake": {
    "channel": "SMS",
    "audience": "new_customers",
    "offer_id": "OFF-001",
    "extracted_claims": [
      {"type": "price", "value": "$0", "span": "FREE iPhone 17 Pro"},
      {"type": "price", "modifier": "forever", "span": "absolutely free forever"},
      {"type": "urgency", "span": "Limited time only"}
    ]
  }
}
```

UI: the Original panel populates with channel/audience pills, the offer pill
appears (`🏷️ OFF-001`), and the 5 agent cards show "thinking" pips.

---

## STAGE 2 — Parallel critic round (the courtroom)

LangGraph's `fan_out_critics` node spawns five concurrent tasks via
`asyncio.gather`. Each critic runs its **`run_critic()`** dispatcher in
[runner.py](../backend/app/agents/runner.py), which executes 5 passes:
**Pass 0** deterministic fallback always runs · **Pass 1** schema/lane
validation · **Pass 2** grounding filter · **Pass 2.5** verified-rule
filter · **Pass 3** approval ratchet.

We trace each critic separately.

---

### ⚖️ FCC Enforcer

#### Pass 0 — Deterministic fallback (`_fcc_fallback`)
Runs unconditionally, before any LLM call. It sequentially invokes:

**Tool 1: `check_price_accuracy(content, "OFF-001")`**

The skill (in [`offer_verification.py`](../backend/app/skills/offer_verification.py)):
1. Detects `\bfree\b`, `\$0`, `\bon us\b` patterns. Found "FREE", "free
   forever".
2. Looks up `OFF-001` in the offer registry CSV:
   ```
   plan_required: Unlimited Premium
   plan_monthly_cost: $85.99/mo
   autopay_required: yes
   trade_in_required: yes
   eligible_trade_in_brands: Apple|Samsung|Google
   trade_in_condition: good
   credit_period_months: 36
   monthly_credit_amount: $30.55
   total_promotional_credit: $1099.99
   mandatory_disclosure_text: "$0/mo on Unlimited Premium ($85.99/mo)
     w/ AutoPay + 36-mo bill credits + elig. trade-in (Apple/Samsung/
     Google, good cond.). Credits stop if you cancel/downgrade. Tax/fees
     extra. See novatel.com/t."
   ```
3. Verifies the disclosure of each required condition is present in the
   content adjacent to the claim:
   - plan name "Unlimited Premium" → ❌ missing
   - plan monthly cost "$85.99/mo" → ❌ missing
   - trade-in clause → ❌ missing
   - AutoPay, credit period, "credits stop" → ❌ missing
   - SMS short-link safe-harbor (`novatel.com/t`) → ❌ uses `novatel.com` (no `/t`)

**Returns:**
```json
{
  "verified": false,
  "has_free_claim": true,
  "missing_conditions": [
    "plan name (Unlimited Premium)",
    "plan monthly cost ($85.99/mo)",
    "trade-in requirement",
    "AutoPay requirement",
    "36-month credit period",
    "credits stop on cancellation"
  ],
  "secondary_waived_via_terms_link": false,
  "rule_ids_implicated": ["FTC-005", "BRAND-302", "BRAND-801"]
}
```
Audit trail entry written.

**Tool 2: `check_trade_in_eligibility(content, "OFF-001")`**

Scans for "any phone", "old phone", explicit brand restrictions. Content
says "just switch today" with no trade-in disclosure. Flags FTC-013 because
the "free" claim implies anyone qualifies but the registry restricts to
Apple/Samsung/Google in good condition.

**Tool 3: `detect_superlatives(content)`**

Scans for `\b(fastest|best|#1|industry-leading|most|top|leading)\b`. None
found in this sample → returns `[]`. No FTC-017 violation.

**Tool 4: regex check for "truly unlimited / no throttling"** → no match.
No FTC-008.

**Tool 5: `validate_mandatory_elements(content, "SMS", "OFF-001")`**

Channel spec for SMS requires:
- "Msg&Data rates" → ❌
- "Reply STOP" or "Text STOP" → ❌
- T&C link `novatel.com/t` → ❌ (only bare `novatel.com`)

Returns:
```json
{ "verified": false,
  "missing": ["Msg&Data rates", "STOP opt-out", "T&C link"],
  "rule_ids_implicated": ["FTC-014", "BRAND-401"] }
```

**Pass 0 violations produced (all HARD):**
- `FTC-005` × 6 (one per missing condition)
- `FTC-013` (trade-in eligibility unstated)
- `FTC-014` × 3 (Msg&Data, STOP, T&C link)

#### Pass 1 — LLM call

`get_chat_model()` returns the Azure OpenAI client bound to the
`gpt-5.4-beta` deployment. The runner sends:
- System prompt = `FCC_PROMPT` (FCC Enforcer persona, lane FTC-* only)
- User message = the content + intake summary + `JSON_INSTRUCTION`
- Tools bound = `COMPLIANCE_LOOKUP_TOOLS + OFFER_VERIFICATION_TOOLS +
  validate_mandatory_elements`

The model runs a tool-calling loop:

**LLM tool call 1:** `lookup_offer({"offer_id": "OFF-001"})` → registry row
returned.
**LLM tool call 2:** `check_price_accuracy({"content": "...", "offer_id": "OFF-001"})` → same dict as above (cached, but executed again so the audit captures it).
**LLM tool call 3:** `get_rule({"rule_id": "FTC-005"})` → returns the rule
text and example_violation.
**LLM tool call 4:** `validate_mandatory_elements({"text": "...", "channel": "SMS", "offer_id": "OFF-001"})` → missing list.

The LLM then returns its JSON envelope:
```json
{
  "verdict": "REVISE",
  "summary": "Multiple FTC violations: deceptive $0 claim missing required
   conditions (FTC-005), TCPA elements absent (FTC-014), trade-in
   eligibility misrepresented (FTC-013).",
  "violations": [
    {"rule_id": "FTC-005", "severity": "HARD",
     "description": "FREE iPhone 17 Pro claim lacks plan name, monthly
       cost, AutoPay/trade-in conditions adjacent to the claim",
     "span": "FREE iPhone 17 Pro!!!",
     "suggestion": "Inject offer registry's mandatory_disclosure_text"},
    {"rule_id": "FTC-013", "severity": "HARD",
     "description": "'just switch today' implies all customers qualify;
       trade-in restricted to Apple/Samsung/Google in good condition",
     "span": "just switch today",
     "suggestion": "State 'w/ elig. trade-in (Apple/Samsung/Google, good cond.)'"},
    {"rule_id": "FTC-014", "severity": "HARD",
     "description": "SMS missing Msg&Data, STOP opt-out, T&C link",
     "span": "novatel.com",
     "suggestion": "Append 'Msg&Data rates may apply. Reply STOP. Terms: novatel.com/t'"},
    {"rule_id": "BRAND-302", "severity": "HARD",
     "description": "Use of 'FREE' without immediate qualifier",
     "span": "FREE iPhone 17 Pro",
     "suggestion": "Replace with '$0/mo on Unlimited Premium...'"}
  ]
}
```

#### Pass 1 (filter) — schema/lane

The runner filters this list:
- `BRAND-302` ❌ **dropped** — outside FCC Enforcer's lane (FCC owns only
  `FTC-*`). Brand Guardian will flag it independently.
- `FTC-005`, `FTC-013`, `FTC-014` ✅ kept.

#### Pass 2 — grounding filter

`_grounded_rule_ids("fcc_enforcer", iteration=1)` walks the audit and
collects rule_ids that surfaced via tool calls this round:
- From `get_rule(FTC-005)` → `FTC-005`
- From `check_price_accuracy.rule_ids_implicated` → `FTC-005`, `BRAND-302`, `BRAND-801`
- From `validate_mandatory_elements.rule_ids_implicated` → `FTC-014`, `BRAND-401`

`FTC-013` is NOT in this set, but it IS in the deterministic fallback's
output → kept. ✅

#### Pass 2.5 — verified-rule filter
`_verified_rule_ids` collects rule_ids that a tool *affirmed compliant*
(`verified=True`). None this round (everything failed). No drops.

#### Pass 3 — approval ratchet
`prior_state["fcc_enforcer"].ever_approved = False` (this is round 1).
Skip.

#### Final merge
LLM violations + deterministic violations deduped on `(rule_id, span)`.
Result:
- 1× `FTC-005` HARD (description merged)
- 1× `FTC-013` HARD
- 1× `FTC-014` HARD (with full missing list in description)

Verdict recomputed: **REVISE**. Score: `7 - 2*3 - 0 = 1` (clamped to 1).

#### WebSocket emit
```json
{ "type": "critic",
  "verdict": {
    "agent": "fcc_enforcer", "verdict": "REVISE", "score": 1,
    "summary": "Multiple FTC violations...",
    "violations": [...3 items...]
  }
}
```
UI: ⚖️ card flips from "thinking" → red REVISE badge with `1/10`.

---

### 🛡️ Brand Guardian

#### Pass 0 — `_brand_fallback`

**Tool 1: `detect_prohibited_phrases(content, "SMS")`**

Loads `list_prohibited_terms("SMS")` from the brand bible §3:
```
[{"rule_id": "BRAND-301", "term": "truly unlimited"},
 {"rule_id": "BRAND-302", "term": "free", "context": "without qualifier"},
 {"rule_id": "BRAND-303", "term": "guaranteed"},
 {"rule_id": "BRAND-304", "term": "best ever"},
 ...]
```
Scans content. Hits:
- "FREE" → BRAND-302 (free without qualifier)
- "absolutely free forever" → BRAND-302 (compounded)
- "absolutely" → BRAND-310 (absolute language)

**Tool 2: `detect_urgency_language(content)`** → matches "Limited time
only", "today" → `BRAND-102`.

**Tool 3: `detect_all_caps(content)`** → "FREE" qualifies (all-caps word
≥3 chars in marketing copy) → `BRAND-103`.

**Tool 4: `detect_superlatives(content)`** → no match.

**Tool 5: `validate_cta(content, "SMS", "new_customers")`** → No
recognized CTA from approved registry ("Switch today" is not in
SMS-approved CTA list `[Switch & Save, Get $0, Shop now, ...]`).
Returns `{verified: false, rule_ids_implicated: ["BRAND-603"]}`.
**Note:** "Switch today" is borderline — depending on registry version
this might pass.

**Tool 6: `validate_utm("novatel.com")`** → SMS short-link safe harbor
requires `novatel.com/t` exactly. The bare `novatel.com` is NOT exempt.
→ `BRAND-604` HARD.

**Tool 7: `check_price_accuracy(...)`** (re-run; result cached internally
but audit captures it) → `verified=False` → records BRAND-302 / BRAND-801
as **implicated but not verified**. Used by the verified-rule filter only
when `verified=True`.

**Tool 8: `check_unlimited_qualifier`** — no "unlimited" found → no flag.

**Pass 0 violations:**
- `BRAND-302` HARD ("free" without qualifier)
- `BRAND-102` HARD (urgency)
- `BRAND-103` SOFT (all-caps)
- `BRAND-603` HARD (non-approved CTA)
- `BRAND-604` HARD (UTM missing)

#### Pass 1 — LLM call

System prompt = `BRAND_PROMPT` (Chief Brand Officer persona, lane =
BRAND-1xx/2xx/3xx/6xx). Tools bound = `COMPLIANCE_LOOKUP_TOOLS +
CONTENT_ANALYSIS_TOOLS + validate_cta + validate_utm`.

LLM calls:
- `search_brand_rules({"query": "free", "section": "§3"})` → returns
  BRAND-302, BRAND-301, BRAND-308 entries.
- `get_rule({"rule_id": "BRAND-302"})` → full rule.
- `detect_prohibited_phrases({"text": "...", "channel": "SMS"})` → same as
  Pass 0.
- `detect_urgency_language({"text": "..."})` → same.
- `detect_all_caps({"text": "..."})` → same.

LLM returns:
```json
{
  "verdict": "REVISE",
  "violations": [
    {"rule_id": "BRAND-302", "severity": "HARD", ...},
    {"rule_id": "BRAND-102", "severity": "HARD", "description": "Urgency
     language 'Limited time only' / 'today'", ...},
    {"rule_id": "BRAND-103", "severity": "SOFT", ...},
    {"rule_id": "BRAND-603", "severity": "HARD", "description":
     "'switch today' is not in the approved SMS CTA registry", ...},
    {"rule_id": "BRAND-604", "severity": "HARD", ...},
    {"rule_id": "FTC-005", "severity": "HARD", ...}     // ← out of lane
  ]
}
```

#### Pass 1 (filter)
- `FTC-005` ❌ dropped (out of lane).

#### Pass 2 (grounding) — all remaining rule_ids appeared via either tool
calls or deterministic fallback → kept.

#### Pass 2.5 — none verified=True.

#### Pass 3 — first round, no ratchet.

#### Final merge → 5 violations, 4 HARD + 1 SOFT.
Verdict: **REVISE**. Score: `7 - 2*4 - 1 = -2` → clamped to `1`.

UI: 🛡️ card → red REVISE, `1/10`, lists the 5 violations.

---

### 👥 Persona Simulator

Lane: BRAND-5xx (audience tone). Tools: brand search §5,
`check_audience_fit`, `get_channel_spec`, `lookup_offer`.

#### Pass 0 — `_persona_fallback`

**Tool 1: `check_audience_fit("SMS", "new_customers")`**
Looks up the channel × audience matrix. New customers + SMS = legitimate
acquisition channel → `verified=True`. No BRAND-501.

**Tool 2: jargon-map check**
Audience "new_customers" + content has no "deprioritization", "throttling",
"BYOD" → no BRAND-502.

**Pass 0 violations:** none.

#### Pass 1 — LLM
The persona LLM adopts a first-person stance:
> "As a new customer scanning my phone, the all-caps FREE grabs me but the
> three exclamation marks and 'absolutely free forever' read as scammy.
> I'd hesitate."

Returns:
```json
{ "verdict": "REVISE",
  "violations": [
    {"rule_id": "BRAND-502", "severity": "SOFT",
     "description": "Tone reads as low-trust spam to first-time visitors",
     "suggestion": "Use straightforward language; drop the exclamations"}
  ]
}
```

#### Filters: in-lane (BRAND-5xx), grounded via brand search → kept.

Final: 1 SOFT violation. Verdict: **APPROVE** (no HARD).
Score: `10 - min(2, 1) = 9`.

UI: 👥 card → green APPROVE, `9/10`, with one stylistic SOFT note.

---

### 🔬 Technical Lead

Lane: BRAND-7xx, 8xx (claim accuracy + disclosures). Tools:
offer-verification suite + `extract_claims`.

#### Pass 0 — `_tech_fallback`

**Tool 1: `extract_claims(content)`** → 3 claims (from intake).

For each claim, **`verify_claim(claim, "OFF-001")`**:
- "$0 / FREE" → registry says: $0/mo bill credit *only* with AutoPay +
  trade-in. Without disclosure → contradiction. → `BRAND-701` HARD,
  `BRAND-801` HARD.
- "absolutely free forever" → registry says credits stop on
  cancellation. → `BRAND-701` HARD ("forever" is unsubstantiable).
- "Limited time" → no time-bound offer in registry → `BRAND-704` SOFT
  ("urgency without deadline date").

#### Pass 1 — LLM (using same tools, more nuance):

Returns:
```json
{ "verdict": "REVISE",
  "violations": [
    {"rule_id": "BRAND-701", "severity": "HARD",
     "description": "'free forever' contradicts registry: credits stop
       if customer cancels"},
    {"rule_id": "BRAND-801", "severity": "HARD",
     "description": "Mandatory disclosure text missing"},
    {"rule_id": "BRAND-704", "severity": "SOFT", ...}
  ]
}
```

Filters: in-lane (700–899), grounded via `verify_claim.rule_ids_implicated`
including BRAND-701 → kept.

Final: 2 HARD + 1 SOFT. **REVISE**. Score: `7 - 4 - 1 = 2`.

UI: 🔬 card → red REVISE, `2/10`.

---

### 📋 Ops Strategist

Lane: BRAND-4xx (channel format), 6xx (CTA/UTM). Tools:
`channel_validation` suite.

#### Pass 0 — `_ops_fallback`

**Tool 1: `validate_length(content, "SMS", "new_customers")`**
Content is 122 chars. SMS limit = 160. → `verified=True`,
`rule_ids_implicated=["BRAND-401"]`. No length violation.
**(But this `verified=True` will be used by Pass 2.5 to suppress LLM
re-flagging of BRAND-401.)**

**Tool 2: `validate_mandatory_elements(content, "SMS", "OFF-001")`**
Same as FCC's call → missing Msg&Data, STOP, T&C link. The Ops lane keeps
these as `BRAND-401` (channel-format SMS rule); FCC keeps them as
`FTC-014`. → `BRAND-401` HARD.

**Tool 3: `validate_utm("novatel.com")`** → bare URL, not the SMS
short-link → `BRAND-604` HARD.

**Tool 4: `validate_cta(content, "SMS", "new_customers")`** → "switch
today" not in approved CTA registry → `BRAND-603` HARD.

#### Pass 1 — LLM
Returns 3 violations matching the fallback + tries `BRAND-401` for length:
`{"rule_id": "BRAND-401", "severity": "HARD", "description": "exceeds 160
chars"}` ← **wrong**. Counted at 122 chars.

#### Pass 2.5 — verified-rule filter
`validate_length` returned `verified=True` with `rule_ids_implicated=
["BRAND-401"]` for the **length** dimension. But `validate_mandatory_elements`
returned `verified=False` with `rule_ids_implicated=["FTC-014", "BRAND-401",
...]` for the **mandatory elements** dimension.

Both report `BRAND-401`. The verified-rule filter currently de-dupes by
rule_id; **this is a known limitation** (see [Architect Deep-Dive §17](Guardian-AI-Architect-Deep-Dive.md#17-design-trade-offs-and-answers-to-expected-architect-questions)).
The deterministic fallback still flags BRAND-401 for missing elements, so
the violation survives via merge. The LLM's spurious "exceeds 160 chars"
flag IS dropped (because length is verified).

#### Final
- `BRAND-401` HARD (mandatory elements)
- `BRAND-603` HARD (CTA)
- `BRAND-604` HARD (UTM)

Verdict: **REVISE**. Score: `7 - 6 = 1`.

---

### Round-1 verdict summary

| Critic | Verdict | Score | HARD | SOFT |
|---|---|---|---|---|
| ⚖️  FCC Enforcer | REVISE | 1 | 3 | 0 |
| 🛡️  Brand Guardian | REVISE | 1 | 4 | 1 |
| 👥 Persona Simulator | APPROVE | 9 | 0 | 1 |
| 🔬 Technical Lead | REVISE | 2 | 2 | 1 |
| 📋 Ops Strategist | REVISE | 1 | 3 | 0 |

Composite = (1+1+9+2+1)/5 = **2.8/10**.

---

## STAGE 3 — Resolver (`agents/resolver.py`)

The aggregate node calls `run_resolver(content, intake, verdicts, audit, iteration=1, prior_state=None)`.

### Step 1 — Deterministic fixes (`_deterministic_fixes`) — always runs

Five passes on the original content:

**(a) `replace_prohibited_terms(content)`** — substitution table:
```
"truly unlimited" → "unlimited"
"absolutely" → ""           # softener stripped
"forever" → ""              # unsupportable
"FREE" → "$0/mo"            # disclosure-bearing replacement
```
Output: `"$0/mo iPhone 17 Pro!!! No catch, just switch today and get it
free. Limited time only! novatel.com"`

**(b) `add_utm_to_text(text, "SMS", campaign=None)`** —
SMS gets the short-link rule applied: bare `novatel.com` → `novatel.com/t`.
Output: `"...switch today and get it free. Limited time only! novatel.com/t"`

**(c) `apply_disclosure(text, "OFF-001", "SMS")`** —
Looks up the registry's `mandatory_disclosure_text`, and because this is
SMS it picks the **abbreviated SMS variant**:
> `"$0/mo on Unlimited Premium ($85.99/mo) w/ AutoPay+36mo bill credits+elig. trade-in. Credits stop if you cancel. See novatel.com/t"`

Output (concatenated, before truncate):
> `"$0/mo iPhone 17 Pro!!! Switch today. $0/mo on Unlimited Premium ($85.99/mo) w/ AutoPay+36mo bill credits+elig. trade-in. Credits stop if you cancel. Limited time. novatel.com/t"`

**(d) `truncate_to_channel(text, "SMS")`** — preserves the mandatory tail.
Trims marketing copy from the front to fit ≤160 chars.

**(e) `add_mandatory_elements(text, "SMS")`** — appends "Msg&Data rates may
apply. Reply STOP" if not present.

Final DRAFT (~155 chars):
> `"$0/mo iPhone 17 Pro w/ Unlimited Premium ($85.99/mo) + AutoPay + 36mo credits + elig. trade-in. Credits stop on cancel. Msg&Data rates may apply. Reply STOP. novatel.com/t"`

**Audit trail entry:**
```json
{ "agent": "resolver", "tool": "deterministic_fixes",
  "input": {"channel": "SMS", "offer_id": "OFF-001"},
  "output": {"changes": [
    "replaced 'FREE' → '$0/mo'",
    "stripped 'absolutely', 'forever'",
    "applied OFF-001 mandatory disclosure (SMS variant)",
    "added Msg&Data + STOP",
    "rewrote URL → novatel.com/t"
  ]} }
```

### Step 2 — Compliance brief

`_compliance_brief(intake, verdicts, prior_state=None)` builds an imperative
prompt block:

```
OFFER REGISTRY (use these exact values):
  plan: Unlimited Premium ($85.99/mo)
  AutoPay: required
  trade-in: required (Apple/Samsung/Google, good condition)
  credit period: 36 months
  monthly credit: $30.55
  total credit: $1099.99
  SMS short-link safe-harbor: novatel.com/t

CRITIC HARD VIOLATIONS TO FIX:
  fcc_enforcer:
    - FTC-005: $0/free claim missing required disclosures
    - FTC-013: trade-in eligibility unstated
    - FTC-014: SMS missing Msg&Data, STOP, T&C link
  brand_guardian:
    - BRAND-302: 'free' without qualifier
    - BRAND-102: urgency language ("Limited time only", "today")
    - BRAND-603: non-approved CTA ("switch today")
    - BRAND-604: missing UTM (use SMS short-link)
  technical_lead:
    - BRAND-701: 'free forever' contradicts registry
    - BRAND-801: mandatory disclosure missing
  ops_strategist:
    - BRAND-401: missing mandatory SMS elements
    - BRAND-603, BRAND-604 (dup)

CRITICS WHO ALREADY APPROVED: [persona_simulator]  (DO-NOT-REGRESS)
```

### Step 3 — LLM rewrite

Builds the user message with: original, intake, compliance brief,
critic-verdict JSON, seed metrics (composite=2.8, all_approved=False),
2 few-shot good samples for SMS/new_customers, and the DRAFT.

System prompt = `RESOLVER_PROMPT` (senior copy editor with surgical-edit mandate).

LLM responds with strict JSON:
```json
{
  "revised_content": "$0/mo iPhone 17 Pro w/ Unlimited Premium ($85.99/mo), AutoPay + 36-mo credits, elig. trade-in (Apple/Samsung/Google, good cond.). Credits stop if you cancel. Msg&Data rates apply. Reply STOP. Terms: novatel.com/t",
  "changelog": [
    {"change": "Replaced 'FREE iPhone 17 Pro' with disclosure-bearing $0/mo claim",
     "rule_ids": ["FTC-005", "BRAND-302", "BRAND-801"]},
    {"change": "Added eligible trade-in brands and condition",
     "rule_ids": ["FTC-013"]},
    {"change": "Removed urgency language ('Limited time only', '!!!')",
     "rule_ids": ["BRAND-102"]},
    {"change": "Added Msg&Data, STOP, T&C link (SMS short-link)",
     "rule_ids": ["FTC-014", "BRAND-401", "BRAND-604"]},
    {"change": "Removed 'switch today' CTA in favor of structured disclosure",
     "rule_ids": ["BRAND-603"]},
    {"change": "Removed 'forever' (unsupportable, contradicts registry)",
     "rule_ids": ["BRAND-701"]}
  ],
  "composite_score": 8.5,
  "all_approved": true,
  "violations_resolved": ["FTC-005","FTC-013","FTC-014","BRAND-102","BRAND-302","BRAND-401","BRAND-603","BRAND-604","BRAND-701","BRAND-801"],
  "violations_unresolved": []
}
```

### Step 4 — Insurance pass

Re-runs UTM → truncate → mandatory elements → truncate. The LLM output
already had everything; insurance pass is a no-op here.

### Step 5 — `IterationRecord` emitted

```json
{ "type": "iteration",
  "iteration": {
    "iteration": 1,
    "verdicts": [...all 5 critic verdicts...],
    "revised_content": "$0/mo iPhone 17 Pro w/ Unlimited Premium...",
    "changelog": "### Round 1 changes\n- Replaced 'FREE...' (FTC-005, BRAND-302, BRAND-801)\n...",
    "composite_score": 8.5,
    "converged": false   // resolver claims approved but iter < cap; gate decides
  }
}
```

UI: ScoreProgressionChart shows the first datapoint at 8.5 (resolver's
self-assessment). Resolver panel populates with diff + changelog markdown.

---

## STAGE 4 — Gate

`gate` node checks two conditions:

```python
def gate(state):
    last = state.iterations[-1]
    all_approved = all(v.verdict == "APPROVE" for v in last.verdicts)
    if all_approved:
        return END
    if state.iteration >= settings.max_iterations:
        return END
    return "fan_out_critics"   # loop with state.current_content = revised
```

Round 1: `all_approved=False` (4 of 5 critics REVISE'd the *original*).
With `GUARDIAN_MAX_ITERATIONS=1` (default) → goes to END.
With `GUARDIAN_MAX_ITERATIONS=3` → loops to Round 2 with the rewritten
content. The **approval ratchet** kicks in there: `prior_state["persona_simulator"].ever_approved = True`, so any new HARD violation Persona makes in Round 2 demotes to SOFT unless its deterministic fallback also flags it.

---

## STAGE 5 — `done` event + User Gate

WebSocket emits:
```json
{ "type": "done",
  "response": {
    "final_content": "$0/mo iPhone 17 Pro w/ Unlimited Premium ($85.99/mo)...",
    "iterations": [...],
    "audit_trail": [...all ToolCallTrace entries from all critics + resolver...],
    "converged": false,
    "elapsed_ms": 6342
  }
}
```

UI: User Gate appears with three options:
1. **Accept** any version (Original | Round 1 rewrite) → routes to `/report`.
2. **Edit & re-review** → opens inline editor; submit triggers `rerun(text)`.
3. **Run another round** on the chosen version.

---

## What the audit trail looks like (excerpt)

```json
[
  {"agent":"intake","tool":"find_offer_by_content","iteration":1,
   "input":{"text":"FREE iPhone 17 Pro!!!..."},
   "output":[{"offer_id":"OFF-001","confidence":0.92,...}]},

  {"agent":"fcc_enforcer","tool":"check_price_accuracy","iteration":1,
   "input":{"offer_id":"OFF-001"},
   "output":{"verified":false,"missing_conditions":[...],
             "rule_ids_implicated":["FTC-005","BRAND-302","BRAND-801"]}},

  {"agent":"fcc_enforcer","tool":"validate_mandatory_elements","iteration":1,
   "input":{"channel":"SMS"},
   "output":{"verified":false,"missing":["Msg&Data rates","STOP opt-out","T&C link"]}},

  {"agent":"fcc_enforcer","tool":"llm_call","iteration":1,
   "input":{"model":"gpt-5.4-beta","prompt_tokens":2841},
   "output":{"completion_tokens":487,"verdict":"REVISE","violations_returned":4}},

  ... (similar entries for brand_guardian, persona_simulator, technical_lead, ops_strategist) ...

  {"agent":"resolver","tool":"deterministic_fixes","iteration":1,
   "input":{"channel":"SMS","offer_id":"OFF-001"},
   "output":{"changes":[5 entries...]}},

  {"agent":"resolver","tool":"llm_rewrite","iteration":1,
   "input":{"violations":12},
   "output":{"chars":228,"edits":6,"composite_score":8.5,"all_approved":true,
             "violations_resolved":[10 rule_ids],"violations_unresolved":[]}}
]
```

This is what's exportable as JSON from the report page.

---

## How skills, tools, and the LLM combine — the meta-pattern

| Layer | Role | When it runs | Trust level |
|---|---|---|---|
| **Skills (Python)** | Pure functions over JSON/CSV ground truth | Always (Pass 0) | Highest — structurally provable |
| **Tools (LangChain `@tool` wrappers)** | The same skills, but exposed to the LLM via function-calling | When the LLM chooses to call them | High — the LLM cannot fabricate tool outputs |
| **LLM verdicts** | Judgment + nuance + style critique | Pass 1, only if a key is configured | Filtered — must cite a rule_id grounded in tools or in the deterministic fallback |
| **Approval ratchet** | Anti-oscillation governor | Pass 3 | Prevents stylistic regressions from re-blocking |
| **Resolver** | Synthesis + deterministic safety net + LLM rewrite | Once per round | Deterministic floor + LLM polish |

**Key insight:** the LLM is never the source of truth. It is a *judgment
amplifier* that operates on top of structurally proven facts. Every
flagged violation traces to (a) a deterministic skill output OR (b) an
LLM cite of a rule_id that the LLM itself just looked up via a tool. This
is how Guardian AI achieves the precision needed for legal-grade marketing
review — without surrendering to hallucination.

---

*End of worked example.*
