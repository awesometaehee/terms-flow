import { describe, expect, it } from "vitest";

import { normalizeDoc, sameDoc } from "./richdoc";

describe("sameDoc", () => {
  it("ignores editor nulls, empty arrays and key order", () => {
    const stored = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "a" }] }] };
    const fromEditor = {
      content: [{ attrs: { textAlign: null }, type: "paragraph", content: [{ text: "a", type: "text", marks: [] }] }],
      type: "doc",
    };
    expect(sameDoc(stored, fromEditor)).toBe(true);
  });

  it("detects real changes", () => {
    const a = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "a" }] }] };
    const b = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "a", marks: [{ type: "bold" }] }] }] };
    expect(sameDoc(a, b)).toBe(false);
  });

  it("keeps meaningful attrs", () => {
    expect(normalizeDoc({ type: "variable", attrs: { key: "x", other: null } })).toEqual({ attrs: { key: "x" }, type: "variable" });
  });
});
