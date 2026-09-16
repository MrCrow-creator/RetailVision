import cors from "cors";
import express, { type Express } from "express";
import helmet from "helmet";
import type { Logger } from "pino";
import { pinoHttp } from "pino-http";
import { createLogger } from "./lib/logger.js";
import { errorHandler, notFoundHandler } from "./middleware/errors.js";
import { createHealthRouter } from "./routes/health.routes.js";

interface CreateAppOptions {
  frontendOrigin?: string;
  aiServiceUrl?: string;
  aiHealthTimeoutMs?: number;
  fetchImpl?: typeof fetch;
  logger?: Logger;
}

export function createApp(options: CreateAppOptions = {}): Express {
  const app = express();
  const logger = options.logger ?? createLogger("info");

  app.disable("x-powered-by");
  app.use(pinoHttp({ logger }));
  app.use(helmet());
  app.use(
    cors({
      origin: options.frontendOrigin ?? "http://localhost:5173",
      methods: ["GET"],
    }),
  );
  app.use(express.json({ limit: "1mb" }));

  app.use(
    "/api/v1/health",
    createHealthRouter({
      aiServiceUrl: options.aiServiceUrl ?? "http://127.0.0.1:8000",
      aiHealthTimeoutMs: options.aiHealthTimeoutMs ?? 2000,
      fetchImpl: options.fetchImpl,
    }),
  );

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}
