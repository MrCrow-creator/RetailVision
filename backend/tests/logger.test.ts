import { Writable } from "node:stream";
import { describe, expect, it } from "vitest";
import { createLogger } from "../src/lib/logger.js";

describe("logger", () => {
  it("redacts credentials from serialized request headers", () => {
    let output = "";
    const destination = new Writable({
      write(chunk, _encoding, callback) {
        output += chunk.toString();
        callback();
      },
    });
    const logger = createLogger("info", destination);

    logger.info({
      req: {
        headers: {
          accept: "application/json",
          authorization: "Bearer private-token",
          cookie: "session=private-cookie",
          "x-api-key": "private-api-key",
        },
      },
    });

    const record = JSON.parse(output) as {
      req: { headers: Record<string, string> };
    };
    expect(record.req.headers).toMatchObject({
      accept: "application/json",
      authorization: "[Redacted]",
      cookie: "[Redacted]",
      "x-api-key": "[Redacted]",
    });
    expect(output).not.toContain("private-token");
    expect(output).not.toContain("private-cookie");
    expect(output).not.toContain("private-api-key");
  });
});
