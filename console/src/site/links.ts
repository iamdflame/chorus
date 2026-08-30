/** Outbound links, in one place.
 *
 *  The repository URL appears in the nav, the footer and two pages. Scattered as string
 *  literals it is four opportunities to ship a placeholder that a judge will click; as
 *  one constant it is a single line to set. */

export const REPO = "https://github.com/iamdflame/chorus";

const file = (path: string) => `${REPO}/blob/main/${path}`;

export const LINKS = {
  repo: REPO,
  readme: file("README.md"),
  architecture: file("docs/ARCHITECTURE.md"),
  swarmProof: file("scripts/prove_swarm.py"),
  determinismProof: file("scripts/verify_determinism.py"),
  fleetProof: file("scripts/verify_fleet_replay.py"),
  kernel: file("kernel/interposer.py"),
  projection: file("swarm/canonical.py"),
} as const;
