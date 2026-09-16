import { createApp } from "./app.js";
import { env } from "./config/env.js";
import { createLogger } from "./lib/logger.js";

const logger = createLogger(env.LOG_LEVEL);
const app = createApp({
  frontendOrigin: env.FRONTEND_ORIGIN,
  aiServiceUrl: env.AI_SERVICE_URL,
  aiHealthTimeoutMs: env.AI_HEALTH_TIMEOUT_MS,
  logger,
});

const server = app.listen(env.BACKEND_PORT, env.BACKEND_HOST, () => {
  logger.info(
    {
      host: env.BACKEND_HOST,
      port: env.BACKEND_PORT,
      environment: env.NODE_ENV,
    },
    "RetailVision backend started",
  );
});

let shuttingDown = false;

function shutdown(signal: NodeJS.Signals): void {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  logger.info({ signal }, "Shutting down backend");

  const forceCloseTimer = setTimeout(() => {
    logger.error("Backend did not close within 10 seconds");
    process.exit(1);
  }, 10_000);
  forceCloseTimer.unref();

  server.close((error) => {
    clearTimeout(forceCloseTimer);
    if (error) {
      logger.error({ err: error }, "Backend shutdown failed");
      process.exitCode = 1;
      return;
    }

    logger.info("Backend stopped");
    process.exitCode = 0;
  });
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
