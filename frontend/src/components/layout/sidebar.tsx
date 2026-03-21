import { Link, useLocation } from "wouter";

const NAV_ITEMS = [
  {
    path: "/",
    label: "Dashboard",
    testId: "nav-dashboard",
    // Lucide: layout-dashboard
    icon: (
      <svg viewBox="0 0 24 24">
        <rect width="7" height="9" x="3" y="3" rx="1" />
        <rect width="7" height="5" x="14" y="3" rx="1" />
        <rect width="7" height="9" x="14" y="12" rx="1" />
        <rect width="7" height="5" x="3" y="16" rx="1" />
      </svg>
    ),
  },
  {
    path: "/apps",
    label: "Apps",
    testId: "nav-apps",
    // Lucide: boxes
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l3 1.8a2 2 0 0 0 2.06 0L12 19v-5.5l-5-3-4.03 2.42Z" />
        <path d="m7 16.5-4.74-2.85" />
        <path d="m7 16.5 5-3" />
        <path d="M7 16.5v5.17" />
        <path d="M12 13.5V19l3.97 2.38a2 2 0 0 0 2.06 0l3-1.8a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L17 10.5l-5 3Z" />
        <path d="m17 16.5-5-3" />
        <path d="m17 16.5 4.74-2.85" />
        <path d="M17 16.5v5.17" />
        <path d="M7.97 4.42A2 2 0 0 0 7 6.13v4.37l5 3 5-3V6.13a2 2 0 0 0-.97-1.71l-3-1.8a2 2 0 0 0-2.06 0l-3 1.8Z" />
        <path d="M12 8 7.26 5.15" />
        <path d="m12 8 4.74-2.85" />
        <path d="M12 13.5V8" />
      </svg>
    ),
  },
  {
    path: "/logs",
    label: "Logs",
    testId: "nav-logs",
    // Lucide: scroll-text
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M15 12h-5" />
        <path d="M15 8h-5" />
        <path d="M19 17V5a2 2 0 0 0-2-2H4" />
        <path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2" />
      </svg>
    ),
  },
] as const;

export function Sidebar() {
  const [location] = useLocation();

  return (
    <aside class="ht-sidebar">
      <div class="ht-sidebar-brand">
        <Link href="/" class="ht-brand-link" aria-label="Hassette home">
          <img src="/hassette-logo.png" alt="Hassette" style={{ height: "24px", width: "auto" }} />
        </Link>
      </div>
      <nav aria-label="Main navigation">
        <ul class="ht-nav-list">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.path === "/"
                ? location === "/"
                : location.startsWith(item.path);
            return (
              <li key={item.path}>
                <Link
                  href={item.path}
                  class={`ht-nav-item${isActive ? " is-active" : ""}`}
                  data-testid={item.testId}
                  aria-label={item.label}
                >
                  {item.icon}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}
