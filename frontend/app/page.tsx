"use client";

import { useState } from "react";
import type { CaseResult } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const label = (s: string) => s.replace(/_/g, " ");
const fmtDate = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export default function Home() {
  const [result, setResult] = useState<CaseResult | null>(null);
  const [letter, setLetter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(req: Promise<Response>) {
    setBusy(true);
    setError(null);
    try {
      const res = await req;
      if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
      const data: CaseResult = await res.json();
      setResult(data);
      setLetter(data.appeal?.body ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (!(form.get("denial") as File)?.size) form.delete("denial");
    for (const f of form.getAll("supporting") as File[]) if (!f.size) form.delete("supporting");
    run(fetch(`${API}/api/cases`, { method: "POST", body: form }));
  }

  async function deleteCase() {
    if (!result) return;
    await fetch(`${API}/api/cases/${result.case_id}`, { method: "DELETE" });
    setResult(null);
    setLetter("");
  }

  return (
    <main>
      <header>
        <h1>AppealPilot</h1>
        <p className="lead">
          Your health claim was denied. Upload the denial letter and your policy, and get an appeal that
          cites the exact clauses on your side, a list of missing documents, and every deadline.
        </p>
      </header>

      {!result && (
        <form onSubmit={submit} className="card">
          <label>
            Policy wording (PDF or text) <span className="req">required</span>
            <input type="file" name="policy" accept=".pdf,.txt" required />
          </label>
          <label>
            Denial / repudiation letter
            <input type="file" name="denial" accept=".pdf,.txt" />
          </label>
          <label>
            …or paste the denial letter
            <textarea name="denial_text" rows={5} placeholder="Reason for rejection: ..." />
          </label>
          <label>
            Bills, discharge summary, reports (optional)
            <input type="file" name="supporting" accept=".pdf,.txt" multiple />
          </label>
          <div className="row">
            <button type="submit" disabled={busy}>{busy ? "Building your appeal…" : "Build my appeal"}</button>
            <button type="button" className="ghost" disabled={busy}
              onClick={() => run(fetch(`${API}/api/demo`, { method: "POST" }))}>
              Try a sample case
            </button>
          </div>
          <p className="fine">
            Files are used only for your case and can be deleted at any time. This is information, not legal advice.
          </p>
        </form>
      )}

      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <section className="card">
            <div className="row between">
              <h2>What the insurer said</h2>
              <span className={`pill ${result.mode}`}>{result.mode === "claude" ? "Claude agent" : "offline mode"}</span>
            </div>
            <dl>
              <dt>Denial type</dt><dd>{label(result.denial.category)}</dd>
              {result.denial.insurer && (<><dt>Insurer</dt><dd>{result.denial.insurer}</dd></>)}
              {result.denial.claim_number && (<><dt>Claim</dt><dd>{result.denial.claim_number}</dd></>)}
              {result.denial.amount_claimed && (<><dt>Amount</dt><dd>₹{result.denial.amount_claimed.toLocaleString("en-IN")}</dd></>)}
            </dl>
            <blockquote>{result.denial.reason_text}</blockquote>
          </section>

          {result.appeal && (
            <section className="card">
              <h2>Clauses on your side</h2>
              {result.appeal.citations.map((c) => (
                <div key={c.clause_id} className="cite">
                  <strong>Clause {c.clause_id.split(":").pop()}</strong>
                  <q>{c.quote}</q>
                  <p>{c.argument}</p>
                </div>
              ))}
            </section>
          )}

          {result.documents && (
            <section className="card">
              <h2>Documents</h2>
              <ul className="checks">
                {result.documents.present.map((d) => <li key={d} className="ok">{d}</li>)}
                {result.documents.missing.map((d) => <li key={d} className="miss">{d} (missing)</li>)}
              </ul>
            </section>
          )}

          <section className="card">
            <div className="row between">
              <h2>Your appeal letter</h2>
              <div className="row">
                <button className="ghost" onClick={() => navigator.clipboard.writeText(letter)}>Copy</button>
                <a className="button ghost" download="appeal.txt"
                  href={`data:text/plain;charset=utf-8,${encodeURIComponent(letter)}`}>Download</a>
              </div>
            </div>
            <textarea className="letter" value={letter} onChange={(e) => setLetter(e.target.value)} rows={22} />
          </section>

          <section className="card">
            <div className="row between">
              <h2>Deadlines</h2>
              <a className="button ghost" href={`${API}/api/cases/${result.case_id}/deadlines.ics`}>Add to calendar</a>
            </div>
            <ol className="timeline">
              {result.deadlines.map((d) => (
                <li key={d.step}>
                  <time>{fmtDate(d.due)}</time>
                  <div>
                    <strong>{label(d.step)}</strong>
                    <p>{d.description}</p>
                    <small>{d.source}</small>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <div className="row">
            <button className="ghost" onClick={() => setResult(null)}>Start a new case</button>
            <button className="danger" onClick={deleteCase}>Delete my data</button>
          </div>
        </>
      )}
    </main>
  );
}
