import type { CriticVerdict, IterationRecord } from "../types";

// Synthesize a 1-10 score per critic.
//
// The critic's APPROVE/REVISE verdict is the source of truth; we anchor the
// numeric score to it so the two never disagree:
//   APPROVE  → 8..10 (floor 8, perfect=10)
//   REVISE   → 1..7  (severity-weighted)
export function agentScore(v: CriticVerdict): number {
  const hard = v.violations.filter((x) => x.severity === "HARD").length;
  const soft = v.violations.filter((x) => x.severity === "SOFT").length;

  if (v.verdict === "APPROVE") {
    // Lightly penalise residual SOFT advisories but never drop below 8.
    const raw = 10 - Math.min(2, soft);
    return Math.max(8, Math.min(10, raw));
  }

  // REVISE: deeper deductions, capped at 7 so it can never look "approved".
  const raw = 7 - hard * 2 - soft;
  return Math.max(1, Math.min(7, raw));
}

export function compositeScore(verdicts: CriticVerdict[]): number {
  if (!verdicts.length) return 0;
  const sum = verdicts.reduce((a, v) => a + agentScore(v), 0);
  return Math.round((sum / verdicts.length) * 10) / 10;
}

export function iterationScore(it: IterationRecord): number {
  return compositeScore(it.verdicts);
}

export function scoreColor(score: number): string {
  if (score >= 8) return "#16a34a";
  if (score >= 6) return "#ca8a04";
  return "#dc2626";
}

export function fmtElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}
