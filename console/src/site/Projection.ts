/** The projection, computed in the browser exactly as the kernel computes it.
 *
 *  This is a port, not an illustration. `swarm/canonical.py` builds the same key from the
 *  same buckets in the same order, and `tests/test_projection_parity` fails if the two
 *  ever disagree — because a teaching page that quietly diverges from the system it is
 *  teaching is worse than no page.
 *
 *  What is deliberately NOT done here is faking an effect address. The real one is
 *  blake2b over (kind, role, causal parents, canonical request), and hashing something
 *  else in the browser to produce an official-looking hex string would be inventing
 *  evidence. The projection key is the thing that actually decides whether two agents
 *  share a thought, so it is the honest object to show.
 */

export const SCHEMA = "v2";

export const TIERS = ["basic", "silver", "gold", "platinum"] as const;
export const URGENCIES = ["critical", "urgent", "same_day", "flexible"] as const;
export const CONSTRAINTS = ["assisted", "checked_bags", "unencumbered"] as const;
export const HAULS = ["short", "long", "intercontinental"] as const;

export interface Traveller {
  name: string;
  tier: (typeof TIERS)[number];
  hoursUntil: number;
  partySize: number;
  needsAssistance: boolean;
  checkedBags: number;
  haul: (typeof HAULS)[number];
  hotelEntitled: boolean;
  misconnect: boolean;
}

/** Buckets, matching kernel order. Coarse on purpose: every extra distinction multiplies
 *  the number of distinct thoughts, and one that does not change the decision buys
 *  nothing but cost. */
export function urgencyBand(hours: number): string {
  if (hours <= 4) return "critical";
  if (hours <= 12) return "urgent";
  if (hours <= 24) return "same_day";
  return "flexible";
}

export function partyBand(size: number): string {
  if (size <= 1) return "solo";
  if (size === 2) return "pair";
  if (size <= 4) return "family";
  return "group";
}

export function constraintBand(bags: number, assistance: boolean): string {
  if (assistance) return "assisted";
  if (bags > 0) return "checked_bags";
  return "unencumbered";
}

export function projectionKey(t: Traveller): string {
  return [
    SCHEMA,
    "passenger",
    t.tier,
    urgencyBand(t.hoursUntil),
    partyBand(t.partySize),
    constraintBand(t.checkedBags, t.needsAssistance),
    t.haul,
    t.hotelEntitled ? "hotel" : "nohotel",
    t.misconnect ? "misconnect" : "origin",
  ].join("|");
}

/** The lattice ceiling: 4 x 4 x 4 x 3 x 3 x 2 x 2. Stated rather than discovered — a
 *  saturation claim without its ceiling invites the reader to wonder whether the curve
 *  keeps climbing off the right of the frame. */
export const CEILING =
  TIERS.length * URGENCIES.length * 4 * CONSTRAINTS.length * HAULS.length * 2 * 2;
