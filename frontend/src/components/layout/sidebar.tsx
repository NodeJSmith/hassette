import { useLocation } from "wouter";

const NAV_ITEMS = [
  { path: "/", icon: "⊞", label: "Dashboard" },
  { path: "/apps", icon: "⬡", label: "Apps" },
  { path: "/logs", icon: "≡", label: "Logs" },
] as const;

export function Sidebar() {
  const [location] = useLocation();

  return (
    <aside class="ht-sidebar">
      <div class="ht-sidebar-brand">
        <a href="/" class="ht-brand-link">
          <span class="ht-pulse-dot" />
        </a>
      </div>
      <nav class="ht-sidebar-nav">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.path === "/"
              ? location === "/"
              : location.startsWith(item.path);
          return (
            <a
              key={item.path}
              href={item.path}
              class={`ht-sidebar-link${isActive ? " active" : ""}`}
              title={item.label}
            >
              <span class="ht-sidebar-icon">{item.icon}</span>
            </a>
          );
        })}
      </nav>
    </aside>
  );
}
