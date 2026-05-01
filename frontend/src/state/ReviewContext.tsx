import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { reviewStream } from "../api/client";
import type {
  CriticVerdict, IntakeMetadata, IterationRecord, ReviewRequest, ReviewResponse, ToolCallTrace,
} from "../types";

type Status = "idle" | "running" | "done" | "error";

interface Ctx {
  request: ReviewRequest | null;
  setRequest: (r: ReviewRequest) => void;

  status: Status;
  startedAt: number | null;
  roundStartedAt: number | null;

  intake: IntakeMetadata | null;
  iterations: IterationRecord[];
  liveCritics: CriticVerdict[];
  auditTrail: ToolCallTrace[];
  final: ReviewResponse | null;
  error: string | null;
  /** User-chosen final content (any prior version). Falls back to latest. */
  selectedFinal: string | null;
  setSelectedFinal: (content: string) => void;

  /** Start the very first review (clears any prior state). */
  start: () => void;
  /** Run another adversarial round with new content, preserving history. */
  rerun: (newContent: string) => void;
  cancel: () => void;
  reset: () => void;
}

const ReviewCtx = createContext<Ctx | null>(null);

export function ReviewProvider({ children }: { children: ReactNode }) {
  const [request, setRequestState] = useState<ReviewRequest | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [roundStartedAt, setRoundStartedAt] = useState<number | null>(null);
  const [intake, setIntake] = useState<IntakeMetadata | null>(null);
  const [iterations, setIterations] = useState<IterationRecord[]>([]);
  const [liveCritics, setLiveCritics] = useState<CriticVerdict[]>([]);
  const [auditTrail, setAuditTrail] = useState<ToolCallTrace[]>([]);
  const [final, setFinal] = useState<ReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedFinal, setSelectedFinal] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const iterCountRef = useRef(0); // total rounds completed across reruns

  const setRequest = useCallback((r: ReviewRequest) => setRequestState(r), []);

  const reset = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("idle");
    setStartedAt(null);
    setRoundStartedAt(null);
    setIntake(null);
    setIterations([]);
    setLiveCritics([]);
    setAuditTrail([]);
    setFinal(null);
    setError(null);
    setSelectedFinal(null);
    iterCountRef.current = 0;
  }, []);

  // Internal: open WS for the current request. `preserveHistory` keeps prior iterations.
  const openStream = useCallback((req: ReviewRequest, preserveHistory: boolean) => {
    wsRef.current?.close();
    setLiveCritics([]);
    setFinal(null);
    setError(null);
    setStatus("running");
    setRoundStartedAt(Date.now());
    if (!preserveHistory) {
      setIntake(null);
      setIterations([]);
      setAuditTrail([]);
      iterCountRef.current = 0;
      setStartedAt(Date.now());
    } else if (!startedAt) {
      setStartedAt(Date.now());
    }

    wsRef.current = reviewStream(
      req,
      (e) => {
        if (e.type === "intake") setIntake(e.intake);
        else if (e.type === "critic") setLiveCritics((p) => [...p, e.verdict]);
        else if (e.type === "iteration") {
          // Re-number the iteration to reflect TOTAL rounds across reruns
          const renumbered: IterationRecord = { ...e.iteration, iteration: iterCountRef.current + 1 };
          renumbered.verdicts = renumbered.verdicts.map((v) => ({ ...v, iteration: renumbered.iteration }));
          iterCountRef.current += 1;
          setIterations((p) => [...p, renumbered]);
          setLiveCritics([]);
        } else if (e.type === "done") {
          setFinal(e.response);
          setAuditTrail((p) => [...p, ...e.response.audit_trail]);
          setStatus("done");
        } else if (e.type === "error") {
          setError(e.error);
          setStatus("error");
        }
      },
      () => {
        setStatus((s) => (s === "running" ? "done" : s));
      },
    );
  }, [startedAt]);

  const start = useCallback(() => {
    if (!request) return;
    openStream(request, /* preserveHistory */ false);
  }, [request, openStream]);

  const rerun = useCallback((newContent: string) => {
    if (!request) return;
    const next = { ...request, content: newContent };
    setRequestState(next);
    openStream(next, /* preserveHistory */ true);
  }, [request, openStream]);

  const cancel = useCallback(() => {
    wsRef.current?.close();
    setStatus("idle");
  }, []);

  useEffect(() => () => { wsRef.current?.close(); }, []);

  const value = useMemo<Ctx>(() => ({
    request, setRequest,
    status, startedAt, roundStartedAt,
    intake, iterations, liveCritics, auditTrail, final, error,
    selectedFinal, setSelectedFinal,
    start, rerun, cancel, reset,
  }), [request, setRequest, status, startedAt, roundStartedAt, intake, iterations, liveCritics, auditTrail, final, error, selectedFinal, start, rerun, cancel, reset]);

  return <ReviewCtx.Provider value={value}>{children}</ReviewCtx.Provider>;
}

export function useReview(): Ctx {
  const c = useContext(ReviewCtx);
  if (!c) throw new Error("useReview must be inside ReviewProvider");
  return c;
}
