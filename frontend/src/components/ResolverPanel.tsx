import type { IterationRecord } from "../types";
import { DiffView } from "./DiffView";

export function ResolverPanel({
  iterations,
  running,
  originalContent,
}: {
  iterations: IterationRecord[];
  running: boolean;
  originalContent: string;
}) {
  const latest = iterations.length ? iterations[iterations.length - 1] : null;

  return (
    <aside className="resolver-panel">
      <h3>Resolver</h3>

      {!latest && running && (
        <div className="resolver-waiting">
          <span className="dot running" />
          Waiting for critics to finish...
        </div>
      )}

      {!latest && !running && (
        <div className="resolver-waiting muted">Resolver output will appear here.</div>
      )}

      {latest && (() => {
        const allApproved =
          latest.verdicts.length > 0 &&
          latest.verdicts.every((v) => v.verdict === "APPROVE");
        return (
        <>
          <div className="resolver-section">
            <div className="resolver-label">Iteration {latest.iteration}</div>
            {allApproved ? (
              <div className="muted">All critics approved — no rewrite needed.</div>
            ) : latest.revised_content ? (
              <DiffView before={originalContent} after={latest.revised_content} />
            ) : (
              <div className="muted warn">
                Resolver did not return a rewrite. Use <em>Edit &amp; Re-review</em>
                to supply a corrected version.
              </div>
            )}
          </div>

          {latest.changelog && (
            <div className="resolver-section">
              <div className="resolver-label">Changelog</div>
              <div className="changelog-md">{latest.changelog}</div>
            </div>
          )}
        </>
        );
      })()}
    </aside>
  );
}
