import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectProfileRead } from "@/api/analysis";
import Analysis from "@/routes/Analysis";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_ID = "22222222-2222-4222-8222-222222222222";
const CHUNK_ID = "33333333-3333-4333-8333-333333333333";

const citation = {
  chunkId: CHUNK_ID,
  documentId: DOCUMENT_ID,
  documentName: "HSO source.docx",
  page: 2,
  sectionTitle: "Architecture",
};

const emptyScalar = {
  value: null,
  sourceReferences: [],
  evidenceMissing: false,
  verificationStatus: null,
};

const profile: ProjectProfileRead = {
  id: "44444444-4444-4444-8444-444444444444",
  project_id: PROJECT_ID,
  overall_confidence: "medium",
  model: "model-v1",
  prompt_version: "profile-v1",
  created_at: "2026-08-04T10:00:00Z",
  profile: {
    purpose: {
      value: "Support municipal health-service casework",
      sourceReferences: [citation],
      evidenceMissing: false,
      verificationStatus: "grounded",
    },
    dataSubjects: { items: [] },
    personalDataCategories: { items: [] },
    specialCategories: { items: [] },
    systems: {
      items: [
        {
          value: "Azure OpenAI",
          sourceReferences: [citation],
          evidenceMissing: false,
          verificationStatus: "grounded",
        },
      ],
    },
    processors: { items: [] },
    retention: emptyScalar,
    accessControl: emptyScalar,
    internationalTransfer: emptyScalar,
    missingInfo: [
      {
        field: "retention",
        description: "Retention is undocumented",
        severity: "warning",
      },
    ],
    openQuestions: [
      {
        question: "How long will personal data be retained?",
        rationale: "A defined deletion schedule is required.",
      },
    ],
    needsReview: [
      {
        fieldPath: "accessControl",
        value: "Unsupported logging claim",
        sourceReferences: [],
        unverifiedCitations: ["C999"],
        evidenceMissing: true,
        verificationStatus: "unverified",
      },
    ],
    overallConfidence: "medium",
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderAnalysis() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}/analysis`]}>
        <Routes>
          <Route path="/projects/:id/analysis" element={<Analysis />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Analysis", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders trusted claims, gaps, questions, rejected claims, and citation evidence", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith(`/projects/${PROJECT_ID}/profile`)) return jsonResponse(profile);
      if (path.endsWith(`/documents/${DOCUMENT_ID}/chunks/${CHUNK_ID}`)) {
        return jsonResponse({
          id: CHUNK_ID,
          document_id: DOCUMENT_ID,
          chunk_index: 0,
          page: 2,
          section_title: "Architecture",
          section_path: "Overview > Architecture",
          char_start: 0,
          char_end: 48,
          sha8: "deadbeef",
          text: "Azure OpenAI is used for structured project analysis.",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderAnalysis();

    expect(await screen.findByText("Azure OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Retention is undocumented")).toBeInTheDocument();
    expect(screen.getByText("How long will personal data be retained?")).toBeInTheDocument();
    expect(screen.getByText("Unsupported logging claim")).toBeInTheDocument();
    expect(screen.getByText("Rejected citations: C999")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /HSO source\.docx/ })[0]);

    expect(
      await screen.findByText("Azure OpenAI is used for structured project analysis."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close citation" })).toBeInTheDocument();
  });

  it("starts an English analysis and exposes queued progress", async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith(`/projects/${PROJECT_ID}/profile`)) {
        return jsonResponse(
          {
            type: "about:blank",
            title: "Not Found",
            status: 404,
            detail: "Profile not found",
          },
          404,
        );
      }
      if (path.endsWith(`/projects/${PROJECT_ID}/analyze`) && init?.method === "POST") {
        return jsonResponse({ job_id: "55555555-5555-4555-8555-555555555555" }, 202);
      }
      if (path.endsWith("/jobs/55555555-5555-4555-8555-555555555555")) {
        return jsonResponse({
          id: "55555555-5555-4555-8555-555555555555",
          project_id: PROJECT_ID,
          kind: "analyze_project",
          status: "queued",
          progress_pct: 0,
          error: null,
          arq_job_id: "arq-123",
          created_at: "2026-08-04T10:00:00Z",
          updated_at: "2026-08-04T10:00:00Z",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderAnalysis();

    expect(await screen.findByText("No profile yet")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Output language"), {
      target: { value: "en" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze project" }));

    expect(await screen.findByText("Analysis job: queued")).toBeInTheDocument();
    await waitFor(() => {
      const post = vi
        .mocked(fetch)
        .mock.calls.find(([, init]) => init?.method === "POST");
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ output_language: "en" });
    });
  });

  it("refreshes the profile when the analysis job completes", async () => {
    let profileRequests = 0;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith(`/projects/${PROJECT_ID}/profile`)) {
        profileRequests += 1;
        if (profileRequests === 1) {
          return jsonResponse(
            {
              type: "about:blank",
              title: "Not Found",
              status: 404,
              detail: "Profile not found",
            },
            404,
          );
        }
        return jsonResponse(profile);
      }
      if (path.endsWith(`/projects/${PROJECT_ID}/analyze`) && init?.method === "POST") {
        return jsonResponse({ job_id: "66666666-6666-4666-8666-666666666666" }, 202);
      }
      if (path.endsWith("/jobs/66666666-6666-4666-8666-666666666666")) {
        return jsonResponse({
          id: "66666666-6666-4666-8666-666666666666",
          project_id: PROJECT_ID,
          kind: "analyze_project",
          status: "complete",
          progress_pct: 100,
          error: null,
          arq_job_id: "arq-456",
          created_at: "2026-08-04T10:00:00Z",
          updated_at: "2026-08-04T10:00:03Z",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderAnalysis();

    expect(await screen.findByText("No profile yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Analyze project" }));

    expect(await screen.findByText("Analysis job: complete")).toBeInTheDocument();
    expect(await screen.findByText("Azure OpenAI")).toBeInTheDocument();
    expect(profileRequests).toBe(2);
  });
});
