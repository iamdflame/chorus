import { useEffect, useState } from "react";
import { Link, useRoute } from "./router";

const ROUTES = [
  { to: "/", label: "Overview" },
  { to: "/mechanism", label: "Mechanism" },
  { to: "/evidence", label: "Evidence" },
];

export function Nav() {
  const { path } = useRoute();
  const [lifted, setLifted] = useState(false);
  const [open, setOpen] = useState(false);

  // The bar earns its background only once content is behind it; over the hero it should
  // be invisible chrome, not a slab.
  useEffect(() => {
    const onScroll = () => setLifted(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => setOpen(false), [path]);

  return (
    <header className="nav" data-lifted={lifted} data-open={open}>
      <div className="nav-inner shell">
        <Link to="/" className="mark" aria-label="Chorus home">
          <span className="mark-dot" aria-hidden="true" />
          CHORUS
        </Link>

        <nav className="nav-links" aria-label="Primary">
          {ROUTES.map((route) => (
            <Link
              key={route.to}
              to={route.to}
              className="nav-link"
              data-current={path === route.to}
            >
              {route.label}
            </Link>
          ))}
        </nav>

        <div className="nav-actions">
          <a className="nav-link" href="https://github.com" target="_blank" rel="noreferrer">
            Source
          </a>
          <Link to="/console" className="btn" data-variant={path === "/console" ? undefined : "ghost"}>
            Open console
          </Link>
        </div>

        <button
          className="nav-toggle"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <span /><span />
        </button>
      </div>

      <div className="nav-sheet" hidden={!open}>
        {[...ROUTES, { to: "/console", label: "Console" }].map((route) => (
          <Link key={route.to} to={route.to} className="nav-sheet-link">
            {route.label}
          </Link>
        ))}
      </div>
    </header>
  );
}
