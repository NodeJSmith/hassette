import { render } from "preact";
import { App } from "./app";
import "./tokens.css";
import "./global.css";

// Apply persisted theme before first render to avoid FOUC
const savedTheme = localStorage.getItem("ht-theme");
if (savedTheme === "light" || savedTheme === "dark") {
  document.documentElement.setAttribute("data-theme", savedTheme);
}

render(<App />, document.getElementById("app")!);
