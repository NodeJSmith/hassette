import { useEffect } from "preact/hooks";

const APP_NAME = "Hassette";
const SUFFIX = ` - ${APP_NAME}`;

export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title + SUFFIX;
    return () => {
      document.title = APP_NAME;
    };
  }, [title]);
}
