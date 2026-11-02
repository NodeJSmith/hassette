import { fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import type { BlockingFinding, BlockingFindingsData } from "../../api/endpoints";
import { createBlockingFinding, createFrameRef } from "../../test/blocking-fixtures";
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

/** Renders the `office` instance's section, linking with `linkInstance`, unless `acrossInstances` is set. */
function renderSection({
  linkInstance,
  acrossInstances = false,
}: { linkInstance?: string; acrossInstances?: boolean } = {}) {
  const scope: BlockingScope = acrossInstances ? { kind: "app" } : { kind: "instance", name: "office", linkInstance };
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

  it("requests the scope's instance by name", async () => {
    const seen = serveFindings([]);
    renderSection();
    await waitFor(() => expect(seen[0]?.searchParams.get("instance_name")).toBe("office"));
  });

  it("shows the call site, what it calls into, the handlers, and the stats", async () => {
    serveFindings([createBlockingFinding({ app_key: APP_KEY })]);
    const { findByTestId, getByRole } = renderSection({ linkInstance: "office" });
    const entry = await findByTestId("overview-blocking-finding-0");

    expect(entry.textContent).toContain("calendar_service.py:98 in get_calendar_events");
    expect(entry.textContent).toContain("calls gcsa/events.py get_events");
    expect(entry.textContent).toContain("9 events · up to 534.0ms · avg 300.0ms · last seen");
    const handlerLink = getByRole("link", { name: "scan_and_schedule" }) as HTMLAnchorElement;
    expect(handlerLink.href).toContain(`/apps/${APP_KEY}/handlers/job/7?instance=office`);
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
          { kind: "listener", id: 3, name: "refresh", handler_method: "refresh", instance_name: "bedroom" },
          { kind: "listener", id: 8, name: "refresh", handler_method: "refresh", instance_name: "office" },
        ],
        instances: [{ name: "bedroom" }, { name: "office" }],
      }),
    ]);
    const { findByTestId, getByTestId, getAllByRole } = renderSection({ acrossInstances: true });
    const entry = await findByTestId("overview-blocking-finding-0");

    expect(seen[0]?.searchParams.has("instance_name")).toBe(false);
    expect(getByTestId("overview-blocking-findings").textContent).toContain("blocking calls · all instances");
    expect(getByTestId("overview-blocking-finding-0-instances").textContent).toBe("on bedroom, office");
    expect(entry.textContent).toContain("refresh (bedroom), refresh (office)");
    const links = getAllByRole("link", { name: "refresh" }) as HTMLAnchorElement[];
    expect(links.map((a) => new URL(a.href).search)).toEqual(["?instance=bedroom", "?instance=office"]);
  });

  it("labels a ref with no stored name 'unnamed instance' and links its handler with no instance", async () => {
    serveFindings([
      createBlockingFinding({
        handlers: [{ kind: "listener", id: 3, name: "refresh", handler_method: "refresh", instance_name: null }],
        instances: [{ name: "office" }, { name: null }],
      }),
    ]);
    const { findByTestId, getByTestId, getByRole } = renderSection({ acrossInstances: true });
    const entry = await findByTestId("overview-blocking-finding-0");

    expect(getByTestId("overview-blocking-finding-0-instances").textContent).toBe("on office, unnamed instance");
    expect(entry.textContent).toContain("refresh (unnamed instance)");
    const link = getByRole("link", { name: "refresh" }) as HTMLAnchorElement;
    expect(new URL(link.href).search).toBe("");
  });

  it("on one instance's page, doesn't tag instances", async () => {
    serveFindings([createBlockingFinding()]);
    const { findByTestId, queryByTestId } = renderSection({ linkInstance: "office" });
    await findByTestId("overview-blocking-finding-0");
    expect(queryByTestId("overview-blocking-finding-0-instances")).toBeNull();
  });

  it("lists both call sites when two functions share one file and line", async () => {
    const at = (fn: string) => createFrameRef({ filename: "/apps/calendar_service.py", lineno: 98, function: fn });
    serveFindings([
      createBlockingFinding({ call_site: at("new_fetch") }),
      createBlockingFinding({ call_site: at("old_fetch") }),
    ]);
    // React still renders rows that share a key, so the duplicate-key warning is the observable failure.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { findByTestId } = renderSection();

    expect((await findByTestId("overview-blocking-finding-0")).textContent).toContain("in new_fetch");
    expect((await findByTestId("overview-blocking-finding-1")).textContent).toContain("in old_fetch");
    expect(errorSpy.mock.calls.flat().join(" ")).not.toContain("same key");
    errorSpy.mockRestore();
  });

  it("warns that older call sites are omitted when the server truncated", async () => {
    serveFindings([createBlockingFinding()], true);
    const { findByTestId } = renderSection();
    expect(await findByTestId("overview-blocking-truncated")).toBeDefined();
  });
});
