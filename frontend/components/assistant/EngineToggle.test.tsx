import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ENGINE_TOGGLE_ENABLED is read from process.env at module-evaluation time
// (a Next.js build-time inline, not a runtime read), so testing both the
// on/off states requires vi.resetModules() + a fresh dynamic import per
// case rather than a single top-level import.
async function loadEngineToggle() {
  vi.resetModules();
  return import("@/components/assistant/EngineToggle");
}

describe("EngineToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders nothing when the build flag is not set", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE", "false");
    const { EngineToggle } = await loadEngineToggle();

    const { container } = render(<EngineToggle />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders the toggle when the build flag is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE", "true");
    const { EngineToggle } = await loadEngineToggle();

    render(<EngineToggle />);

    expect(screen.getByRole("group", { name: "Uni engine" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "V1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "V2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "V3" })).toBeInTheDocument();
  });

  it("supports switching to V3", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE", "true");
    const { EngineToggle, getEnginePreference } = await loadEngineToggle();

    render(<EngineToggle />);

    fireEvent.click(screen.getByRole("button", { name: "V3" }));

    expect(getEnginePreference()).toBe("v3");
    expect(screen.getByRole("button", { name: "V3" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(window.localStorage.getItem("uni-engine")).toBe("v3");
  });

  it("defaults to V1 and persists a click to localStorage", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE", "true");
    const { EngineToggle, getEnginePreference } = await loadEngineToggle();

    render(<EngineToggle />);

    expect(getEnginePreference()).toBe("v1");
    expect(screen.getByRole("button", { name: "V1" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );

    fireEvent.click(screen.getByRole("button", { name: "V2" }));

    expect(getEnginePreference()).toBe("v2");
    expect(screen.getByRole("button", { name: "V2" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(window.localStorage.getItem("uni-engine")).toBe("v2");
  });

  it("getEnginePreference reads a previously stored preference", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE", "true");
    window.localStorage.setItem("uni-engine", "v2");
    const { getEnginePreference } = await loadEngineToggle();

    expect(getEnginePreference()).toBe("v2");
  });

  it("setEnginePreference is a no-op-safe way to set the preference directly", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE", "true");
    const { setEnginePreference, getEnginePreference } = await loadEngineToggle();

    setEnginePreference("v2");

    expect(getEnginePreference()).toBe("v2");
  });
});
