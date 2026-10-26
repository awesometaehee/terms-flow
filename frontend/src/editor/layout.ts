// 표·단 나누기·이미지. JSON 형식은 서버(app/richtext.py)와 같다.
// - 표 칸 안: 문단·제목·목록·이미지 (표 안의 표, 표 안의 단은 넣지 않는다)
// - 단 안: 그 밖에 표도 넣을 수 있다 (단 안의 단은 넣지 않는다)
import { Extension, Node, findParentNode, mergeAttributes } from "@tiptap/core";
import { Image } from "@tiptap/extension-image";
import { TableCell, TableHeader, TableRow, TableView } from "@tiptap/extension-table";
import { Fragment, type Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection, type Transaction } from "@tiptap/pm/state";
import { TableMap, columnResizingPluginKey } from "@tiptap/pm/tables";
import type { EditorView, NodeView, ViewMutationRecord } from "@tiptap/pm/view";

import { uploadLibraryImage } from "../lib/images";

const CELL_CONTENT = "(paragraph | heading | bulletList | orderedList | image)+";
const COLUMN_CONTENT = "(paragraph | heading | bulletList | orderedList | image | table)+";

// --- 표 열 너비 ---------------------------------------------------------------------

// 저장된 열 너비(px)는 비율로 쓴다. 너비가 없는 열은 있는 열들의 평균을 준다 (서버 출력과 같은 규칙).
// 그래야 넓은 화면(모듈)에서 맞춘 표가 좁은 화면(문서)에서도 넘치거나 일부 열이 찌그러지지 않는다.
export function columnPercents(table: PMNode): number[] {
  const widths: (number | null)[] = [];
  table.firstChild?.forEach((cell) => {
    const colspan = Number(cell.attrs.colspan) || 1;
    const colwidth = cell.attrs.colwidth as (number | null)[] | null;
    for (let i = 0; i < colspan; i += 1) widths.push(colwidth?.[i] || null);
  });
  const known = widths.filter((w): w is number => !!w);
  const fill = known.length ? known.reduce((a, b) => a + b, 0) / known.length : 1;
  const filled = widths.map((w) => w ?? fill);
  const total = filled.reduce((a, b) => a + b, 0);
  return filled.map((w) => (w / total) * 100);
}

// 표를 언제나 칸 너비(100%)에 맞추고 열은 비율로 나눈다.
// 열 경계를 끄는 동안에는 크기 조절 기능이 px로 그렸다가, 놓으면(새 colwidth 저장) 다시 비율로 맞춘다.
export class FitTableView extends TableView {
  constructor(...args: ConstructorParameters<typeof TableView>) {
    super(...args);
    this.fit();
  }

  update(node: PMNode): boolean {
    const ok = super.update(node);
    if (ok) this.fit();
    return ok;
  }

  private fit() {
    const percents = columnPercents(this.node);
    Array.from(this.colgroup.children).forEach((col, i) => {
      const el = col as HTMLElement;
      el.style.minWidth = "";
      el.style.width = percents[i] !== undefined ? `${percents[i]}%` : "";
    });
    this.table.style.width = "100%";
    this.table.style.minWidth = "";
  }
}

// 열 경계를 잡는 순간, 그 표의 저장된 너비를 지금 화면의 px로 바꿔 둔다 (보이는 모양은 그대로).
// 저장된 너비가 넓은 화면 기준이면 좁은 화면에서 끌 때 마우스보다 덜 움직이기 때문이다.
export const TableFitResize = Extension.create({
  name: "tableFitResize",
  // 표 크기 조절 플러그인보다 먼저 mousedown을 받아야 한다.
  priority: 1000,
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("tableFitResize"),
        props: {
          handleDOMEvents: {
            mousedown: (view) => {
              const handle = columnResizingPluginKey.getState(view.state)?.activeHandle ?? -1;
              if (handle < 0) return false;
              const $cell = view.state.doc.resolve(handle);
              let depth = $cell.depth;
              while (depth > 0 && $cell.node(depth).type.name !== "table") depth -= 1;
              if (depth === 0) return false;
              const table = $cell.node(depth);
              const tableStart = $cell.start(depth);
              const dom = (view.nodeDOM(tableStart - 1) as HTMLElement | null)?.querySelector("table");
              const map = TableMap.get(table);
              const percents = columnPercents(table);
              if (!dom || percents.length !== map.width) return false;
              const total = dom.getBoundingClientRect().width;
              const widths = percents.map((pct) => Math.max(1, Math.round((total * pct) / 100)));
              const tr = view.state.tr;
              const seen = new Set<number>();
              for (const cellPos of map.map) {
                if (seen.has(cellPos)) continue;
                seen.add(cellPos);
                const cell = table.nodeAt(cellPos)!;
                const rect = map.findCell(cellPos);
                const colwidth = widths.slice(rect.left, rect.right);
                if (JSON.stringify(cell.attrs.colwidth) !== JSON.stringify(colwidth)) {
                  tr.setNodeMarkup(tableStart + cellPos, undefined, { ...cell.attrs, colwidth });
                }
              }
              if (tr.docChanged) view.dispatch(tr.setMeta("addToHistory", false));
              return false;
            },
          },
        },
      }),
    ];
  },
});

