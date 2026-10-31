// Page helpers for docs/screenshots.yml entries, exposed as window.docShot.
// capture_screenshots.py prepends this file to every entry's javascript.
//
// Home Assistant renders inside nested shadow roots, which document.querySelector and
// shot-scraper's wait_for cannot see into. Every helper waits for its target with a bounded
// poll, so entries need no fixed `wait`.
window.docShot = (() => {
  const TIMEOUT_MS = 20000;
  const POLL_MS = 100;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (text) => (text || "").replace(/\s+/g, " ").trim();

  function* walk(root) {
    for (const el of root.querySelectorAll("*")) {
      yield el;
      if (el.shadowRoot) yield* walk(el.shadowRoot);
    }
  }

  // Target: {tag, text?, within?}. `text` matches the start of the element's normalized text;
  // `within` limits the search to the shadow tree of the named host element. The first visible
  // match in document order wins.
  function find({ tag, text, within }) {
    let root = document;
    if (within) {
      root = [...walk(document)].find((el) => el.localName === within)?.shadowRoot;
      if (!root) return null;
    }
    for (const el of walk(root)) {
      if (el.localName !== tag) continue;
      if (text !== undefined && !normalize(el.textContent).startsWith(text)) continue;
      if (el.getBoundingClientRect().width > 0) return el;
    }
    return null;
  }

  async function waitFor(target, isReady = () => true) {
    const deadline = Date.now() + TIMEOUT_MS;
    while (Date.now() < deadline) {
      const el = find(target);
      if (el && isReady(el)) return el;
      await sleep(POLL_MS);
    }
    throw new Error(`docShot: no ready element for ${JSON.stringify(target)} within ${TIMEOUT_MS}ms`);
  }

  // Finishes running animations (shadow trees included, unlike ANIMATION_DISABLE_JS's stylesheet;
  // infinite ones like spinners can't finish, so they're skipped), then waits until two consecutive polls measure the same position.
  async function settle(el) {
    let previous = null;
    const deadline = Date.now() + TIMEOUT_MS;
    while (Date.now() < deadline) {
      for (const animation of document.getAnimations()) {
        if (Number.isFinite(animation.effect?.getComputedTiming().endTime)) animation.finish();
      }
      const current = JSON.stringify(el.getBoundingClientRect());
      if (current === previous) return;
      previous = current;
      await sleep(POLL_MS);
    }
    throw new Error(`docShot: <${el.localName}> did not stop moving within ${TIMEOUT_MS}ms`);
  }

  async function click(target) {
    const el = await waitFor(target, (candidate) => !candidate.disabled);
    await settle(el);
    el.click();
  }

  async function fill(target, value) {
    const el = await waitFor(target);
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  }

  // The overlay is a popover because the top layer is the only thing that paints above an open
  // modal <dialog>. It works the same way for a target on the page and one inside a dialog.
  async function circle(target) {
    const el = await waitFor(target);
    el.scrollIntoView({ block: "center" });
    await settle(el);
    const rect = el.getBoundingClientRect();
    const paddingX = 14;
    const paddingY = 8;
    const overlay = document.createElement("div");
    overlay.popover = "manual";
    overlay.style.cssText = `
      position: fixed; inset: auto; margin: 0; padding: 0; overflow: visible;
      left: ${rect.left - paddingX}px; top: ${rect.top - paddingY}px;
      width: ${rect.width + 2 * paddingX}px; height: ${rect.height + 2 * paddingY}px;
      box-sizing: border-box; background: transparent; pointer-events: none;
      border: 3px solid #1a8a1a; border-radius: 50%; box-shadow: 1px 2px 4px rgb(0 0 0 / 35%);
    `;
    document.body.appendChild(overlay);
    overlay.showPopover();
  }

  return { click, fill, circle };
})();
