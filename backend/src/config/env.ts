import dotenv from "dotenv";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const rootEnvPath = fileURLToPath(new URL("../../../.env", import.meta.url));
dotenv.config({ path: rootEnvPath, quiet: true });

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  LOG_LEVEL: z.enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"]).default("info"),
  BACKEND_HOST: z.string().min(1).default("127.0.0.1"),
  BACKEND_PORT: z.coerce.number().int().min(1).max(65_535).default(4000),
  FRONTEND_ORIGIN: z.url().default("http://localhost:5173"),
  AI_SERVICE_URL: z.url().default("http://127.0.0.1:8000"),
  AI_HEALTH_TIMEOUT_MS: z.coerce.number().int().min(100).max(30_000).default(2000),
});

const result = envSchema.safeParse(process.env);

if (!result.success) {
  const details = result.error.issues
    .map((issue) => `${issue.path.join(".") || "environment"}: ${issue.message}`)
    .join("; ");
  throw new Error(`Invalid backend environment configuration: ${details}`);
}

export const env = result.data;
