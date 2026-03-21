/**
 * Fixed-capacity ring buffer. Overwrites the oldest entry when full.
 * Used for the log stream where we keep the most recent N entries.
 */
export class RingBuffer<T> {
  private readonly items: T[];
  private head = 0;
  private count = 0;

  constructor(readonly capacity: number) {
    this.items = new Array<T>(capacity);
  }

  push(item: T): void {
    this.items[(this.head + this.count) % this.capacity] = item;
    if (this.count < this.capacity) {
      this.count++;
    } else {
      this.head = (this.head + 1) % this.capacity;
    }
  }

  toArray(): T[] {
    const result: T[] = new Array(this.count);
    for (let i = 0; i < this.count; i++) {
      result[i] = this.items[(this.head + i) % this.capacity];
    }
    return result;
  }

  get length(): number {
    return this.count;
  }

  clear(): void {
    this.head = 0;
    this.count = 0;
  }
}