// --- 행 높이 -----------------------------------------------------------------------

// 행 높이(px)는 최소 높이로 쓴다. 글자가 넘치면 그만큼 더 커진다.
export const RichTableRow = TableRow.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      height: {
        default: null,
        parseHTML: (el) => parseInt(el.style.height, 10) || null,
        renderHTML: (attrs) => (attrs.height ? { style: `height: ${attrs.height}px` } : {}),
      },
    };
  },
});

const ROW_EDGE = 4; // px: 행 아래 선에서 이 거리 안이면 높이를 끌 수 있다
const ROW_SNAP = 2;
const ROW_MIN = 16;

// 행 아래 선을 끌어 높이를 바꾼다. 끄는 동안은 문서 밖 <style>로 미리 보여 주고(행 요소는 에디터가 관리한다),
// 놓으면 그 행의 height로 저장한다. 다른 표와 맞출 수 있게 지금 높이를 숫자로 보여 준다.
// Shift를 누른 채 끌면 표의 모든 행을 같은 높이로 바꾼다 (끄는 도중에 눌러도 된다).
export const RowResize = Extension.create({
  name: "rowResize",
  addProseMirrorPlugins() {
    let hoverRow: HTMLTableRowElement | null = null;
    let dragging = false;

    const rowAtEdge = (view: EditorView, event: MouseEvent): HTMLTableRowElement | null => {
      const cell = (event.target as HTMLElement | null)?.closest?.("td, th");
      const table = cell?.closest("table");
      if (!table || !view.dom.contains(table)) return null;
      // 칸이 여러 줄에 걸쳐 있어도 마우스 높이로 어느 행의 아래 선인지 찾는다.
      for (const tr of Array.from(table.rows)) {
        if (Math.abs(event.clientY - tr.getBoundingClientRect().bottom) <= ROW_EDGE) return tr;
      }
      return null;
    };

    const setHover = (view: EditorView, row: HTMLTableRowElement | null) => {
      hoverRow = row;
      view.dom.classList.toggle("row-resize-cursor", !!row);
    };

    const startDrag = (view: EditorView, event: MouseEvent, tr: HTMLTableRowElement) => {
      const table = tr.closest("table")!;
      const index = Array.from(table.rows).indexOf(tr);
      const startY = event.clientY;
      const startHeight = tr.getBoundingClientRect().height;
      const id = Math.random().toString(36).slice(2);
      table.dataset.rowResize = id;
      const style = document.head.appendChild(document.createElement("style"));
      const label = document.body.appendChild(document.createElement("div"));
      label.className = "row-resize-label";
      let height = Math.round(startHeight);
      let all = event.shiftKey;
      dragging = true;

      const onMove = (e: MouseEvent) => {
        height = Math.max(ROW_MIN, Math.round((startHeight + e.clientY - startY) / ROW_SNAP) * ROW_SNAP);
        all = e.shiftKey;
        const rows = all ? "tr" : `tr:nth-child(${index + 1})`;
        style.textContent = `table[data-row-resize="${id}"] > tbody > ${rows} { height: ${height}px !important; }`;
        label.textContent = all ? `모든 행 높이 ${height}px` : `높이 ${height}px`;
        label.style.left = `${e.clientX + 14}px`;
        label.style.top = `${e.clientY - 10}px`;
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        dragging = false;
        delete table.dataset.rowResize;
        style.remove();
        label.remove();
        setHover(view, null);
        const pos = view.posAtDOM(tr, 0) - 1;
        const row = view.state.doc.nodeAt(pos);
        if (!row || row.type.name !== "tableRow") return;
        const change = view.state.tr;
        if (all) {
          // 이 행이 든 표의 모든 행
          const $row = view.state.doc.resolve(pos);
          const tablePos = $row.before($row.depth);
          $row.parent.forEach((child, offset) => {
            if (child.attrs.height !== height) change.setNodeMarkup(tablePos + 1 + offset, undefined, { ...child.attrs, height });
          });
        } else if (row.attrs.height !== height) {
          change.setNodeMarkup(pos, undefined, { ...row.attrs, height });
        }
        if (change.docChanged) view.dispatch(change);
      };
      onMove(event);
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    };

    return [
      new Plugin({
        key: new PluginKey("rowResize"),
        props: {
          handleDOMEvents: {
            mousemove: (view, event) => {
              if (dragging || !view.editable) return false;
              // 열 경계를 잡을 수 있는 자리에서는 열 크기 조절이 먼저다.
              if ((columnResizingPluginKey.getState(view.state)?.activeHandle ?? -1) > -1) {
                if (hoverRow) setHover(view, null);
                return false;
              }
              const row = rowAtEdge(view, event);
              if (row !== hoverRow) setHover(view, row);
              return false;
            },
            mouseleave: (view) => {
              if (!dragging && hoverRow) setHover(view, null);
              return false;
            },
            mousedown: (view, event) => {
              if (!hoverRow || event.button !== 0 || !view.editable) return false;
              event.preventDefault();
              startDrag(view, event, hoverRow);
              return true;
            },
          },
        },
      }),
    ];
  },
});

