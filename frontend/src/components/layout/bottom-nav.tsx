import { Link, useLocation } from "wouter";
import { IconBoxes, IconDashboard, IconHistory, IconScrollText } from "../shared/icons";

const NAV_ITEMS = [
  {
    path: "/",
    label: "Dashboard",
    testId: "nav-dashboard-mobile",
    icon: <IconDashboard />,
  },
  {
    path: "/apps",
    label: "Apps",
    testId: "nav-apps-mobile",
    icon: <IconBoxes />,
  },
  {
    path: "/logs",
    label: "Logs",
    testId: "nav-logs-mobile",
    icon: <IconScrollText />,
  },
  {
    path: "/sessions",
    label: "Sessions",
    testId: "nav-sessions-mobile",
    icon: <IconHistory />,
  },
] as const;

export function BottomNav() {
  const [location] = useLocation();

  return (
    <nav class="ht-bottom-nav" aria-label="Mobile navigation">
      {NAV_ITEMS.map((item) => {
        const isActive =
          item.path === "/"
            ? location === "/"
            : location.startsWith(item.path);
        return (
          <Link
            key={item.path}
            href={item.path}
            class={`ht-bottom-nav__item${isActive ? " is-active" : ""}`}
            data-testid={item.testId}
            aria-label={item.label}
            aria-current={isActive ? "page" : undefined}
          >
            {item.icon}
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
