import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { useReview } from "../state/ReviewContext";

const CHANNELS = ["SMS", "Email", "LinkedIn", "Landing Page", "Press Release"];
const AUDIENCES = ["Consumer (General)", "Executive (VP+)", "Small Business Owner", "Technical (IT/Ops)"];

export default function UploadPage() {
  const nav = useNavigate();
  const { setRequest, reset } = useReview();
  const [content, setContent] = useState("");
  const [channel, setChannel] = useState("SMS");
  const [audience, setAudience] = useState("Consumer (General)");

  useEffect(() => { reset(); }, [reset]);

  function go() {
    if (!content.trim()) return;
    setRequest({ content, channel, audience });
    nav("/review");
  }

  return (
    <div className="page upload-page">
      <TopBar />
      <main className="upload-main">
        <section className="hero">
          <h1>Catch compliance issues <span className="grad">before</span> they ship.</h1>
          <p>Guardian AI brings an adversarial, red-teaming approach to telecom marketing content. Five specialized AI agents scrutinize your content, finding every compliance flaw before it goes live.</p>
        </section>

        <section className="agents-strip">
          <div className="agents-row">
            <div className="agent-tile agent-fcc">
              <div className="agent-icon" aria-hidden>⚖️</div>
              <div className="agent-name">FCC Enforcer</div>
              <div className="agent-role">FCC/FTC Compliance Attorney</div>
            </div>
            <div className="agent-tile agent-brand">
              <div className="agent-icon" aria-hidden>🛡️</div>
              <div className="agent-name">Brand Guardian</div>
              <div className="agent-role">Voice &amp; Terminology Sentinel</div>
            </div>
            <div className="agent-tile agent-persona">
              <div className="agent-icon" aria-hidden>👥</div>
              <div className="agent-name">Persona Simulator</div>
              <div className="agent-role">Thinks Like Your Customer</div>
            </div>
            <div className="agent-tile agent-tech">
              <div className="agent-icon" aria-hidden>🔬</div>
              <div className="agent-name">Technical Lead</div>
              <div className="agent-role">Senior Product Spec Auditor</div>
            </div>
            <div className="agent-tile agent-ops">
              <div className="agent-icon" aria-hidden>📋</div>
              <div className="agent-name">Ops Strategist</div>
              <div className="agent-role">Marketing Operations Quality Lead</div>
            </div>
          </div>
        </section>

        <section className="upload-card">
          <label className="big-label">Your content</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste your ad copy, SMS, email, or landing page text..."
            rows={10}
          />
          <div className="char-count">{content.length} chars</div>

          <div className="upload-row">
            <div>
              <label>Channel</label>
              <select value={channel} onChange={(e) => setChannel(e.target.value)}>
                {CHANNELS.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label>Audience</label>
              <select value={audience} onChange={(e) => setAudience(e.target.value)}>
                {AUDIENCES.map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
          </div>

          <button className="cta" disabled={!content.trim()} onClick={go}>
            🚀 Start Compliance Review
          </button>
        </section>

        <section className="info-card">
          <h3>What happens next?</h3>
          <ol>
            <li><b>Intake</b> parses channel, audience, offer, and extracts factual claims.</li>
            <li><b>5 critics</b> review in parallel, citing rules from their own lane only.</li>
            <li><b>Resolver</b> rewrites the content, scores 1–10, and lists every edit.</li>
            <li>You <b>accept</b>, <b>edit & re-review</b>, or <b>run another adversarial round</b> — for as many passes as you need.</li>
          </ol>
        </section>
      </main>
    </div>
  );
}
