import type { ReviewRequest } from "../types";

const CHANNEL_ICON: Record<string, string> = {
  SMS: "💬", sms: "💬",
  Email: "✉️", email: "✉️",
  LinkedIn: "💼", linkedin: "💼",
  Facebook: "📘", facebook: "📘",
  Instagram: "📸", instagram: "📸",
  landing_page: "🌐",
  press_release: "📰",
};

export function OriginalContentPanel({ request, content }: { request: ReviewRequest; content?: string }) {
  const channel = request.channel || "SMS";
  const audience = request.audience || "—";
  const text = content ?? request.content;
  return (
    <aside className="left-panel">
      <h3>Original</h3>
      <div className="pill-row">
        <span className="pill channel-pill">{CHANNEL_ICON[channel] || "📨"} {channel}</span>
        <span className="pill audience-pill">👥 {audience}</span>
      </div>
      {request.offer_id && <div className="pill offer-pill">🏷️ {request.offer_id}</div>}
      <div className="orig-label">Content reviewed</div>
      <pre className="orig-content">{text}</pre>
      <div className="orig-meta">
        <div><span className="muted">chars</span> {text.length}</div>
      </div>
    </aside>
  );
}
