import { Router } from "express";
import { checkAiHealth } from "../services/ai-health.service.js";

const SERVICE_VERSION = "0.1.0";

interface HealthRouterOptions {
  aiServiceUrl: string;
  aiHealthTimeoutMs: number;
  fetchImpl?: typeof fetch;
}

export function createHealthRouter(options: HealthRouterOptions): Router {
  const router = Router();

  router.get("/", (_request, response) => {
    response.setHeader("Cache-Control", "no-store");
    response.status(200).json({
      status: "ok",
      service: "backend",
      version: SERVICE_VERSION,
      timestamp: new Date().toISOString(),
    });
  });

  router.get("/ai", async (request, response) => {
    response.setHeader("Cache-Control", "no-store");

    try {
      const upstream = await checkAiHealth({
        baseUrl: options.aiServiceUrl,
        timeoutMs: options.aiHealthTimeoutMs,
        fetchImpl: options.fetchImpl,
      });

      response.status(200).json({
        status: "ok",
        service: "ai-service",
        upstream,
      });
    } catch (error) {
      request.log.warn({ err: error }, "AI service health check failed");
      response.status(503).json({
        status: "degraded",
        service: "ai-service",
        error: {
          code: "AI_SERVICE_UNAVAILABLE",
          message: "The AI service did not return a valid healthy response.",
        },
      });
    }
  });

  return router;
}
