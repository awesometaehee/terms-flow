// 본문 JSON 비교. 서버(app/richtext.py normalize)와 같은 규칙으로 빈 값을 지우고 키 순서와 무관하게 비교한다.
import type { RichDoc } from "../api/client";

export function normalizeDoc(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(normalizeDoc);
  if (node === null || typeof node !== "object") return node;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(node).sort()) {
    const value = (node as Record<string, unknown>)[key];
    if (key === "attrs" && value && typeof value === "object") {
      const attrs = Object.fromEntries(
        Object.entries(value as Record<string, unknown>)
          .filter(([, v]) => v !== null && v !== undefined)
          .sort(([a], [b]) => a.localeCompare(b)),
      );
      if (Object.keys(attrs).length) out[key] = attrs;
    } else if ((key === "marks" || key === "content") && Array.isArray(value)) {
      if (value.length) out[key] = normalizeDoc(value);
    } else if (value !== null && value !== undefined) {
      out[key] = normalizeDoc(value);
    }
  }
  return out;
}

// 정규화한 본문의 비교용 문자열
export function docKey(doc: RichDoc): string {
  return JSON.stringify(normalizeDoc(doc));
}

export function sameDoc(a: RichDoc | null | undefined, b: RichDoc | null | undefined): boolean {
  if (!a || !b) return a === b;
  return docKey(a) === docKey(b);
}
