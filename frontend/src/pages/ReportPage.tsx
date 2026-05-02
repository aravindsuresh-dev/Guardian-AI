import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DiffView } from "../components/DiffView";
import { ScoreProgressionChart } from "../components/ScoreProgressionChart";
import { TopBar } from "../components/TopBar";
import { CRITIC_META } from "../types";
import type { CriticName, Violation } from "../types";
import { useReview } from "../state/ReviewContext";
import { compositeScore, fmtElapsed, iterationScore, scoreColor } from "../util/score";

export default function ReportPage() {
  const nav = useNavigate();
  const { request, final, iterations, startedAt, selectedFinal, originalContent } = useReview();

  // If user lands here directly, bounce home.
  if (!request || (!final && iterations.length === 0)) {
    return (
      <div className="page">
        <TopBar />
        <main className="report-empty">
          <p>No completed review found.</p>
          <Link to="/" className="cta inline">Start a new review</Link>
        </main>
      </div>
    );
  }

  const finalContent =
    selectedFinal
    || final?.final_content
    || iterations[iterations.length - 1]?.revised_content
    || request.content;
  const beforeContent = originalContent ?? request.content;
  const converged = !!final?.converged;
  const lastIter = iterations[iterations.length - 1];
  const lastScore = lastIter ? iterationScore(lastIter) : compositeScore([]);
  const elapsed = startedAt ? Date.now() - startedAt : 0;

  const allViolations = useMemo(() => {
    const out: Array<Violation & { agent: CriticName; iteration: number }> = [];
    iterations.forEach((it) => it.verdicts.forEach((v) => v.violations.forEach((vi) => {
      out.push({ ...vi, agent: v.agent, iteration: it.iteration });
    })));
    return out;
  }, [iterations]);

  const hardByRule = group(allViolations.filter((v) => v.severity === "HARD"));
  const softByRule = group(allViolations.filter((v) => v.severity === "SOFT"));

  const trail = final?.audit_trail || [];
  const toolCounts = trail.reduce<Record<string, number>>((acc, t) => {
    acc[t.tool] = (acc[t.tool] || 0) + 1;
    return acc;
  }, {});
  const topTools = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);

  const banner = converged ? "approved" : "partial";

  function copyFinal() {
    navigator.clipboard.writeText(finalContent);
  }
  function exportJSON() {
    const blob = new Blob([JSON.stringify({ request, final, iterations }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "guardian-ai-audit.json"; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="page report-page">
      <TopBar />
      <main className="report-main">
        <section className={`result-banner ${banner}`}>
          <div className="banner-left">
            <div className="banner-status">
              {converged ? "✅ All critics approved" : "⚠️ Accepted with outstanding critic notes"}
            </div>
            <div className="banner-meta">
              {request.channel} · {request.audience} {request.offer_id ? `· ${request.offer_id}` : ""}
            </div>
          </div>
          <div className="banner-right">
            <div className="banner-score" style={{ color: scoreColor(lastScore) }}>{lastScore.toFixed(1)}<span className="muted">/10</span></div>
            <div className="banner-meta">{iterations.length} round{iterations.length === 1 ? "" : "s"} · {fmtElapsed(elapsed)}</div>
          </div>
        </section>

        <section className="report-2col">
          <div className="card">
            <ScoreProgressionChart iterations={iterations} height={140} />
          </div>
          <div className="card">
            <h3>Verdicts per round</h3>
            <table className="verdict-table">
              <thead>
                <tr>
                  <th>Round</th>
                  {(Object.keys(CRITIC_META) as CriticName[]).map((n) => (
                    <th key={n}><span style={{ color: CRITIC_META[n].color }}>{CRITIC_META[n].emoji}</span> {CRITIC_META[n].label.split(" ")[0]}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {iterations.map((it) => (
                  <tr key={it.iteration}>
                    <td>R{it.iteration}</td>
                    {(Object.keys(CRITIC_META) as CriticName[]).map((n) => {
                      const v = it.verdicts.find((x) => x.agent === n);
                      return <td key={n}>{v ? <span className={`badge ${v.verdict.toLowerCase()}`}>{v.verdict}</span> : "—"}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card">
          <h3>Before / After</h3>
          <DiffView before={beforeContent} after={finalContent} />
        </section>

        <section className="card">
          <h3>Violations</h3>
          <ViolationGroup title="HARD" entries={hardByRule} />
          <ViolationGroup title="SOFT" entries={softByRule} />
        </section>

        <section className="card">
          <h3>Tool Call Summary</h3>
          <div className="tool-stats">
            <div><span className="muted">Total calls</span><b>{trail.length}</b></div>
            <div><span className="muted">Distinct tools</span><b>{Object.keys(toolCounts).length}</b></div>
          </div>
          <div className="tool-top">
            <div className="muted">Most-used tools</div>
            <ol>
              {topTools.map(([t, c]) => <li key={t}><code>{t}</code> · {c}</li>)}
            </ol>
          </div>
          <details>
            <summary>Full audit trail ({trail.length})</summary>
            <pre style={{ maxHeight: 320, overflow: "auto" }}>{JSON.stringify(trail, null, 2)}</pre>
          </details>
        </section>

        <section className="report-actions">
          <button onClick={copyFinal}>📋 Copy Final Content</button>
          <button onClick={exportJSON} className="secondary">📥 Export Audit Trail (JSON)</button>
          <button onClick={() => nav("/review")} className="secondary">↩️ Back to Review (edit & re-run)</button>
          <button onClick={() => nav("/")} className="secondary">🔄 Review Another</button>
        </section>
      </main>
    </div>
  );
}

function group(rows: Array<Violation & { agent: CriticName; iteration: number }>) {
  const out: Record<string, Array<Violation & { agent: CriticName; iteration: number }>> = {};
  rows.forEach((r) => {
    (out[r.rule_id] = out[r.rule_id] || []).push(r);
  });
  return out;
}

function ViolationGroup({ title, entries }: {
  title: string;
  entries: Record<string, Array<Violation & { agent: CriticName; iteration: number }>>;
}) {
  const keys = Object.keys(entries);
  if (!keys.length) return <div className="muted" style={{ marginBottom: 12 }}>No {title} violations.</div>;
  return (
    <div className="vg">
      <div className="vg-h">{title} <span className="muted">({keys.length} rule{keys.length === 1 ? "" : "s"})</span></div>
      {keys.map((k) => (
        <details key={k} className="vg-item">
          <summary>
            <span className="rid">{k}</span>
            <span className="muted">{entries[k].length} occurrence{entries[k].length === 1 ? "" : "s"}</span>
          </summary>
          <ul>
            {entries[k].map((e, i) => (
              <li key={i}>
                <span className="muted">R{e.iteration} · {CRITIC_META[e.agent].label}</span> — {e.description}
                {e.suggestion && <div className="sugg">→ {e.suggestion}</div>}
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}
