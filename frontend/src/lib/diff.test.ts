import { describe, expect, it } from "vitest";

import { diffLines, toCsv } from "./diff";

describe("diffLines", () => {
  it("marks removed and added lines around unchanged ones", () => {
    expect(diffLines("제1항\n변경 전\n제3항", "제1항\n변경 후\n제3항")).toEqual([
      { kind: "same", text: "제1항" },
      { kind: "removed", text: "변경 전" },
      { kind: "added", text: "변경 후" },
      { kind: "same", text: "제3항" },
    ]);
  });

  it("handles appended lines", () => {
    expect(diffLines("a", "a\nb")).toEqual([
      { kind: "same", text: "a" },
      { kind: "added", text: "b" },
    ]);
  });
});

describe("toCsv", () => {
  it("quotes values and prefixes BOM", () => {
    expect(toCsv(["코드", "사유"], [["P1", '따옴표 "포함"']])).toBe('﻿"코드","사유"\r\n"P1","따옴표 ""포함"""');
  });
});
