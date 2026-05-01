import type { IterationRecord } from "../types";
import { CriticCard } from "./CriticCard";

export function IterationView({ rec }: { rec: IterationRecord }) {
  return (
    <div className="iteration">
      <h3>Iteration {rec.iteration}</h3>
      <details open>
        <summary>Content reviewed ({rec.content.length} chars)</summary>
        <pre className="diff-pre">{rec.content}</pre>
      </details>
      {rec.verdicts.map((v) => (
        <CriticCard key={v.agent} verdict={v} />
      ))}
      {rec.revised_content && (
        <>
          <h3 style={{ marginTop: 16 }}>Resolver — proposed revision</h3>
          <pre className="diff-pre">{rec.revised_content}</pre>
          {rec.changelog && (
            <details>
              <summary>Changelog</summary>
              <pre>{rec.changelog}</pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
