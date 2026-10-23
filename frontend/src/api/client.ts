// API 호출 도우미. 타입은 백엔드 OpenAPI에서 생성한 schema.ts를 쓴다 (pnpm gen:api).
import type { JSONContent } from "@tiptap/core";

import type { components } from "./schema";

export type Schemas = components["schemas"];
export type ProductSummary = Schemas["ProductSummary"];
export type ProductDetail = Schemas["ProductDetail"];
export type ProductStatus = Schemas["ProductStatus"];
export type DocumentSetSummary = Schemas["DocumentSetSummary"];
export type DocumentSetDetail = Schemas["DocumentSetDetail"];
export type PreviewOut = Schemas["PreviewOut"];
export type ClauseSummary = Schemas["ClauseSummary"];
export type ClauseDetail = Schemas["ClauseDetail"];
export type ImpactOut = Schemas["ImpactOut"];
export type ImpactProduct = Schemas["ImpactProduct"];
export type BulkUpdateSummary = Schemas["BulkUpdateSummary"];
export type BulkUpdateDetail = Schemas["BulkUpdateDetail"];
export type BulkUpdateItemOut = Schemas["BulkUpdateItemOut"];
export type ImpactDocument = Schemas["ImpactDocument"];
export type VariableImpactOut = Schemas["VariableImpactOut"];
export type ErrorResponse = Schemas["ErrorResponse"];

// KMS
export type CategoryOut = Schemas["CategoryOut"];
export type TagOut = Schemas["TagOut"];
export type VariableOut = Schemas["VariableOut"];
export type DocumentSummary = Schemas["DocumentSummary"];
export type DocumentDetail = Schemas["DocumentDetail"];
export type DocumentStatus = Schemas["DocumentStatus"];
export type BlockOut = Schemas["BlockOut"];
export type DocumentRevisionSummary = Schemas["DocumentRevisionSummary"];
export type PublicationSummary = Schemas["PublicationSummary"];
export type PublicationDetail = Schemas["PublicationDetail"];
export type SearchOut = Schemas["SearchOut"];
export type ClauseRevisionOut = Schemas["ClauseRevisionOut"];
// 에디터(TipTap) 본문 JSON. 서버 응답의 content_json은 이 형식이다.
export type RichDoc = JSONContent;

export function publicationFileUrl(publicationId: string, fileId: string): string {
  return `/api/publications/${publicationId}/files/${fileId}`;
}

export function documentPreviewUrl(documentId: string, revisionNo?: number): string {
  return `/api/documents/${documentId}/preview${revisionNo ? `?revision_no=${revisionNo}` : ""}`;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ErrorResponse,
  ) {
    super(body.message);
  }
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: init?.method ?? (init?.body === undefined ? "GET" : "POST"),
    headers: init?.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const body =
      data && typeof data === "object" && "message" in data
        ? (data as ErrorResponse)
        : { code: "HTTP_ERROR", message: `요청 실패 (${res.status})`, errors: [] };
    throw new ApiError(res.status, body);
  }
  return data as T;
}

export function fileUrl(versionId: string, fileId: string): string {
  return `/api/document-sets/${versionId}/files/${fileId}`;
}

export function versionHtmlUrl(versionId: string): string {
  return `/api/document-sets/${versionId}/html`;
}
