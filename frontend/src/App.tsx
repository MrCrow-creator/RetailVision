import { useEffect, useState } from "react";
import { ServiceStatus, type ConnectionState } from "./components/ServiceStatus";
import { getBackendHealth } from "./services/api";

const pipeline = [
  { label: "Observe", detail: "Shelf image + query", active: true },
  { label: "Retrieve", detail: "Vector + graph + SQL", active: false },
  { label: "Fuse", detail: "Source-aware evidence", active: false },
  { label: "Explain", detail: "Grounded response", active: false },
];

const futureCapabilities = [
  ["Visual identification", "YOLO, OCR and multimodal candidates", "Milestones 11-13"],
  ["Hybrid retrieval", "Qdrant, Neo4j and PostgreSQL evidence", "Milestone 14"],
  ["Retail reasoning", "Deterministic rules with grounded language", "Milestones 15-16"],
] as const;

function App() {
  const [connection, setConnection] = useState<ConnectionState>({ phase: "checking" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    getBackendHealth(controller.signal)
      .then((health) => setConnection({ phase: "connected", health }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }

        setConnection({
          phase: "error",
          message: error instanceof Error ? error.message : "The health check failed unexpectedly.",
        });
      });

    return () => controller.abort();
  }, [attempt]);

  return (
    <main className="min-h-screen overflow-hidden bg-[#080b0f] text-slate-100">
      <div className="grid-overlay pointer-events-none fixed inset-0 opacity-30" />
      <div className="pointer-events-none fixed left-1/2 top-[-22rem] h-[42rem] w-[42rem] -translate-x-1/2 rounded-full bg-cyan-400/[0.07] blur-[120px]" />

      <div className="relative mx-auto flex min-h-screen max-w-7xl flex-col px-5 py-6 sm:px-8 lg:px-12">
        <header className="flex items-center justify-between border-b border-white/[0.08] pb-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/10 font-mono text-sm font-bold text-cyan-200">
              RV
            </div>
            <div>
              <p className="text-sm font-semibold tracking-wide text-white">RetailVision</p>
              <p className="text-[0.65rem] uppercase tracking-[0.2em] text-white/35">
                Knowledge intelligence
              </p>
            </div>
          </div>
          <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 font-mono text-[0.65rem] uppercase tracking-wider text-white/50">
            Foundation / M01
          </span>
        </header>

        <section className="grid flex-1 items-center gap-14 py-16 lg:grid-cols-[1.25fr_0.75fr] lg:py-20">
          <div>
            <p className="mb-5 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.26em] text-cyan-300/70">
              <span className="h-px w-8 bg-cyan-300/40" />
              Multimodal retail evidence
            </p>
            <h1 className="max-w-4xl text-4xl font-semibold leading-[1.08] tracking-[-0.045em] text-white sm:text-6xl lg:text-[4.25rem]">
              From shelf pixels to
              <span className="text-gradient block">grounded decisions.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-7 text-slate-400 sm:text-lg sm:leading-8">
              A retail intelligence layer designed to connect visual product evidence, semantic
              retrieval, graph relationships, and exact operational records.
            </p>

            <div className="mt-10 grid gap-px overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.08] sm:grid-cols-4">
              {pipeline.map((stage, index) => (
                <div key={stage.label} className="relative bg-[#0c1015] px-4 py-5">
                  <div className="flex items-center justify-between">
                    <span
                      className={`font-mono text-[0.65rem] ${stage.active ? "text-cyan-300" : "text-white/25"}`}
                    >
                      0{index + 1}
                    </span>
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${stage.active ? "bg-cyan-300 shadow-[0_0_12px_#67e8f9]" : "bg-white/15"}`}
                    />
                  </div>
                  <p className="mt-5 text-sm font-semibold text-white/90">{stage.label}</p>
                  <p className="mt-1 text-xs leading-5 text-white/35">{stage.detail}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-4 lg:pl-6">
            <ServiceStatus
              connection={connection}
              onRetry={() => {
                setConnection({ phase: "checking" });
                setAttempt((value) => value + 1);
              }}
            />

            <section className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-5 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white/85">Capability roadmap</h2>
                <span className="text-[0.65rem] uppercase tracking-[0.18em] text-white/30">
                  Not implemented
                </span>
              </div>
              <div className="mt-4 divide-y divide-white/[0.06]">
                {futureCapabilities.map(([name, detail, milestone]) => (
                  <div key={name} className="py-4 first:pt-1 last:pb-1">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-sm font-medium text-white/75">{name}</p>
                        <p className="mt-1 text-xs leading-5 text-white/35">{detail}</p>
                      </div>
                      <span className="shrink-0 rounded-md bg-white/[0.04] px-2 py-1 font-mono text-[0.6rem] text-white/30">
                        {milestone}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </section>

        <footer className="flex flex-col gap-2 border-t border-white/[0.08] pt-5 text-xs text-white/30 sm:flex-row sm:items-center sm:justify-between">
          <p>Implementation/adaptation inspired by mKG-RAG</p>
          <p className="font-mono">React / Express / FastAPI</p>
        </footer>
      </div>
    </main>
  );
}

export default App;
