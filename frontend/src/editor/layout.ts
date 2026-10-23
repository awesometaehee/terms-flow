// 표·단 나누기·이미지. JSON 형식은 서버(app/richtext.py)와 같다.
// - 표 칸 안: 문단·제목·목록·이미지 (표 안의 표, 표 안의 단은 넣지 않는다)
// - 단 안: 그 밖에 표도 넣을 수 있다 (단 안의 단은 넣지 않는다)
import { Extension, Node, findParentNode, mergeAttributes } from "@tiptap/core";
import { Image } from "@tiptap/extension-image";
import { TableCell, TableHeader } from "@tiptap/extension-table";
import { Fragment, type Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection, type Transaction } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";

const CELL_CONTENT = "(paragraph | heading | bulletList | orderedList | image)+";
const COLUMN_CONTENT = "(paragraph | heading | bulletList | orderedList | image | table)+";

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
export async function uploadImage(file: File): Promise<string> {
  if (!IMAGE_TYPES.includes(file.type)) throw new Error("PNG·JPG·GIF·WEBP 이미지만 넣을 수 있습니다.");
  const res = await fetch("/api/assets", { method: "POST", body: file, headers: { "Content-Type": file.type } });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.errors?.[0]?.message ?? body?.message ?? "이미지를 올리지 못했습니다.");
  return body.url as string;
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
