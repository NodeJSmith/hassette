/**
 * Ambient type declarations for third-party globals used by the
 * Hassette web UI scripts.  These are intentionally minimal — only
 * the APIs actually referenced in the JS files are declared.
 */

// ---------------------------------------------------------------------------
// Alpine.js
// ---------------------------------------------------------------------------

interface AlpineStatic {
  /**
   * Register a reusable Alpine component.
   *
   * @param name  - Component name referenced by `x-data`.
   * @param factory - Factory function returning the component definition.
   */
  data(name: string, factory: (...args: any[]) => Record<string, any>): void;

  /**
   * Register or retrieve a global Alpine store.
   *
   * @param name  - Store name.
   * @param value - Store definition (omit to retrieve).
   */
  store(name: string, value?: Record<string, any>): any;
}

declare var Alpine: AlpineStatic;

// ---------------------------------------------------------------------------
// htmx
// ---------------------------------------------------------------------------

interface HtmxAjaxOptions {
  target?: string | Element;
  swap?: string;
}

interface HtmxStatic {
  /**
   * Perform an HTMX-style AJAX request.
   *
   * @param method  - HTTP method.
   * @param url     - Request URL.
   * @param options - Target element and swap strategy.
   */
  ajax(method: string, url: string, options?: HtmxAjaxOptions): void;
}

declare var htmx: HtmxStatic;
