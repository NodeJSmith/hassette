import { fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { BlockingFinding, BlockingFindingsData } from "../../api/endpoints";
import { createBlockingFinding, createFrameRef } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import { BlockingFindingsSection, type BlockingScope } from "./blocking-findings";

const APP_KEY = "car_climate";

function serveFindings(findings: BlockingFinding[], truncated = false) {
  const seen: URL[] = [];
  server.use(
    http.get("/api/telemetry/app/:app_key/blocking", ({ request }) => {
      seen.push(new URL(request.url));
      return HttpResponse.json<BlockingFindingsData>({ findings, truncated });
    }),
  );
  return seen;
}

/** Renders instance 2's section, linking with `linkInstance`, unless `acrossInstances` is set. */
function renderSection({
  linkInstance,
  acrossInstances = false,
}: { linkInstance?: number; acrossInstances?: boolean } = {}) {
  const scope: BlockingScope = acrossInstances ? { kind: "app" } : { kind: "instance", index: 2, linkInstance };
  return renderWithAppState(<BlockingFindingsSection appKey={APP_KEY} scope={scope} />, {
    storeOverrides: { uptimeSeconds: 120 },
  });
}

describe("BlockingFindingsSection", () => {
  it("renders nothing when the app has no findings", async () => {
    const seen = serveFindings([]);
    const { queryByTestId } = renderSection();
    await waitFor(() => expect(seen.length).toBe(1));
    expect(queryByTestId("overview-blocking-findings")).toBeNull();
  });

  it("renders nothing when the fetch fails", async () => {
    let requests = 0;
    server.use(
      http.get("/api/telemetry/app/:app_key/blocking", () => {
        requests += 1;
        return HttpResponse.json(null, { status: 503 });
      }),
    );
    const { queryByTestId } = renderSection();
    await waitFor(() => expect(requests).toBeGreaterThan(0));
    expect(queryByTestId("overview-blocking-findings")).toBeNull();
  });

  it("requests the resolved instance", async () => {
    const seen = serveFindings([]);
    renderSection();
    await waitFor(() => expect(seen[0]?.searchParams.get("instance_index")).toBe("2"));
  });

  it("shows the call site, what it calls into, the handlers, and the stats", async () => {
    serveFindings([createBlockingFinding({ app_key: APP_KEY })]);
    const { findByTestId, getByRole } = renderSection({ linkInstance: 2 });
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

  it("across instances, requests every instance and names each finding's instances", async () => {
    const seen = serveFindings([
      createBlockingFinding({
        handlers: [
          { kind: "listener", id: 3, name: "refresh", handler_method: "refresh", instance_index: 0 },
          { kind: "listener", id: 8, name: "refresh", handler_method: "refresh", instance_index: 1 },
        ],
        instances: [
          { index: 0, name: "bedroom" },
          { index: 1, name: "office" },
        ],
      }),
    ]);
    const { findByTestId, getByTestId, getAllByRole } = renderSection({ acrossInstances: true });
    const entry = await findByTestId("overview-blocking-finding-0");

    expect(seen[0]?.searchParams.has("instance_index")).toBe(false);
    expect(getByTestId("overview-blocking-findings").textContent).toContain("blocking calls · all instances");
    expect(getByTestId("overview-blocking-finding-0-instances").textContent).toBe("on bedroom, office");
    expect(entry.textContent).toContain("refresh (bedroom), refresh (office)");
    const links = getAllByRole("link", { name: "refresh" }) as HTMLAnchorElement[];
    expect(links.map((a) => new URL(a.href).search)).toEqual(["?instance=0", "?instance=1"]);
  });

  it("on one instance's page, doesn't tag instances", async () => {
    serveFindings([createBlockingFinding()]);
    const { findByTestId, queryByTestId } = renderSection({ linkInstance: 2 });
    await findByTestId("overview-blocking-finding-0");
    expect(queryByTestId("overview-blocking-finding-0-instances")).toBeNull();
  });

  it("warns that older call sites are omitted when the server truncated", async () => {
    serveFindings([createBlockingFinding()], true);
    const { findByTestId } = renderSection();
    expect(await findByTestId("overview-blocking-truncated")).toBeDefined();
  });
});
