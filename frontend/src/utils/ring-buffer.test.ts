import { describe, expect, it } from "vitest";
import { RingBuffer } from "./ring-buffer";

describe("RingBuffer", () => {
  it("push and toArray preserves order", () => {
    const buf = new RingBuffer<number>(5);
    buf.push(1);
    buf.push(2);
    buf.push(3);
    expect(buf.toArray()).toEqual([1, 2, 3]);
    expect(buf.length).toBe(3);
  });

  it("wraps when capacity exceeded, dropping oldest", () => {
    const buf = new RingBuffer<string>(3);
    buf.push("a");
    buf.push("b");
    buf.push("c");
    buf.push("d"); // drops "a"
    expect(buf.toArray()).toEqual(["b", "c", "d"]);
    expect(buf.length).toBe(3);
  });

  it("wraps multiple times correctly", () => {
    const buf = new RingBuffer<number>(2);
    buf.push(1);
    buf.push(2);
    buf.push(3);
    buf.push(4);
    buf.push(5);
    expect(buf.toArray()).toEqual([4, 5]);
  });

  it("clear resets buffer", () => {
    const buf = new RingBuffer<number>(5);
    buf.push(1);
    buf.push(2);
    buf.clear();
    expect(buf.length).toBe(0);
    expect(buf.toArray()).toEqual([]);
  });
});
