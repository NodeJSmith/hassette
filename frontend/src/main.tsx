import { render } from "preact";
import { App } from "./app";
import "./tokens.css";
import "./global.css";

render(<App />, document.getElementById("app")!);
