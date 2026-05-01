// Tiny word-level diff (LCS) — good enough for marketing copy.
function tokenize(s: string): string[] {
  return s.split(/(\s+)/).filter((t) => t.length > 0);
}

type Op = { type: "eq" | "del" | "add"; text: string };

function diff(a: string[], b: string[]): Op[] {
  const n = a.length, m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops: Op[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push({ type: "eq", text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ type: "del", text: a[i] }); i++; }
    else { ops.push({ type: "add", text: b[j] }); j++; }
  }
  while (i < n) ops.push({ type: "del", text: a[i++] });
  while (j < m) ops.push({ type: "add", text: b[j++] });
  return ops;
}

export function DiffView({ before, after }: { before: string; after: string }) {
  const ops = diff(tokenize(before), tokenize(after));
  return (
    <div className="diff-grid">
      <div className="diff-col">
        <div className="diff-h">Before</div>
        <pre className="diff-pre">
          {ops.map((o, i) =>
            o.type === "add" ? null :
            <span key={i} className={o.type === "del" ? "diff-del" : ""}>{o.text}</span>
          )}
        </pre>
      </div>
      <div className="diff-col">
        <div className="diff-h">After</div>
        <pre className="diff-pre">
          {ops.map((o, i) =>
            o.type === "del" ? null :
            <span key={i} className={o.type === "add" ? "diff-add" : ""}>{o.text}</span>
          )}
        </pre>
      </div>
    </div>
  );
}
