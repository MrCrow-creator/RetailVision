const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");
const HEALTH_TIMEOUT_MS = 5000;

export interface HealthResponse {
  status: "ok";
  service: "backend";
  version: string;
  timestamp: string;
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    candidate.status === "ok" &&
    candidate.service === "backend" &&
    typeof candidate.version === "string" &&
    typeof candidate.timestamp === "string"
  );
}

export async function getBackendHealth(
  signal?: AbortSignal,
  timeoutMs = HEALTH_TIMEOUT_MS,
): Promise<HealthResponse> {
  const requestController = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => requestController.abort(signal?.reason);

  if (signal?.aborted) {
    abortFromCaller();
  } else {
    signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  const timeout = setTimeout(() => {
    timedOut = true;
    requestController.abort();
  }, timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      headers: { Accept: "application/json" },
      signal: requestController.signal,
    });

    if (!response.ok) {
      throw new Error(`Backend health check failed with status ${response.status}`);
    }

    const payload: unknown = await response.json();
    if (!isHealthResponse(payload)) {
      throw new Error("Backend returned an invalid health response");
    }

    return payload;
  } catch (error) {
    if (timedOut) {
      throw new Error(`Backend health check timed out after ${timeoutMs}ms`, { cause: error });
    }

    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}
