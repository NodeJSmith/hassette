import { Link, useLocation } from "wouter";
import { IconBoxes, IconDashboard, IconHistory, IconScrollText } from "../shared/icons";

const NAV_ITEMS = [
  {
    path: "/",
    label: "Dashboard",
    testId: "nav-dashboard",
    icon: <IconDashboard />,
  },
  {
    path: "/apps",
    label: "Apps",
    testId: "nav-apps",
    icon: <IconBoxes />,
  },
  {
    path: "/logs",
    label: "Logs",
    testId: "nav-logs",
    icon: <IconScrollText />,
  },
  {
    path: "/sessions",
    label: "Sessions",
    testId: "nav-sessions",
    icon: <IconHistory />,
  },
] as const;

export function Sidebar() {
  const [location] = useLocation();

  return (
    <aside class="ht-sidebar">
      <div class="ht-sidebar-brand">
        <Link href="/" class="ht-brand-link" aria-label="Hassette home">
          <img src="/hassette-logo.png" alt="Hassette" class="ht-sidebar__logo" />
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
