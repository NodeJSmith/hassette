import { useEffect } from "preact/hooks";

const SUFFIX = " - Hassette";

export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title + SUFFIX;
    return () => {
      document.title = "Hassette";
    };
  }, [title]);
}
