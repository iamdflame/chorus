import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./site/tokens.css";
import "./site/chrome.css";
import "./site/pages.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
