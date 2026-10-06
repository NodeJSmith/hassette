/** Current sort of a table: the column key and its direction. */
export interface SortState<K extends string = string> {
  key: K;
  dir: "asc" | "desc";
}
