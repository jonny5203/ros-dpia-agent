import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileText, LoaderCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router";

import {
  type ChunkRef,
  type NamedReferencedList,
  type OutputLanguage,
  type ProjectProfile,
  type ReferencedValue,
  getChunk,
  getJob,
  getLatestProfile,
  startAnalysis,
} from "@/api/analysis";
import { ApiError } from "@/api/client";

const SCALAR_FIELDS: { key: keyof Pick<
  ProjectProfile,
  "purpose" | "retention" | "accessControl" | "internationalTransfer"
>; label: string }[] = [
  { key: "purpose", label: "Purpose" },
  { key: "retention", label: "Retention and deletion" },
  { key: "accessControl", label: "Access control" },
  { key: "internationalTransfer", label: "International transfers" },
];

const LIST_FIELDS: { key: keyof Pick<
  ProjectProfile,
  | "dataSubjects"
  | "personalDataCategories"
  | "specialCategories"
  | "systems"
  | "processors"
>; label: string }[] = [
  { key: "dataSubjects", label: "Data subjects" },
  { key: "personalDataCategories", label: "Personal-data categories" },
  { key: "specialCategories", label: "Special categories" },
  { key: "systems", label: "Systems" },
  { key: "processors", label: "Processors" },
];

function CitationChips({
  citations,
  onSelect,
}: {
  citations: ChunkRef[];
  onSelect: (citation: ChunkRef) => void;
}) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {citations.map((citation) => (
        <button
          key={citation.chunkId}
          type="button"
          onClick={() => onSelect(citation)}
          className="inline-flex items-center gap-1 rounded-full border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <FileText className="h-3 w-3" />
          {citation.documentName ?? "Document"}
          {citation.page !== null ? ` · p. ${citation.page}` : ""}
        </button>
      ))}
    </div>
  );
}

function VerificationBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const grounded = status === "grounded";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        grounded
          ? "bg-emerald-100 text-emerald-800"
          : "bg-amber-100 text-amber-900"
      }`}
    >
      {status}
    </span>
  );
}

function ScalarField({
  label,
  field,
  onCitation,
}: {
  label: string;
  field: ReferencedValue;
  onCitation: (citation: ChunkRef) => void;
}) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold">{label}</h2>
        <VerificationBadge status={field.verificationStatus} />
      </div>
      {field.value ? (
        <p className="mt-2 text-sm leading-6">{field.value}</p>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">No grounded information found.</p>
      )}
      <CitationChips citations={field.sourceReferences} onSelect={onCitation} />
    </section>
  );
}

function ListField({
  label,
  field,
  onCitation,
}: {
  label: string;
  field: NamedReferencedList;
  onCitation: (citation: ChunkRef) => void;
}) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="font-semibold">{label}</h2>
      {field.items.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">No grounded information found.</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {field.items.map((item, index) => (
            <li key={`${item.value}-${index}`} className="border-l-2 pl-3">
              <div className="flex items-start justify-between gap-3 text-sm">
                <span>{item.value}</span>
                <VerificationBadge status={item.verificationStatus} />
              </div>
              <CitationChips citations={item.sourceReferences} onSelect={onCitation} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CitationDetail({
  citation,
  onClose,
}: {
  citation: ChunkRef;
  onClose: () => void;
}) {
  const chunk = useQuery({
    queryKey: ["chunk", citation.chunkId],
    queryFn: () => getChunk(citation),
  });

  return (
    <aside className="fixed inset-y-0 right-0 z-20 w-full max-w-xl overflow-y-auto border-l bg-background p-6 shadow-2xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Citation evidence
          </p>
          <h2 className="mt-1 text-lg font-semibold">{citation.documentName ?? "Document"}</h2>
          <p className="text-sm text-muted-foreground">
            {citation.page !== null ? `Page ${citation.page}` : "Page not recorded"}
            {citation.sectionTitle ? ` · ${citation.sectionTitle}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close citation"
          className="rounded-md p-2 hover:bg-accent"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      {chunk.isLoading && (
        <p className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="h-4 w-4 animate-spin" /> Loading evidence…
        </p>
      )}
      {chunk.error && (
        <p className="mt-6 text-sm text-destructive">
          Could not load citation: {(chunk.error as ApiError).message}
        </p>
      )}
      {chunk.data && (
        <div className="mt-6 space-y-3">
          <p className="text-xs text-muted-foreground">
            Chunk {chunk.data.chunk_index + 1} · checksum {chunk.data.sha8}
          </p>
          <pre className="whitespace-pre-wrap rounded-lg border bg-muted p-4 font-sans text-sm leading-6">
            {chunk.data.text}
          </pre>
        </div>
      )}
    </aside>
  );
}

