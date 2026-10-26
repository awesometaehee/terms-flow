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

  it("treats table cell span 1 as default", () => {
    const cell = (attrs?: object) => ({ type: "tableCell", ...(attrs ? { attrs } : {}), content: [{ type: "paragraph" }] });
    const a = { type: "doc", content: [{ type: "table", content: [{ type: "tableRow", content: [cell()] }] }] };
    const b = {
      type: "doc",
      content: [{ type: "table", content: [{ type: "tableRow", content: [cell({ colspan: 1, rowspan: 1, colwidth: null })] }] }],
    };
    expect(sameDoc(a, b)).toBe(true);
    expect(normalizeDoc(cell({ colspan: 2, rowspan: 1 }))).toEqual({ attrs: { colspan: 2 }, content: [{ type: "paragraph" }], type: "tableCell" });
  });

  it("keeps meaningful attrs", () => {
    expect(normalizeDoc({ type: "variable", attrs: { key: "x", other: null } })).toEqual({ attrs: { key: "x" }, type: "variable" });
  });
});
