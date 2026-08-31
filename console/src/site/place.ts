/** Plate and Instrument — the two places this product is.
 *
 *  Not a theme toggle. The Plate is the permanent record and the Instrument is the live
 *  detector, and moving between them is a lighting change that encodes something true:
 *  you are stepping from the record into the apparatus. Routes declare which place they
 *  are, so no component ever has to know.
 *
 *  The transition is deliberately one thing used consistently. `--dur-place` on the body
 *  background and text handles the crossfade; the typographic axes shift with it because
 *  they are declared per-place in the token file rather than set here.
 */

export type Place = "instrument" | "plate";

/** Which place each route is. The record is read; the instrument is watched. */
const PLACES: Record<string, Place> = {
  "/": "instrument",
  "/console": "instrument",
  "/incident": "instrument",
  "/intake": "instrument",
  "/mechanism": "plate",
  "/evidence": "plate",
  "/ledger": "plate",
  "/registry": "plate",
  "/architecture": "plate",
  "/policy": "plate",
};

export function placeFor(path: string): Place {
  if (PLACES[path]) return PLACES[path];
  // Deep links inherit their section's lighting: /policy/:cell is provenance, so Plate.
  const root = "/" + path.split("/").filter(Boolean)[0];
  return PLACES[root] ?? "instrument";
}

/** Apply a place to the document. Idempotent, so routing can call it freely. */
export function applyPlace(place: Place): void {
  const root = document.documentElement;
  if (root.dataset.place === place) return;
  root.dataset.place = place;
  // A meta theme-color that lags the page by 420ms looks like a bug on mobile, so it is
  // set from the resolved token immediately rather than transitioned.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    const housing = getComputedStyle(root).getPropertyValue("--housing").trim();
    if (housing) meta.setAttribute("content", housing);
  }
}
