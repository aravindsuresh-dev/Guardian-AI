import { useEffect, useState } from "react";

export interface VersionOption {
  /** Stable id used as the React key & select value. */
  id: string;
  /** Short human label like "Original" or "Round 2 rewrite". */
  label: string;
  /** Full content for that version. */
  content: string;
}

export function UserGate({
  visible,
  versions,
  onAcceptFinal,
  onEditAndReview,
  onRerun,
}: {
  visible: boolean;
  /** Ordered list: index 0 = original, last = latest rewrite. Must be non-empty when visible. */
  versions: VersionOption[];
  onAcceptFinal: (content: string) => void;
  onEditAndReview: (newText: string) => void;
  onRerun: (content: string) => void;
}) {
  const latestId = versions[versions.length - 1]?.id ?? "";
  const [selectedId, setSelectedId] = useState(latestId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  // When a new round arrives, auto-advance the selection to the latest.
  useEffect(() => {
    setSelectedId(latestId);
  }, [latestId]);

  if (!visible) return null;
  const selected = versions.find((v) => v.id === selectedId) ?? versions[versions.length - 1];
  const proposedContent = selected.content;

  if (editing) {
    return (
      <div className="user-gate">
        <div className="gate-edit">
          <div className="gate-edit-label">
            Editing <strong>{selected.label}</strong> — re-run the critics on this revised text:
          </div>
          <textarea
            autoFocus
            rows={5}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="gate-edit-actions">
            <button className="secondary" onClick={() => { setEditing(false); }}>Cancel</button>
            <button onClick={() => onEditAndReview(draft)} disabled={!draft.trim()}>
              Submit & Re-review
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="user-gate">
      {versions.length > 1 && (
        <div className="gate-versions" role="radiogroup" aria-label="Choose version">
          <span className="gate-versions-label">Use version:</span>
          {versions.map((v) => (
            <button
              key={v.id}
              type="button"
              role="radio"
              aria-checked={v.id === selectedId}
              className={`version-pill${v.id === selectedId ? " active" : ""}`}
              onClick={() => setSelectedId(v.id)}
              title={v.content.slice(0, 200)}
            >
              {v.label}
            </button>
          ))}
        </div>
      )}

      <div className="gate-actions">
        <button className="gate-btn approve" onClick={() => onAcceptFinal(proposedContent)}>
          <span className="gate-icon">✅</span>
          <div>
            <div className="gate-title">Accept as Final & Export</div>
            <div className="gate-sub">Lock <em>{selected.label}</em> and view the audit report</div>
          </div>
        </button>
        <button
          className="gate-btn edit"
          onClick={() => { setDraft(proposedContent); setEditing(true); }}
        >
          <span className="gate-icon">✏️</span>
          <div>
            <div className="gate-title">Edit & Re-review</div>
            <div className="gate-sub">Tweak <em>{selected.label}</em>, then run critics again</div>
          </div>
        </button>
        <button className="gate-btn final" onClick={() => onRerun(proposedContent)}>
          <span className="gate-icon">🔁</span>
          <div>
            <div className="gate-title">Run Adversarial Round Again</div>
            <div className="gate-sub">Use <em>{selected.label}</em> as input for another pass</div>
          </div>
        </button>
      </div>
    </div>
  );
}
