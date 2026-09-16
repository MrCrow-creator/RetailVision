import pino, { type DestinationStream, type Logger } from "pino";

export function createLogger(level: string, destination?: DestinationStream): Logger {
  return pino(
    {
      level,
      base: {
        service: "backend",
      },
      redact: {
        paths: [
          "req.headers.authorization",
          "req.headers.cookie",
          'req.headers["x-api-key"]',
          'res.headers["set-cookie"]',
        ],
        censor: "[Redacted]",
      },
    },
    destination,
  );
}
