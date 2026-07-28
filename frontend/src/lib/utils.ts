import { twMerge } from "tailwind-merge";

type ClassDictionary = Record<string, boolean | null | undefined>;
type ClassArray = ClassValue[];
type ClassValue = string | number | boolean | null | undefined | ClassDictionary | ClassArray;

function flattenClassValue(value: ClassValue): string[] {
  if (!value) {
    return [];
  }
  if (typeof value === "string" || typeof value === "number") {
    return [String(value)];
  }
  if (Array.isArray(value)) {
    return value.flatMap(flattenClassValue);
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .filter(([, enabled]) => enabled)
      .map(([className]) => className);
  }
  return [];
}

export function cn(...inputs: ClassValue[]) {
  return twMerge(flattenClassValue(inputs).join(" "));
}
