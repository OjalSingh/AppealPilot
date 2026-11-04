"use client";

const GROUNDS: { value: string; label: string }[] = [
  { value: "wrong_vehicle", label: "The photo or plate is not my vehicle" },
  { value: "plate_cloned", label: "Someone may be using a duplicate of my number plate" },
  { value: "vehicle_sold", label: "I had already sold the vehicle" },
  { value: "already_paid", label: "I already paid this challan" },
  { value: "wrong_offence", label: "The offence recorded is not what happened" },
  { value: "no_notice_received", label: "I never received a notice" },
  { value: "notice_incomplete", label: "The notice has no photo or is missing details" },
  { value: "signage_absent", label: "There was no visible warning sign" },
];

export default function ChallanForm({
  busy,
  onSubmit,
  onDemo,
}: {
  busy: boolean;
  onSubmit: (form: FormData) => void;
  onDemo: () => void;
}) {
  function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    for (const [key, value] of Array.from(form.entries())) {
      if (value instanceof File ? !value.size : value === "") form.delete(key);
    }
    onSubmit(form);
  }

  return (
    <form onSubmit={submit} className="card">
      <label>
        Challan notice (photo, PDF or text)
        <input type="file" name="challan" accept=".pdf,.txt,image/png,image/jpeg" />
      </label>
      <label>
        …or paste the notice text
        <textarea name="challan_text" rows={5} placeholder="Challan No: ...  Offence: ...  Date of offence: ..." />
      </label>

      <fieldset>
        <legend>Dates (from your notice)</legend>
        <div className="grid3">
          <label>Date of offence<input type="date" name="offence_date" /></label>
          <label>Notice / challan date<input type="date" name="notice_date" /></label>
          <label>Pay or contest by<input type="date" name="pay_by" /></label>
        </div>
      </fieldset>

      <label>
        Vehicle number
        <input type="text" name="vehicle_number" placeholder="MH12AB1234" autoCapitalize="characters" />
      </label>

      <fieldset>
        <legend>What is wrong with it? (tick all that apply, or leave blank)</legend>
        {GROUNDS.map((g) => (
          <label key={g.value} className="check">
            <input type="checkbox" name="grounds" value={g.value} /> {g.label}
          </label>
        ))}
      </fieldset>

      <div className="grid3">
        <label>
          If sold, date of sale
          <input type="date" name="sold_date" />
        </label>
        <label>
          Type of challan
          <select name="is_echallan" defaultValue="">
            <option value="">Not sure</option>
            <option value="true">E-challan (camera / device)</option>
            <option value="false">On-the-spot challan</option>
          </select>
        </label>
      </div>

      <label>
        Anything else to tell us
        <textarea name="notes" rows={3} placeholder="e.g. I sold the car in May and never got an SMS" />
      </label>
      <label>
        Supporting files (RC, photos, receipts)
        <input type="file" name="supporting" accept=".pdf,.txt,image/png,image/jpeg" multiple />
      </label>

      <div className="row">
        <button type="submit" disabled={busy}>{busy ? "Checking your challan…" : "Check my challan"}</button>
        <button type="button" className="ghost" disabled={busy} onClick={onDemo}>Try a sample challan</button>
      </div>
      <p className="fine">
        We prepare a representation for you to file; the authority decides. This is information, not legal
        advice. If the fine is small, paying can be the sensible choice.
      </p>
    </form>
  );
}