// --- 표 칸 배경색 ------------------------------------------------------------------

const background = {
  background: {
    default: null,
    parseHTML: (el: HTMLElement) => el.style.backgroundColor || null,
    renderHTML: (attrs: { background?: string | null }) =>
      attrs.background ? { style: `background-color: ${attrs.background}` } : {},
  },
};

export const RichTableCell = TableCell.extend({
  content: CELL_CONTENT,
  addAttributes() {
    return { ...this.parent?.(), ...background };
  },
});

export const RichTableHeader = TableHeader.extend({
  content: CELL_CONTENT,
  addAttributes() {
    return { ...this.parent?.(), ...background };
  },
});

// --- 단 나누기 ---------------------------------------------------------------------

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    columns: {
      insertColumns: (count: number) => ReturnType;
      // 단 너비 비율 (예: [1, 2]). null이면 같은 너비
      setColumnWidths: (ratio: number[] | null) => ReturnType;
      addColumn: () => ReturnType;
      removeColumn: () => ReturnType;
      // 단을 풀어 내용을 위에서 아래로 이어 붙인다.
      unsetColumns: () => ReturnType;
    };
  }
}

export const Column = Node.create({
  name: "column",
  content: COLUMN_CONTENT,
  isolating: true,

  addAttributes() {
    return {
      width: {
        default: null,
        parseHTML: (el) => Number(el.getAttribute("data-width")) || null,
        // 에디터에서는 단마다 비율을 직접 준다 (부모 격자는 단 너비가 바뀌어도 다시 그려지지 않는다).
        renderHTML: (attrs) => (attrs.width ? { "data-width": attrs.width, style: `flex-grow: ${attrs.width}` } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="column"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "column", class: "rt-column" }), 0];
  },
});

// 단 경계를 끌어 비율을 바꾼다. 손잡이는 편집 내용 밖(contentDOM 밖)에 두어 입력에 끼어들지 않는다.
// 끄는 동안 바로 보여 주고 5% 단위로 맞추며, 놓으면 버튼과 같은 형식(합 100인 정수)으로 저장한다.
const SNAP = 5;
const MIN_WIDTH = 10;

function currentWidths(node: PMNode): number[] {
  const widths: number[] = [];
  node.forEach((col) => widths.push(Number(col.attrs.width) || 0));
  if (widths.every((w) => w > 0)) return widths;
  // 너비가 없으면 같은 너비 (합 100: 3단은 33·33·34)
  const even = Math.floor(100 / node.childCount);
  return widths.map((_, i) => (i === node.childCount - 1 ? 100 - even * (node.childCount - 1) : even));
}

class ColumnsView implements NodeView {
  dom: HTMLElement;
  contentDOM: HTMLElement;
  private node: PMNode;
  private handles: HTMLElement[] = [];
  private label: HTMLElement;
  private observer: ResizeObserver;

  constructor(
    node: PMNode,
    private view: EditorView,
    private getPos: () => number | undefined,
  ) {
    this.node = node;
    this.dom = document.createElement("div");
    this.dom.className = "rt-columns-wrap";
    this.contentDOM = this.dom.appendChild(document.createElement("div"));
    this.contentDOM.className = "rt-columns";
    this.contentDOM.dataset.type = "columns";
    this.label = this.dom.appendChild(document.createElement("div"));
    this.label.className = "columns-ratio-label";
    this.label.contentEditable = "false";
    this.observer = new ResizeObserver(() => this.layout());
    this.observer.observe(this.contentDOM);
    this.syncHandles();
  }

