// Shared types mirroring backend Pydantic schemas
export type Severity = "HARD" | "SOFT";
export type Verdict = "APPROVE" | "REVISE";
export type CriticName =
  | "fcc_enforcer"
  | "brand_guardian"
  | "persona_simulator"
  | "technical_lead"
  | "ops_strategist";

export interface Violation {
  rule_id: string;
  severity: Severity;
  description: string;
  span?: string | null;
  suggestion?: string | null;
  source?: string | null;
}

export interface CriticVerdict {
  agent: CriticName;
  verdict: Verdict;
  summary: string;
  violations: Violation[];
  iteration: number;
}

export interface IntakeMetadata {
  channel: string;
  audience?: string | null;
  offer_id?: string | null;
  extracted_claims: string[];
}

export interface IterationRecord {
  iteration: number;
  content: string;
  verdicts: CriticVerdict[];
  revised_content?: string | null;
  changelog?: string | null;
}

export interface ToolCallTrace {
  agent: string;
  tool: string;
  input: Record<string, unknown>;
  output: unknown;
  iteration: number;
  ts: string;
}

export interface ReviewResponse {
  final_content: string;
  converged: boolean;
  iterations: IterationRecord[];
  intake: IntakeMetadata;
  audit_trail: ToolCallTrace[];
}

export interface ReviewRequest {
  content: string;
  channel?: string;
  audience?: string;
  offer_id?: string;
}

export type ProgressEvent =
  | { type: "intake"; intake: IntakeMetadata }
  | { type: "critic"; verdict: CriticVerdict }
  | { type: "iteration"; iteration: IterationRecord }
  | { type: "done"; response: ReviewResponse }
  | { type: "error"; error: string };

export const CRITIC_META: Record<CriticName, { label: string; emoji: string; color: string }> = {
  fcc_enforcer:      { label: "FCC Enforcer",      emoji: "🔴", color: "#dc2626" },
  brand_guardian:    { label: "Brand Guardian",    emoji: "🟡", color: "#ca8a04" },
  persona_simulator: { label: "Persona Simulator", emoji: "🟢", color: "#16a34a" },
  technical_lead:    { label: "Technical Lead",    emoji: "🔵", color: "#2563eb" },
  ops_strategist:    { label: "Ops Strategist",    emoji: "🟣", color: "#9333ea" },
};
