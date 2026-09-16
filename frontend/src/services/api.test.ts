import { afterEach, describe, expect, it, vi } from "vitest";
import { getBackendHealth } from "./api";

describe("getBackendHealth", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("aborts a stalled request after the configured timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Request aborted", "AbortError"));
          });
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const request = expect(getBackendHealth(undefined, 50)).rejects.toThrow(
      "Backend health check timed out after 50ms",
    );
    await vi.advanceTimersByTimeAsync(50);

    await request;
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