  update(node: PMNode): boolean {
    if (node.type !== this.node.type) return false;
    this.node = node;
    this.syncHandles();
    return true;
  }

  // 손잡이·비율 표시는 편집 내용이 아니다.
  ignoreMutation(mutation: ViewMutationRecord): boolean {
    return mutation.type !== "selection" && !this.contentDOM.contains(mutation.target);
  }

  stopEvent(event: Event): boolean {
    return event.target instanceof HTMLElement && event.target.classList.contains("columns-handle");
  }

  destroy() {
    this.observer.disconnect();
  }

  private syncHandles() {
    const needed = this.node.childCount - 1;
    while (this.handles.length < needed) {
      const handle = document.createElement("div");
      handle.className = "columns-handle";
      handle.contentEditable = "false";
      handle.title = "끌어서 단 너비 바꾸기";
      const index = this.handles.length;
      handle.addEventListener("mousedown", (event) => this.startDrag(event, index));
      this.dom.appendChild(handle);
      this.handles.push(handle);
    }
    while (this.handles.length > needed) this.handles.pop()!.remove();
    requestAnimationFrame(() => this.layout());
  }

  // 손잡이를 단과 단 사이 틈 가운데에 놓는다.
  private layout() {
    const cols = Array.from(this.contentDOM.children) as HTMLElement[];
    const base = this.dom.getBoundingClientRect();
    this.handles.forEach((handle, i) => {
      const left = cols[i]?.getBoundingClientRect();
      const right = cols[i + 1]?.getBoundingClientRect();
      if (!left || !right) return;
      handle.style.left = `${(left.right + right.left) / 2 - base.left}px`;
    });
  }

