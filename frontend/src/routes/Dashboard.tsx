import { useQuery } from "@tanstack/react-query";

import { ApiError, getHealth } from "@/api/client";

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({ queryKey: ["health"], queryFn: getHealth });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="text-muted-foreground">
        Phase 0 skeleton — the project list and create form land in Phase 2.
      </p>

      <section className="max-w-md rounded-lg border p-4 text-sm">
        <div className="mb-2 font-medium">Backend health</div>
        {isLoading && <div className="text-muted-foreground">checking…</div>}
        {error && (
          <div className="text-destructive">unreachable: {(error as ApiError).message}</div>
        )}
        {data && (
          <div className="space-y-1">
            <div>
              <span className={data.status === "ok" ? "text-foreground" : "text-destructive"}>
                {data.status}
              </span>{" "}
              · app {data.app} {data.version}
            </div>
            <div className="text-muted-foreground">
              openrouter: {data.openrouter.reachable ? "reachable" : "unreachable"}
              {data.openrouter.key_configured
                ? ` · key ${data.openrouter.key_valid ? "valid" : "invalid"}`
                : " · no key configured"}
              {" · "}
              {data.openrouter_ms} ms
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
