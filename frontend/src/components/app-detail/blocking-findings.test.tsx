import { fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../../api/generated-types";
import { createBlockingFinding, createFrameRef } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import { BlockingFindingsSection } from "./blocking-findings";

type BlockingFindingsResponse = components["schemas"]["BlockingFindingsResponse"];
type BlockingFinding = components["schemas"]["BlockingFinding"];

const APP_KEY = "car_climate";

function serveFindings(findings: BlockingFinding[], truncated = false) {
  const seen: URL[] = [];
  server.use(
    http.get("/api/telemetry/app/:app_key/blocking", ({ request }) => {
      seen.push(new URL(request.url));
      return HttpResponse.json<BlockingFindingsResponse>({ findings, truncated });
    }),
  );
  return seen;
}

function renderSection(instanceQs = "") {
  return renderWithAppState(
    <BlockingFindingsSection appKey={APP_KEY} resolvedInstanceIndex={2} instanceQs={instanceQs} />,
    { storeOverrides: { uptimeSeconds: 120 } },
  );
}

describe("BlockingFindingsSection", () => {
  it("renders nothing when the app has no findings", async () => {
    const seen = serveFindings([]);
    const { queryByTestId } = renderSection();
    await waitFor(() => expect(seen.length).toBe(1));
    expect(queryByTestId("overview-blocking-findings")).toBeNull();
  });

  it("renders nothing when the fetch fails", async () => {
    server.use(http.get("/api/telemetry/app/:app_key/blocking", () => HttpResponse.json(null, { status: 503 })));
    const { queryByTestId } = renderSection();
    await new Promise((r) => setTimeout(r, 50));
    expect(queryByTestId("overview-blocking-findings")).toBeNull();
  });

  it("requests the resolved instance", async () => {
    const seen = serveFindings([]);
    renderSection();
    await waitFor(() => expect(seen[0]?.searchParams.get("instance_index")).toBe("2"));
  });

  it("shows the call site, what it calls into, the handlers, and the stats", async () => {
    serveFindings([createBlockingFinding({ app_key: APP_KEY })]);
    const { findByTestId, getByRole } = renderSection("?instance=2");
    const entry = await findByTestId("overview-blocking-finding-0");

    expect(entry.textContent).toContain("calendar_service.py:98 in get_calendar_events");
    expect(entry.textContent).toContain("calls gcsa/events.py get_events");
    expect(entry.textContent).toContain("9 events · up to 534.0ms · avg 300.0ms · last seen");
    const handlerLink = getByRole("link", { name: "scan_and_schedule" }) as HTMLAnchorElement;
    expect(handlerLink.href).toContain(`/apps/${APP_KEY}/handlers/job/7?instance=2`);
  });

  it("expands the latest stack with absolute paths, outermost frame first", async () => {
    serveFindings([createBlockingFinding()]);
    const { findByTestId, getByTestId } = renderSection();
    fireEvent.click(await findByTestId("overview-blocking-finding-0-stack-toggle"));

    const lines = getByTestId("overview-blocking-finding-0-stack").textContent ?? "";
    expect(lines.indexOf("/apps/calendar_service.py")).toBeGreaterThanOrEqual(0);
    expect(lines.indexOf("/apps/calendar_service.py")).toBeLessThan(lines.indexOf("/usr/local/lib/python3.13/ssl.py"));
  });

  it("says when no call site was captured", async () => {
    serveFindings([createBlockingFinding({ call_site: null, callee: null, latest_stack: [] })]);
    const { findByTestId, queryByTestId } = renderSection();
    expect((await findByTestId("overview-blocking-finding-0")).textContent).toContain("call site not captured");
    expect(queryByTestId("overview-blocking-finding-0-stack-toggle")).toBeNull();
  });

  it("names the package for a library call site and shows the primitive", async () => {
    serveFindings([
      createBlockingFinding({
        tier: "monkeypatch",
        primitive: "socket.connect",
        callee: null,
        call_site_is_user_code: false,
        detected_in_package: "requests",
        call_site: createFrameRef({ display_path: "requests/api.py", lineno: 10, function: "get" }),
        max_stall_ms: null,
        avg_stall_ms: null,
      }),
    ]);
    const { findByTestId } = renderSection();
    const text = (await findByTestId("overview-blocking-finding-0")).textContent ?? "";
    expect(text).toContain("detected inside requests");
    expect(text).toContain("calls socket.connect");
    expect(text).toContain("at requests/api.py:10 in get");
    expect(text).not.toContain("up to");
  });

  it("warns that older call sites may be missing when the server truncated", async () => {
    serveFindings([createBlockingFinding()], true);
    const { findByTestId } = renderSection();
    expect(await findByTestId("overview-blocking-truncated")).toBeDefined();
  });
});
