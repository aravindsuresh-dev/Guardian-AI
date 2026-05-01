import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AgentCourtroom } from "../components/AgentCourtroom";
import { OriginalContentPanel } from "../components/OriginalContentPanel";
import { ResolverPanel } from "../components/ResolverPanel";
import { ScoreProgressionChart } from "../components/ScoreProgressionChart";
import { TopBar } from "../components/TopBar";
import { UserGate, type VersionOption } from "../components/UserGate";
import { useReview } from "../state/ReviewContext";

export default function ReviewPage() {
  const nav = useNavigate();
  const {
    request, status, intake, iterations, liveCritics, error, start, rerun,
    setSelectedFinal,
  } = useReview();

  // If user lands here without a request (e.g. direct nav), bounce home.
  useEffect(() => {
    if (!request) { nav("/", { replace: true }); return; }
    if (status === "idle") start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!request) return null;
  // Treat anything that isn't a finished/errored state as "running" so the agent
  // cards show thinking pips from the first paint (before start() fires) and
  // through the entire WS lifecycle. UserGate (post-round) is gated separately
  // on iterations + status="done".
  const running = status !== "done" && status !== "error";
  const showGate = status === "done" && iterations.length > 0;

  // Build the version list: original input + each round's rewrite (if any).
  // The user can pick any of these as the basis for accept/edit/rerun.
  const versions = useMemo<VersionOption[]>(() => {
    const list: VersionOption[] = [
      { id: "original", label: "Original", content: request.content },
    ];
    iterations.forEach((it) => {
      const rewrite = it.revised_content?.trim();
      if (rewrite) {
        list.push({
          id: `r${it.iteration}`,
          label: `Round ${it.iteration} rewrite`,
          content: rewrite,
        });
      }
    });
    return list;
  }, [request.content, iterations]);

  const acceptFinal = (content: string) => {
    setSelectedFinal(content);
    nav("/report");
  };

  // Resizable panes ---------------------------------------------------------
  const gridRef = useRef<HTMLElement | null>(null);
  // Persist user preference across reloads.
  const [leftW, setLeftW] = useState<number>(() => {
    const v = Number(localStorage.getItem("guardian.leftW"));
    return Number.isFinite(v) && v > 0 ? v : 280;
  });
  const [rightW, setRightW] = useState<number>(() => {
    const v = Number(localStorage.getItem("guardian.rightW"));
    return Number.isFinite(v) && v > 0 ? v : 400;
  });
  const dragRef = useRef<{ side: "left" | "right"; startX: number; startW: number } | null>(null);

  useEffect(() => {
    function onMove(e: MouseEvent) {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.startX;
      const grid = gridRef.current;
      const gridW = grid ? grid.getBoundingClientRect().width : window.innerWidth;
      // Leave at least 280px for the middle column.
      const minSide = 160;
      const maxSide = Math.max(minSide, gridW - 280 - (d.side === "left" ? rightW : leftW));
      if (d.side === "left") {
        const w = Math.min(maxSide, Math.max(minSide, d.startW + dx));
        setLeftW(w);
      } else {
        const w = Math.min(maxSide, Math.max(minSide, d.startW - dx));
        setRightW(w);
      }
    }
    function onUp() {
      if (dragRef.current) {
        localStorage.setItem("guardian.leftW", String(leftW));
        localStorage.setItem("guardian.rightW", String(rightW));
      }
      dragRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [leftW, rightW]);

  const startDrag = (side: "left" | "right") => (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { side, startX: e.clientX, startW: side === "left" ? leftW : rightW };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div className="page review-page">
      <TopBar showRound />
      <main
        className="review-grid resizable"
        ref={gridRef as any}
        style={{ gridTemplateColumns: `${leftW}px 6px minmax(0, 1fr) 6px ${rightW}px` }}
      >
        <OriginalContentPanel request={request} />

        <div className="pane-resizer" onMouseDown={startDrag("left")} role="separator" aria-orientation="vertical" />

        <section className="middle-col">
          <AgentCourtroom liveCritics={liveCritics} iterations={iterations} running={running} />
          {iterations.length > 0 && (
            <ScoreProgressionChart iterations={iterations} />
          )}
          {error && <div className="error-banner">⚠️ {error}</div>}
          {intake && (
            <details className="intake-details">
              <summary>Intake parsed ({intake.extracted_claims.length} claims)</summary>
              <pre>{JSON.stringify(intake, null, 2)}</pre>
            </details>
          )}
        </section>

        <div className="pane-resizer" onMouseDown={startDrag("right")} role="separator" aria-orientation="vertical" />

        <ResolverPanel
          iterations={iterations}
          running={running}
          originalContent={request.content}
        />
      </main>

      <UserGate
        visible={showGate}
        versions={versions}
        onAcceptFinal={acceptFinal}
        onEditAndReview={(text) => rerun(text)}
        onRerun={(content) => rerun(content)}
      />
    </div>
  );
}
