import { z } from "zod";

const aiHealthSchema = z
  .object({
    status: z.literal("ok"),
    service: z.literal("ai-service"),
    version: z.string().min(1),
    timestamp: z.iso.datetime({ offset: true }),
  })
  .passthrough();

export type AiHealth = z.infer<typeof aiHealthSchema>;

interface CheckAiHealthOptions {
  baseUrl: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
}

export async function checkAiHealth({
  baseUrl,
  timeoutMs,
  fetchImpl = fetch,
}: CheckAiHealthOptions): Promise<AiHealth> {
  const endpoint = new URL("/health", baseUrl);
  const response = await fetchImpl(endpoint, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  });

  if (!response.ok) {
    throw new Error(`AI service health check returned status ${response.status}`);
  }

  return aiHealthSchema.parse(await response.json());
}
