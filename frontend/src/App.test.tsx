import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a successful backend connection from the real health contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "ok",
        service: "backend",
        version: "0.1.0",
        timestamp: "2026-09-16T12:00:00.000Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Backend connected")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/health",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("labels future capabilities as not implemented", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Backend is offline")));

    render(<App />);

    expect(await screen.findByText("Backend unavailable")).toBeInTheDocument();
    expect(screen.getByText("Not implemented")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
