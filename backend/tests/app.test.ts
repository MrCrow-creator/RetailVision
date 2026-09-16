import pino from "pino";
import request from "supertest";
import { describe, expect, it, vi } from "vitest";
import { createApp } from "../src/app.js";

const silentLogger = pino({ level: "silent" });

describe("health routes", () => {
  it("returns the backend health contract", async () => {
    const response = await request(createApp({ logger: silentLogger })).get("/api/v1/health");

    expect(response.status).toBe(200);
    expect(response.headers["cache-control"]).toBe("no-store");
    expect(response.body).toMatchObject({
      status: "ok",
      service: "backend",
      version: "0.1.0",
    });
    expect(Date.parse(response.body.timestamp)).not.toBeNaN();
  });

  it("reports a healthy FastAPI dependency", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ok",
          service: "ai-service",
          version: "0.1.0",
          timestamp: "2026-09-16T12:00:00.000Z",
          capabilities: { vision: "not_implemented" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const app = createApp({ logger: silentLogger, fetchImpl });

    const response = await request(app).get("/api/v1/health/ai");

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      status: "ok",
      service: "ai-service",
      upstream: {
        status: "ok",
        service: "ai-service",
        capabilities: { vision: "not_implemented" },
      },
    });
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("uses a stable 503 response when FastAPI is unavailable", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("connection refused"));
    const app = createApp({ logger: silentLogger, fetchImpl });

    const response = await request(app).get("/api/v1/health/ai");

    expect(response.status).toBe(503);
    expect(response.body).toEqual({
      status: "degraded",
      service: "ai-service",
      error: {
        code: "AI_SERVICE_UNAVAILABLE",
        message: "The AI service did not return a valid healthy response.",
      },
    });
  });

  it("returns a structured 404 for unknown routes", async () => {
    const response = await request(createApp({ logger: silentLogger })).get("/unknown");

    expect(response.status).toBe(404);
    expect(response.body.error.code).toBe("NOT_FOUND");
  });
});