  private startDrag(event: MouseEvent, index: number) {
    if (!this.view.editable) return;
    event.preventDefault();
    event.stopPropagation();
    const widths = currentWidths(this.node);
    const pair = widths[index] + widths[index + 1];
    const cols = Array.from(this.contentDOM.children) as HTMLElement[];
    const gap = cols.length > 1 ? cols[1].getBoundingClientRect().left - cols[0].getBoundingClientRect().right : 0;
    const usable = this.contentDOM.getBoundingClientRect().width - gap * (cols.length - 1);
    const startX = event.clientX;
    let next = widths;
    this.dom.classList.add("is-resizing");
    this.handles[index].classList.add("is-active");

    const onMove = (e: MouseEvent) => {
      const delta = ((e.clientX - startX) / usable) * 100;
      let left = Math.round((widths[index] + delta) / SNAP) * SNAP;
      left = Math.min(pair - MIN_WIDTH, Math.max(MIN_WIDTH, left));
      next = widths.slice();
      next[index] = left;
      next[index + 1] = pair - left;
      // 단 요소는 에디터가 관리하므로 직접 바꾸지 않고, 바깥 요소의 CSS 변수로 미리 보여 준다.
      next.forEach((w, i) => this.dom.style.setProperty(`--col-${i}`, String(w)));
      this.label.textContent = next.join(" : ");
      this.label.style.left = this.handles[index].style.left;
      this.label.classList.add("is-visible");
      this.layout();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      this.dom.classList.remove("is-resizing");
      next.forEach((_, i) => this.dom.style.removeProperty(`--col-${i}`));
      this.handles[index].classList.remove("is-active");
      this.label.classList.remove("is-visible");
      const pos = this.getPos();
      if (pos === undefined || next.join() === currentWidths(this.node).join()) return;
      const tr = this.view.state.tr;
      this.node.forEach((col, offset, i) => tr.setNodeMarkup(pos + 1 + offset, undefined, { ...col.attrs, width: next[i] }));
      this.view.dispatch(tr);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }
}

const parentColumns = findParentNode((node) => node.type.name === "columns");
const parentColumn = findParentNode((node) => node.type.name === "column");

export const Columns = Node.create({
  name: "columns",
  group: "block",
  content: "column{2,4}",
  isolating: true,
  defining: true,

  parseHTML() {
    return [{ tag: 'div[data-type="columns"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-type": "columns", class: "rt-columns" }),
      0,
    ];
  },

  addNodeView() {
    return ({ node, view, getPos }) => new ColumnsView(node, view, getPos);
  },

  addCommands() {
    return {
      insertColumns:
        (count) =>
        ({ chain }) =>
          chain()
            .insertContent({
              type: this.name,
              content: Array.from({ length: count }, () => ({ type: "column", content: [{ type: "paragraph" }] })),
            })
            // 넣은 뒤 커서는 마지막 단에 있으므로 첫 단의 첫 문단으로 옮긴다 (단·단·문단 여는 위치 +3).
            .command(({ tr }) => {
              const found = parentColumns(tr.selection);
              if (found) tr.setSelection(TextSelection.create(tr.doc, found.pos + 3));
              return true;
            })
            .run(),

      setColumnWidths:
        (ratio) =>
        ({ state, tr, dispatch }) => {
          const found = parentColumns(state.selection);
          if (!found || (ratio && ratio.length !== found.node.childCount)) return false;
          if (dispatch) {
            // 너비는 합이 100인 정수 비율로 저장한다 (서버 규칙: 5~95).
            const total = ratio?.reduce((a, b) => a + b, 0) ?? 0;
            found.node.forEach((child, offset, i) => {
              const width = ratio ? Math.round((ratio[i] / total) * 100) : null;
              tr.setNodeMarkup(found.pos + 1 + offset, undefined, { ...child.attrs, width });
            });
          }
          return true;
        },

      addColumn:
        () =>
        ({ state, tr, dispatch }) => {
          const found = parentColumns(state.selection);
          if (!found || found.node.childCount >= 4) return false;
          if (dispatch) {
            const column = state.schema.nodes.column.create(null, state.schema.nodes.paragraph.create());
            tr.insert(found.pos + found.node.nodeSize - 1, column);
            resetWidths(tr, found.pos);
          }
          return true;
        },

      removeColumn:
        () =>
        ({ state, tr, dispatch, commands }) => {
          const columns = parentColumns(state.selection);
          const column = parentColumn(state.selection);
          if (!columns || !column) return false;
          // 두 단 중 하나를 빼면 단 나누기가 의미 없으므로 풀어 버린다.
          if (columns.node.childCount <= 2) return commands.unsetColumns();
          if (dispatch) {
            tr.delete(column.pos, column.pos + column.node.nodeSize);
            resetWidths(tr, columns.pos);
          }
          return true;
        },

      unsetColumns:
        () =>
        ({ state, tr, dispatch }) => {
          const found = parentColumns(state.selection);
          if (!found) return false;
          if (dispatch) {
            const blocks: PMNode[] = [];
            found.node.forEach((column) => column.forEach((block) => blocks.push(block)));
            tr.replaceWith(found.pos, found.pos + found.node.nodeSize, Fragment.fromArray(blocks));
          }
          return true;
        },
    };
  },
});

function resetWidths(tr: Transaction, pos: number) {
  const node = tr.doc.nodeAt(pos);
  node?.forEach((child, offset) => tr.setNodeMarkup(pos + 1 + offset, undefined, { ...child.attrs, width: null }));
}

// --- 이미지 ------------------------------------------------------------------------

const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];

// 이미지를 서버에 올리고 본문에 넣을 주소(/api/assets/...)를 받는다.
// 이미지를 이미지 자료실에 올리고 본문에 넣을 주소(/api/assets/...)를 받는다.
export async function uploadImage(file: File): Promise<string> {
  return (await uploadLibraryImage(file)).url;
}

export function pickImageFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = IMAGE_TYPES.join(",");
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.click();
  });
}

export const RichImage = Image.configure({
  inline: false,
  allowBase64: false,
  resize: { enabled: true, alwaysPreserveAspectRatio: true, minWidth: 40, minHeight: 20 },
});

// 이미지를 붙여 넣거나 끌어다 놓으면 올려서 넣는다.
export const ImagePaste = Extension.create({
  name: "imagePaste",
  addProseMirrorPlugins() {
    const insertFiles = (view: EditorView, files: File[], pos?: number) => {
      const images = files.filter((f) => IMAGE_TYPES.includes(f.type));
      if (!images.length || !view.editable) return false;
      void (async () => {
        for (const file of images) {
          try {
            const src = await uploadImage(file);
            const node = view.state.schema.nodes.image.create({ src });
            const tr = view.state.tr;
            if (pos !== undefined) tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(pos, tr.doc.content.size))));
            // 문단 한가운데여도 문단을 나눠 이미지 블록을 넣는다.
            view.dispatch(tr.replaceSelectionWith(node));
          } catch (e) {
            window.alert((e as Error).message);
          }
        }
      })();
      return true;
    };
    return [
      new Plugin({
        key: new PluginKey("imagePaste"),
        props: {
          handlePaste: (view, event) => insertFiles(view, Array.from(event.clipboardData?.files ?? [])),
          handleDrop: (view, event) => {
            const files = Array.from((event as DragEvent).dataTransfer?.files ?? []);
            const pos = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos;
            return insertFiles(view, files, pos);
          },
        },
      }),
    ];
  },
});
