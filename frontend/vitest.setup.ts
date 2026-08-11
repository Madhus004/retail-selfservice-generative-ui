import "@testing-library/jest-dom/vitest";

// jsdom does not implement scrollIntoView; components that call it (e.g. to
// keep the assistant transcript scrolled to the latest turn) need a no-op stub.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
