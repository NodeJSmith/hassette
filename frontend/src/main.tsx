import "./global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app";
import { getStoredValue, migrateKey } from "./utils/local-storage";
import { isTheme } from "./utils/theme";

// Run all localStorage migrations before any reads.
// This is the canonical location for migrations — add new ones here.
migrateKey("ht-theme", "theme");

// Apply persisted theme before first render to avoid FOUC.
const savedTheme = getStoredValue("theme", "light" as const, isTheme);
document.documentElement.setAttribute("data-theme", savedTheme);

createRoot(document.getElementById("app")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
