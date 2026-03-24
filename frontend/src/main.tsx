import { render } from "preact";
import { App } from "./app";
import { getStoredValue, migrateKey } from "./utils/local-storage";
import { isTheme } from "./utils/theme";
import "./tokens.css";
import "./global.css";

// Run all localStorage migrations before any reads.
// This is the canonical location for migrations — add new ones here.
migrateKey("ht-theme", "theme");

// Apply persisted theme before first render to avoid FOUC.
const savedTheme = getStoredValue("theme", "dark" as const, isTheme);
document.documentElement.setAttribute("data-theme", savedTheme);

render(<App />, document.getElementById("app")!);
