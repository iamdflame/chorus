import { applyPlace, placeFor } from "./place";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

/** A router in forty lines, because the alternative is a dependency that does the same
 *  thing plus route matching we do not need — this site has four routes.
 *
 *  Navigation goes through `document.startViewTransition`, so the browser snapshots the
 *  outgoing view and animates to the incoming one natively. No transition library, no
 *  cross-fade hack, and it degrades to an ordinary instant swap where the API is absent. */

const RouteContext = createContext<{ path: string; go: (to: string) => void }>({
  path: "/",
  go: () => {},
});

export function RouterProvider({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(() => window.location.pathname);

  // The place is applied from the route rather than toggled by the user. Moving from the
  // record into the apparatus is a lighting change, and it should happen because of where
  // you went, not because of a switch you found.
  useEffect(() => {
    applyPlace(placeFor(path));
  }, [path]);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((to: string) => {
    if (to === window.location.pathname) return;
    const commit = () => {
      window.history.pushState({}, "", to);
      setPath(to);
      window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
    };
    // Feature-detected rather than assumed: where it is missing the navigation still
    // happens, just without the transition.
    if (typeof document.startViewTransition === "function") {
      document.startViewTransition(commit);
    } else {
      commit();
    }
  }, []);

  return <RouteContext.Provider value={{ path, go }}>{children}</RouteContext.Provider>;
}

export const useRoute = () => useContext(RouteContext);

export function Link({
  to, children, className, ...rest
}: { to: string; children: ReactNode; className?: string } & Record<string, unknown>) {
  const { go } = useRoute();
  return (
    <a
      href={to}
      className={className}
      onClick={(event) => {
        // Leave modified clicks alone so open-in-new-tab still works.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        go(to);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}
