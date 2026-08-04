import { ApiError, apiFetch } from "@/api/client";

export type OutputLanguage = "nb" | "en";
export type VerificationStatus = "grounded" | "partial" | "unverified";
export type OverallConfidence = "high" | "medium" | "low";

export interface ChunkRef {
  chunkId: string;
  documentId: string;
  documentName: string | null;
  page: number | null;
  sectionTitle: string | null;
}

interface ReferencedBase {
  sourceReferences: ChunkRef[];
  evidenceMissing: boolean;
  verificationStatus: VerificationStatus | null;
}

export interface ReferencedValue extends ReferencedBase {
  value: string | null;
}

export interface ReferencedItem extends ReferencedBase {
  value: string;
}

export interface NamedReferencedList {
  items: ReferencedItem[];
}

export interface Gap {
  field: string;
  description: string;
  severity: "info" | "warning" | "critical";
}

export interface OpenQuestion {
  question: string;
  rationale: string | null;
}

export interface NeedsReviewClaim {
  fieldPath: string;
  value: string;
  sourceReferences: ChunkRef[];
  unverifiedCitations: string[];
  evidenceMissing: boolean;
  verificationStatus: "unverified";
}

export interface ProjectProfile {
  purpose: ReferencedValue;
  dataSubjects: NamedReferencedList;
  personalDataCategories: NamedReferencedList;
  specialCategories: NamedReferencedList;
  systems: NamedReferencedList;
  processors: NamedReferencedList;
  retention: ReferencedValue;
  accessControl: ReferencedValue;
  internationalTransfer: ReferencedValue;
  missingInfo: Gap[];
  openQuestions: OpenQuestion[];
  needsReview: NeedsReviewClaim[];
  overallConfidence: OverallConfidence;
}

export interface ProjectProfileRead {
  id: string;
  project_id: string;
  profile: ProjectProfile;
  overall_confidence: OverallConfidence;
  model: string;
  prompt_version: string;
  created_at: string;
}

export interface JobRead {
  id: string;
  project_id: string;
  kind: string;
  status: "queued" | "running" | "complete" | "failed" | "blocked";
  progress_pct: number;
  error: string | null;
  arq_job_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChunkRead {
  id: string;
  document_id: string;
  chunk_index: number;
  page: number | null;
  section_title: string | null;
  section_path: string | null;
  char_start: number;
  char_end: number;
  sha8: string;
  text: string;
}

export async function getLatestProfile(projectId: string): Promise<ProjectProfileRead | null> {
  try {
    return await apiFetch<ProjectProfileRead>(`/api/v1/projects/${projectId}/profile`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const startAnalysis = (projectId: string, outputLanguage: OutputLanguage) =>
  apiFetch<{ job_id: string }>(`/api/v1/projects/${projectId}/analyze`, {
    method: "POST",
    body: JSON.stringify({ output_language: outputLanguage }),
  });

export const getJob = (jobId: string) => apiFetch<JobRead>(`/api/v1/jobs/${jobId}`);

export const getChunk = (citation: ChunkRef) =>
  apiFetch<ChunkRead>(
    `/api/v1/documents/${citation.documentId}/chunks/${citation.chunkId}`,
  );
