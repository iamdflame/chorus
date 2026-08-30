import { useState } from "react";
import {
  CEILING, HAULS, TIERS, type Traveller, projectionKey,
} from "./Projection";

/** Two travellers, one thought — or two, if you change the right field.
 *
 *  Understanding arrives in about four seconds here, which is faster than any paragraph
 *  manages. The keys are computed by a port of the kernel's own bucketing, and
 *  tests/test_projection_parity.py fails if the two ever drift apart. */

const A: Traveller = {
  name: "Aisha Kwarteng", tier: "platinum", hoursUntil: 3, partySize: 1,
  needsAssistance: false, checkedBags: 1, haul: "long",
  hotelEntitled: true, misconnect: false,
};

const B: Traveller = {
  name: "Tom Reilly", tier: "platinum", hoursUntil: 2, partySize: 1,
  needsAssistance: false, checkedBags: 2, haul: "long",
  hotelEntitled: true, misconnect: false,
};

function Card({
  who, set, label,
}: { who: Traveller; set: (t: Traveller) => void; label: string }) {
  const key = projectionKey(who);
  return (
    <div className="addr-card">
      <p className="eyebrow">{label}</p>
      <p className="addr-name">{who.name}</p>

      <label className="addr-field">
        <span>tier</span>
        <select value={who.tier}
                onChange={(e) => set({ ...who, tier: e.target.value as Traveller["tier"] })}>
          {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </label>

      <label className="addr-field">
        <span>hours until departure</span>
        <input type="number" min={0} max={72} value={who.hoursUntil}
               onChange={(e) => set({ ...who, hoursUntil: Number(e.target.value) })} />
      </label>

      <label className="addr-field">
        <span>party size</span>
        <input type="number" min={1} max={9} value={who.partySize}
               onChange={(e) => set({ ...who, partySize: Number(e.target.value) })} />
      </label>

      <label className="addr-field">
        <span>checked bags</span>
        <input type="number" min={0} max={6} value={who.checkedBags}
               onChange={(e) => set({ ...who, checkedBags: Number(e.target.value) })} />
      </label>

      <label className="addr-field">
        <span>journey</span>
        <select value={who.haul}
                onChange={(e) => set({ ...who, haul: e.target.value as Traveller["haul"] })}>
          {HAULS.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
      </label>

      <label className="addr-field addr-check">
        <input type="checkbox" checked={who.needsAssistance}
               onChange={(e) => set({ ...who, needsAssistance: e.target.checked })} />
        <span>needs assistance</span>
      </label>

      <p className="addr-key data" aria-label="projection key">{key}</p>
    </div>
  );
}

export function AddressDemo() {
  const [a, setA] = useState(A);
  const [b, setB] = useState(B);
  const same = projectionKey(a) === projectionKey(b);

  return (
    <div className="addr">
      <div className="addr-cards">
        <Card who={a} set={setA} label="Passenger A" />
        <Card who={b} set={setB} label="Passenger B" />
      </div>

      <div className="addr-verdict" data-same={same}>
        {same ? (
          <>
            <p className="addr-verdict-head">Same projection → one thought</p>
            <p className="muted">
              Their names differ. Their bags differ. Their reasoning does not, so the
              second one is served from the store. <strong>A pays $0.00096. B pays $0.</strong>
            </p>
          </>
        ) : (
          <>
            <p className="addr-verdict-head">Different projections → two thoughts</p>
            <p className="muted">
              A field that changes the decision changes the bucket, and a changed bucket is
              a second model call. <strong>Both pay $0.00096.</strong>
            </p>
          </>
        )}
      </div>

      <p className="addr-foot faint">
        <span>
        Nothing here is a rendering of an address. The effect address is blake2b over
        (kind, role, causal parents, canonical request); what is shown is the projection
        key, which is the thing that actually decides whether two agents share a thought.
        One of {CEILING.toLocaleString()} possible.
        </span>
      </p>
    </div>
  );
}
