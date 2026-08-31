import { Console } from "./Console";
import { Footer } from "./site/Footer";
import { Nav } from "./site/Nav";
import { Evidence } from "./site/pages/Evidence";
import { Architecture } from "./site/pages/Architecture";
import { Policy } from "./site/pages/Policy";
import { Registry } from "./site/pages/Registry";
import { Home } from "./site/pages/Home";
import { Incident } from "./site/pages/Incident";
import { Intake } from "./site/pages/Intake";
import { LedgerPage } from "./site/pages/Ledger";
import { Mechanism } from "./site/pages/Mechanism";
import { RouterProvider, useRoute } from "./site/router";

function Routes() {
  const { path } = useRoute();

  // The console is an application, not a document: it gets the full viewport beneath the
  // nav and no footer, because a marketing footer under a live canvas reads as a mistake.
  if (path === "/console") {
    return (
      <>
        <Nav />
        <div className="console-frame"><Console /></div>
      </>
    );
  }

  return (
    <>
      <div className="grid-field" aria-hidden="true" />
      <Nav />
      <main>
        {path === "/mechanism" ? <Mechanism />
          : path === "/evidence" ? <Evidence />
          : path === "/ledger" ? <LedgerPage />
          : path === "/incident" ? <Incident />
          : path === "/intake" ? <Intake />
          : path === "/registry" ? <Registry />
          : path === "/architecture" ? <Architecture />
          : path === "/policy" || path.startsWith("/policy/") ? <Policy />
          : <Home />}
      </main>
      <Footer />
    </>
  );
}

export function App() {
  return (
    <RouterProvider>
      <Routes />
    </RouterProvider>
  );
}
