import type { ProgressEvent, ReviewRequest, ReviewResponse } from "../types";

const BASE = ""; // Vite proxies /api and /ws to backend

export async function listOffers(): Promise<Array<Record<string, unknown>>> {
  const r = await fetch(`${BASE}/api/offers`);
  return r.json();
}

export async function getViolationSamples(): Promise<{ samples: Array<Record<string, unknown>> }> {
  const r = await fetch(`${BASE}/api/samples/violation`);
  return r.json();
}

export async function reviewSync(req: ReviewRequest): Promise<ReviewResponse> {
  const r = await fetch(`${BASE}/api/review`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json();
}

export function reviewStream(
  req: ReviewRequest,
  onEvent: (e: ProgressEvent) => void,
  onClose?: () => void,
): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/ws/review`);
  ws.onopen = () => ws.send(JSON.stringify(req));
  ws.onmessage = (ev) => {
    try {
      onEvent(JSON.parse(ev.data) as ProgressEvent);
    } catch {
      /* ignore */
    }
  };
  ws.onclose = () => onClose?.();
  return ws;
}
