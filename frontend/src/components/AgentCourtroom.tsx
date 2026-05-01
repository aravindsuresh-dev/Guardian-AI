import type { CriticName, CriticVerdict, IterationRecord } from "../types";
import { AgentCard } from "./AgentCard";

const ORDER: CriticName[] = [
  "fcc_enforcer",
  "brand_guardian",
  "persona_simulator",
  "technical_lead",
  "ops_strategist",
];

export function AgentCourtroom({
  liveCritics,
  iterations,
  running,
}: {
  liveCritics: CriticVerdict[];
  iterations: IterationRecord[];
  running: boolean;
}) {
  // Show the LIVE round if streaming, otherwise the most-recent finished iteration's verdicts.
  const showLive = running || liveCritics.length > 0;
  const verdicts = showLive
    ? liveCritics
    : iterations.length
      ? iterations[iterations.length - 1].verdicts
      : [];

  // A round is "in progress" whenever the parent says we're running OR we've
  // begun streaming live critics OR no iteration has finished yet. In any of
  // those cases, agents without a verdict yet should show the thinking
  // animation rather than the dormant "Idle" state.
  const inProgress = running || liveCritics.length > 0 || iterations.length === 0;

  const round = iterations.length + (showLive ? 1 : 0);

  return (
    <div className="courtroom">
      <div className="courtroom-head">
        <h3>Agent Courtroom</h3>
        <span className="muted">Round {Math.max(1, round)} · 5 critics in parallel</span>
      </div>

      <div className="agent-stack">
        {ORDER.map((name, i) => {
          const v = verdicts.find((x) => x.agent === name);
          return (
            <div key={name} style={{ animationDelay: `${i * 120}ms` }} className="agent-slide-in">
              <AgentCard name={name} verdict={v} thinking={inProgress && !v} />
            </div>
          );
        })}
      </div>

      {iterations.length > 1 && (
        <details className="prior-rounds">
          <summary>Prior rounds ({iterations.length - 1})</summary>
          {iterations.slice(0, -1).map((it) => (
            <div key={it.iteration} className="prior-round">
              <h4>Round {it.iteration}</h4>
              {it.verdicts.map((v) => (
                <AgentCard key={v.agent} name={v.agent} verdict={v} />
              ))}
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
