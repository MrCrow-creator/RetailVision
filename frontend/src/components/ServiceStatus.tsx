import type { HealthResponse } from "../services/api";

export type ConnectionState =
  | { phase: "checking" }
  | { phase: "connected"; health: HealthResponse }
  | { phase: "error"; message: string };

interface ServiceStatusProps {
  connection: ConnectionState;
  onRetry: () => void;
}

const stateStyles = {
  checking: "border-amber-300/20 bg-amber-300/5 text-amber-200",
  connected: "border-emerald-300/20 bg-emerald-300/5 text-emerald-200",
  error: "border-rose-300/20 bg-rose-300/5 text-rose-200",
} as const;

export function ServiceStatus({ connection, onRetry }: ServiceStatusProps) {
  const title =
    connection.phase === "checking"
      ? "Checking backend"
      : connection.phase === "connected"
        ? "Backend connected"
        : "Backend unavailable";

  return (
    <section
      aria-live="polite"
      className={`relative overflow-hidden rounded-2xl border p-5 ${stateStyles[connection.phase]}`}
    >
      <div className="absolute -right-8 -top-8 h-24 w-24 rounded-full bg-current opacity-[0.04] blur-2xl" />
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-current/60">
            Live service check
          </p>
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2.5 w-2.5">
              {connection.phase === "checking" && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
              )}
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-current" />
            </span>
            <h2 className="text-lg font-semibold text-white">{title}</h2>
          </div>
        </div>

        {connection.phase === "error" && (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-lg border border-current/20 px-3 py-1.5 text-xs font-semibold text-current transition hover:bg-current/10"
          >
            Retry
          </button>
        )}
      </div>

      {connection.phase === "connected" && (
        <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-xl bg-black/20 px-3 py-2.5">
            <dt className="text-white/40">Service</dt>
            <dd className="mt-0.5 font-mono text-xs text-white/90">{connection.health.service}</dd>
          </div>
          <div className="rounded-xl bg-black/20 px-3 py-2.5">
            <dt className="text-white/40">Version</dt>
            <dd className="mt-0.5 font-mono text-xs text-white/90">{connection.health.version}</dd>
          </div>
        </dl>
      )}

      {connection.phase === "error" && (
        <p className="mt-4 text-sm leading-6 text-white/60">{connection.message}</p>
      )}

      <p className="mt-4 font-mono text-[0.68rem] text-white/35">GET /api/v1/health</p>
    </section>
  );
}
