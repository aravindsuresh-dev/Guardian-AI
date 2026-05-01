import type { IterationRecord } from "../types";
import { iterationScore, scoreColor } from "../util/score";

export function ScoreProgressionChart({ iterations, height = 100 }: { iterations: IterationRecord[]; height?: number }) {
  const W = 600, H = height, PAD_L = 32, PAD_R = 12, PAD_T = 12, PAD_B = 22;
  const pts = iterations.map((it) => ({ x: it.iteration, y: iterationScore(it) }));
  const maxX = Math.max(3, ...pts.map((p) => p.x));
  const xOf = (x: number) => PAD_L + ((x - 1) / Math.max(1, maxX - 1)) * (W - PAD_L - PAD_R);
  const yOf = (y: number) => PAD_T + (1 - y / 10) * (H - PAD_T - PAD_B);

  const path = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${xOf(p.x).toFixed(1)} ${yOf(p.y).toFixed(1)}`).join(" ");

  return (
    <div className="score-chart">
      <div className="score-chart-h">Score Progression</div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H}>
        {[0, 5, 10].map((g) => (
          <g key={g}>
            <line x1={PAD_L} x2={W - PAD_R} y1={yOf(g)} y2={yOf(g)} stroke="#2a3358" strokeDasharray="3 3" />
            <text x={4} y={yOf(g) + 4} fontSize="10" fill="#93a3d8">{g}</text>
          </g>
        ))}
        {Array.from({ length: maxX }, (_, i) => i + 1).map((r) => (
          <text key={r} x={xOf(r)} y={H - 6} fontSize="10" fill="#93a3d8" textAnchor="middle">R{r}</text>
        ))}
        {pts.length > 1 && <path d={path} fill="none" stroke="#6366f1" strokeWidth="2" className="chart-line" />}
        {pts.map((p, i) => (
          <circle key={i} cx={xOf(p.x)} cy={yOf(p.y)} r="4" fill={scoreColor(p.y)} stroke="#0b1020" strokeWidth="2" />
        ))}
      </svg>
    </div>
  );
}
