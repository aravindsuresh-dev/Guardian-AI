import type { CriticName, CriticVerdict } from "../types";
import { CRITIC_META } from "../types";

export function CriticCard({
  verdict,
  running,
  name: nameProp,
}: {
  verdict?: CriticVerdict;
  running?: boolean;
  name?: CriticName;
}) {
  const name = verdict?.agent ?? nameProp;
  const meta = name ? CRITIC_META[name] : undefined;
  return (
    <div className="critic-card">
      <div className="head">
        <span style={{ fontSize: 18 }}>{meta?.emoji ?? "⚪"}</span>
        <span className="label" style={{ color: meta?.color ?? "#93a3d8" }}>
          {meta?.label ?? "Critic"}
        </span>
        {running ? (
          <span className="dot running" />
        ) : verdict ? (
          <span className={`badge ${verdict.verdict.toLowerCase()}`}>{verdict.verdict}</span>
        ) : (
          <span className="badge">queued</span>
        )}
      </div>
      {verdict && (
        <div className="body">
          <div className="summary">{verdict.summary}</div>
          {verdict.violations.length === 0 && (
            <div style={{ color: "#6ee7a4", fontSize: 12 }}>No violations.</div>
          )}
          {verdict.violations.map((v, i) => (
            <div key={i} className={`violation ${v.severity}`}>
              <div>
                <span className="rid">{v.rule_id}</span>{" "}
                <span className="badge">{v.severity}</span>
              </div>
              <div className="desc">{v.description}</div>
              {v.span && <div className="span">↳ {v.span}</div>}
              {v.suggestion && <div className="sugg">→ {v.suggestion}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
