import "@testing-library/jest-dom/vitest";

// Node 22+ ships an experimental native `localStorage` global that is
// disabled by default (it throws/returns undefined without
// --localstorage-file). Because it already exists as a global, vitest's
// jsdom environment setup skips overriding it with jsdom's working
// implementation, leaving the broken native stub in place. Replace it here
// with a minimal in-memory polyfill so localStorage behaves as expected in
// tests, on both `globalThis` and `window`.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length() {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const memoryStorage = new MemoryStorage();

for (const target of [globalThis, window]) {
  Object.defineProperty(target, "localStorage", {
    value: memoryStorage,
    configurable: true,
    writable: true,
  });
}
