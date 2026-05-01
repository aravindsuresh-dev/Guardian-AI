import type { CriticName, CriticVerdict } from "../types";
import { CRITIC_META } from "../types";
import { agentScore, scoreColor } from "../util/score";

const ROLE_BLURB: Record<CriticName, string> = {
  fcc_enforcer:      "Federal/FCC truth-in-advertising lane",
  brand_guardian:    "Voice, tone, claim hierarchy",
  persona_simulator: "Audience comprehension & resonance",
  technical_lead:    "Spec accuracy vs offer registry",
  ops_strategist:    "Channel limits, CTAs, attribution",
};

export function AgentCard({
  name,
  verdict,
  thinking,
}: {
  name: CriticName;
  verdict?: CriticVerdict;
  thinking?: boolean;
}) {
  const meta = CRITIC_META[name];
  const score = verdict ? agentScore(verdict) : 0;
  const state = verdict ? "complete" : thinking ? "thinking" : "idle";

  return (
    <div className={`agent-card ${state}`}>
      <div className="agent-head">
        <span className="agent-emoji" style={{ color: meta.color }}>{meta.emoji}</span>
        <div className="agent-id">
          <div className="agent-name">{meta.label}</div>
          <div className="agent-role">{ROLE_BLURB[name]}</div>
        </div>
        {verdict ? (
          <div className="agent-status">
            <span className={`badge ${verdict.verdict.toLowerCase()}`}>{verdict.verdict}</span>
            <span className="agent-score" style={{ color: scoreColor(score) }}>{score.toFixed(1)}</span>
          </div>
        ) : thinking ? (
          <div className="agent-status">
            <span className="thinking-pip" /><span className="thinking-pip" /><span className="thinking-pip" />
          </div>
        ) : (
          <div className="agent-status muted">Idle</div>
        )}
      </div>

      {verdict && (
        <div className="agent-body">
          <div className="agent-summary">{verdict.summary}</div>
          {verdict.violations.length > 0 && (
            <div className="violations">
              {verdict.violations.map((vi, i) => (
                <div key={i} className={`violation ${vi.severity}`}>
                  <span className="rid">{vi.rule_id}</span>
                  <span className="sev">{vi.severity}</span>
                  <div className="desc">{vi.description}</div>
                  {vi.span && <div className="span">“{vi.span}”</div>}
                  {vi.suggestion && <div className="sugg">→ {vi.suggestion}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
