import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useReview } from "../state/ReviewContext";
import { compositeScore, fmtElapsed, iterationScore, scoreColor } from "../util/score";

export function TopBar({ showRound = false }: { showRound?: boolean }) {
  const { status, iterations, liveCritics, cancel } = useReview();
  const [now, setNow] = useState(() => Date.now());
  const [start] = useState(() => Date.now());
  const [frozen, setFrozen] = useState<number | null>(null);

  const active = showRound && status !== "done" && status !== "error";

  useEffect(() => {
    if (!showRound) return;
    if (!active) {
      setFrozen((f) => (f === null ? Date.now() - start : f));
      return;
    }
    setFrozen(null);
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [active, showRound, start]);

  const elapsed = frozen !== null ? frozen : now - start;

  const round = showRound ? Math.max(1, iterations.length + (active ? 1 : 0)) : 0;
  const liveScore = compositeScore(liveCritics);
  const lastScore = iterations.length ? iterationScore(iterations[iterations.length - 1]) : 0;
  const score = liveCritics.length ? liveScore : lastScore;

  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <span className="brand-logo">🛡️</span>
        <div>
          <div className="brand-name">Guardian AI</div>
          <div className="brand-sub">Telecom Marketing Compliance</div>
        </div>
      </Link>

      {showRound && (
        <div className="topbar-center">
          <span className="round-pill">
            <span className={`dot ${active ? "running" : "done"}`} />
            Round {round}
          </span>
          {score > 0 && (
            <span className="score-pill" style={{ borderColor: scoreColor(score), color: scoreColor(score) }}>
              {score.toFixed(1)} / 10
            </span>
          )}
          {showRound && <span className="timer">{fmtElapsed(elapsed)}</span>}
        </div>
      )}

      <div className="topbar-right">
        {showRound && active && (
          <button className="icon-btn" title="Cancel review" onClick={() => {
            if (confirm("Cancel the review in progress?")) cancel();
          }}>✕</button>
        )}
      </div>
    </header>
  );
}