export default function Analysis() {
  const { id: projectId } = useParams();
  const queryClient = useQueryClient();
  const [language, setLanguage] = useState<OutputLanguage>("nb");
  const [jobId, setJobId] = useState<string | null>(null);
  const [citation, setCitation] = useState<ChunkRef | null>(null);

  const profile = useQuery({
    queryKey: ["project-profile", projectId],
    queryFn: () => getLatestProfile(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const job = useQuery({
    queryKey: ["analysis-job", jobId],
    queryFn: () => getJob(jobId!),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1_000 : false;
    },
  });

  const analyze = useMutation({
    mutationFn: () => startAnalysis(projectId!, language),
    onSuccess: ({ job_id }) => setJobId(job_id),
  });

  const jobStatus = job.data?.status;
  useEffect(() => {
    if (jobStatus === "complete") {
      void queryClient.invalidateQueries({ queryKey: ["project-profile", projectId] });
    }
  }, [jobStatus, projectId, queryClient]);

  if (!projectId) {
    return <p className="text-destructive">A project ID is required.</p>;
  }

  const running = analyze.isPending || jobStatus === "queued" || jobStatus === "running";
  const current = profile.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 border-b pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-muted-foreground">Project profile</p>
          <h1 className="text-3xl font-semibold tracking-tight">AI Analysis</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Only citation-verified claims appear as trusted facts. Unsupported model output is
            isolated for human review.
          </p>
        </div>
        <div className="flex items-end gap-3">
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            Output language
            <select
              value={language}
              onChange={(event) => setLanguage(event.target.value as OutputLanguage)}
              disabled={running}
              className="h-10 rounded-md border bg-background px-3 text-sm text-foreground"
            >
              <option value="nb">Norsk bokmål</option>
              <option value="en">English</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => analyze.mutate()}
            disabled={running}
            className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
            {current ? "Analyze again" : "Analyze project"}
          </button>
        </div>
      </header>

      {job.data && (
        <section className="rounded-lg border bg-muted/40 p-4" aria-live="polite">
          <div className="flex items-center justify-between gap-4 text-sm">
            <span className="font-medium">Analysis job: {job.data.status}</span>
            <span>{job.data.progress_pct}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${job.data.progress_pct}%` }}
            />
          </div>
          {job.data.status === "failed" && (
            <p className="mt-2 text-sm text-destructive">
              {job.data.error ?? "Analysis failed."}
            </p>
          )}
        </section>
      )}

      {analyze.error && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Could not start analysis: {(analyze.error as ApiError).message}
        </p>
      )}
      {profile.isLoading && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="h-4 w-4 animate-spin" /> Loading profile…
        </p>
      )}
      {profile.error && (
        <p className="text-sm text-destructive">
          Could not load the profile: {(profile.error as ApiError).message}
        </p>
      )}

      {!profile.isLoading && current === null && !running && (
        <section className="rounded-lg border border-dashed p-10 text-center">
          <h2 className="font-semibold">No profile yet</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Analyze the indexed project documents to build a citation-gated profile.
          </p>
        </section>
      )}

      {current && (
        <>
          <section className="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-4 text-sm">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            <span className="font-medium">Verified profile</span>
            <span className="text-muted-foreground">
              confidence {current.overall_confidence} · {current.model} · {current.prompt_version}
            </span>
            <time className="ml-auto text-muted-foreground" dateTime={current.created_at}>
              {new Date(current.created_at).toLocaleString()}
            </time>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            {SCALAR_FIELDS.map(({ key, label }) => (
              <ScalarField
                key={key}
                label={label}
                field={current.profile[key]}
                onCitation={setCitation}
              />
            ))}
            {LIST_FIELDS.map(({ key, label }) => (
              <ListField
                key={key}
                label={label}
                field={current.profile[key]}
                onCitation={setCitation}
              />
            ))}
          </div>

          <section className="rounded-lg border border-amber-300 bg-amber-50 p-5 text-amber-950">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              <h2 className="font-semibold">Missing information</h2>
            </div>
            {current.profile.missingInfo.length === 0 ? (
              <p className="mt-3 text-sm">No explicit gaps were identified.</p>
            ) : (
              <ul className="mt-3 space-y-3">
                {current.profile.missingInfo.map((gap, index) => (
                  <li key={`${gap.field}-${index}`} className="rounded-md bg-white/60 p-3 text-sm">
                    <span className="font-medium">{gap.field}</span>
                    <span className="ml-2 rounded bg-amber-200 px-1.5 py-0.5 text-xs">
                      {gap.severity}
                    </span>
                    <p className="mt-1">{gap.description}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border p-5">
            <h2 className="font-semibold">Open questions</h2>
            {current.profile.openQuestions.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">No open questions.</p>
            ) : (
              <ol className="mt-3 list-decimal space-y-3 pl-5 text-sm">
                {current.profile.openQuestions.map((question, index) => (
                  <li key={`${question.question}-${index}`}>
                    <p className="font-medium">{question.question}</p>
                    {question.rationale && (
                      <p className="mt-1 text-muted-foreground">{question.rationale}</p>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {current.profile.needsReview.length > 0 && (
            <section className="rounded-lg border border-destructive/40 bg-destructive/5 p-5">
              <div className="flex items-center gap-2 text-destructive">
                <AlertTriangle className="h-5 w-5" />
                <h2 className="font-semibold">Needs human review</h2>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                These model claims were rejected by the citation gate and are not trusted facts.
              </p>
              <ul className="mt-4 space-y-3">
                {current.profile.needsReview.map((claim, index) => (
                  <li key={`${claim.fieldPath}-${index}`} className="rounded-md border bg-background p-3">
                    <p className="text-xs font-medium text-destructive">{claim.fieldPath}</p>
                    <p className="mt-1 text-sm line-through decoration-destructive/60">
                      {claim.value}
                    </p>
                    {claim.unverifiedCitations.length > 0 && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        Rejected citations: {claim.unverifiedCitations.join(", ")}
                      </p>
                    )}
                    <CitationChips citations={claim.sourceReferences} onSelect={setCitation} />
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {citation && <CitationDetail citation={citation} onClose={() => setCitation(null)} />}
    </div>
  );
}
