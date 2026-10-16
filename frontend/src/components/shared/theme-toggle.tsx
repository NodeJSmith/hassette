import { Button } from "@/components/ui/button";

import { useAppStore } from "../../state/store";
import { IconMoon, IconSun } from "./icons";

/** Dark/light switch. Lives in the sidebar footer; the icon previews the theme you'd get. */
export function ThemeToggle() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const nextTheme = theme === "dark" ? "light" : "dark";

  const toggleTheme = () => {
    setTheme(nextTheme);
  };

  return (
    <Button
      variant="subtle"
      size="icon-sm"
      touch
      data-testid="theme-toggle"
      aria-label={`Switch to ${nextTheme} mode`}
      onClick={toggleTheme}
    >
      {nextTheme === "light" ? <IconSun /> : <IconMoon />}
    </Button>
  );
}
