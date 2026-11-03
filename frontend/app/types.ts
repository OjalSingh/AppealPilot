export type Clause = { id: string; number: string | null; title: string | null; text: string };
export type Hit = { clause: Clause; score: number; bm25_rank: number | null; vector_rank: number | null };
export type Citation = { clause_id: string; quote: string; argument: string };
export type Deadline = { step: string; due: string; description: string; source: string };

export type CaseResult = {
  case_id: string;
  mode: "claude" | "offline";
  denial: {
    insurer: string | null;
    claim_number: string | null;
    denial_date: string | null;
    amount_claimed: number | null;
    category: string;
    reason_text: string;
    clauses_cited_by_insurer: string[];
  };
  hits: Hit[];
  documents: { present: string[]; missing: string[]; notes: string[] } | null;
  appeal: { subject: string; body: string; citations: Citation[]; requested_relief: string } | null;
  deadlines: Deadline[];
  usage: Record<string, number>;
};
