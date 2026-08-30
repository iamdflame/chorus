import { LINKS } from "./links";
import { Mark } from "./Mark";
import { Link } from "./router";

type FooterLink = { label: string; to: string } | { label: string; href: string };

const COLUMNS: { title: string; links: FooterLink[] }[] = [
  {
    title: "System",
    links: [
      { label: "Overview", to: "/" },
      { label: "Mechanism", to: "/mechanism" },
      { label: "Evidence", to: "/evidence" },
      { label: "Console", to: "/console" },
    ],
  },
  {
    title: "Built on",
    links: [
      { label: "Gemini 3.5 Flash", href: "https://ai.google.dev/gemini-api/docs" },
      { label: "Agent Development Kit", href: "https://google.github.io/adk-docs/" },
      { label: "Vertex AI", href: "https://cloud.google.com/vertex-ai" },
      { label: "Cloud Run", href: "https://cloud.google.com/run" },
      { label: "Firestore", href: "https://cloud.google.com/firestore" },
    ],
  },
  {
    title: "Reading",
    links: [
      { label: "Architecture", href: LINKS.architecture },
      { label: "The projection", href: LINKS.projection },
      { label: "The interposer", href: LINKS.kernel },
      { label: "Swarm proof", href: LINKS.swarmProof },
      { label: "README", href: LINKS.readme },
    ],
  },
];

export function Footer() {
  return (
    <footer className="footer">
      <div className="shell">
        <div className="footer-top">
          <div className="footer-brand">
            <div className="mark"><Mark />CHORUS</div>
            <p className="footer-claim display h3">
              Twenty&nbsp;thousand agents.<br /><em>Two hundred thoughts.</em>
            </p>
            <p className="footer-note">
              One agent per entity, for the price of the situations they are actually in.
            </p>
          </div>

          <div className="footer-cols">
            {COLUMNS.map((column) => (
              <div className="footer-col" key={column.title}>
                <h3>{column.title}</h3>
                <ul>
                  {column.links.map((link) => (
                    <li key={link.label}>
                      {"to" in link ? (
                        <Link to={link.to}>{link.label}</Link>
                      ) : (
                        <a href={link.href} target="_blank" rel="noreferrer">{link.label}</a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div className="footer-bottom">
          <span>Built for the All Things Agentic hackathon.</span>
          <span className="footer-live">
            <i aria-hidden="true" /> live on Cloud Run · us-central1
          </span>
        </div>
      </div>
    </footer>
  );
}
