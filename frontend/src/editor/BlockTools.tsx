// 표·단·이미지 안에 있을 때 그 아래에 뜨는 도구 막대 (행·열 추가/삭제, 칸 합치기, 칸 색, 단 비율, 이미지 크기).
import { ActionIcon, Divider, Group, Tooltip } from "@mantine/core";
import { findParentNode } from "@tiptap/core";
import { NodeSelection, PluginKey, type EditorState } from "@tiptap/pm/state";
import { useEditorState, type Editor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import { Fragment, useCallback, useMemo, type ReactNode, type RefObject } from "react";

import { ColorPicker, appendToBody, useBubbleRepair } from "./bubble";

const CELL_COLORS = ["#d9e2f3", "#e2efda", "#fff2cc", "#fce4d6", "#ededed", "#f2f2f2", "#1f3864"];
const TOOLS_OPTIONS = { placement: "bottom-start", offset: 6 } as const;

// 단 비율 버튼: 누르면 setColumnWidths로 합 100인 정수 비율이 저장된다.
const RATIOS: Record<number, { label: string; ratio: number[] | null; tip: string }[]> = {
  2: [
    { label: "5:5", ratio: null, tip: "같은 너비" },
    { label: "7:3", ratio: [7, 3], tip: "왼쪽 넓게 (7:3)" },
    { label: "3:7", ratio: [3, 7], tip: "오른쪽 넓게 (3:7)" },
    { label: "2:1", ratio: [2, 1], tip: "왼쪽 넓게 (2:1)" },
    { label: "1:2", ratio: [1, 2], tip: "오른쪽 넓게 (1:2)" },
  ],
  3: [
    { label: "1:1:1", ratio: null, tip: "같은 너비" },
    { label: "1:2:1", ratio: [1, 2, 1], tip: "가운데 넓게" },
  ],
};

// 저장되는 값과 같은 방식으로 계산한 너비 ("70,30"; 같은 너비는 "")
function ratioKey(ratio: number[] | null): string {
  if (!ratio) return "";
  const total = ratio.reduce((a, b) => a + b, 0);
  return ratio.map((r) => Math.round((r / total) * 100)).join(",");
}

function imageSelected(state: EditorState): boolean {
  return state.selection instanceof NodeSelection && state.selection.node.type.name === "image";
}

export function shouldShowBlockTools({ editor, state }: { editor: Editor; state: EditorState }): boolean {
  return editor.isEditable && (editor.isActive("table") || editor.isActive("columns") || imageSelected(state));
}

const parentTable = findParentNode((node) => node.type.name === "table");
const parentColumns = findParentNode((node) => node.type.name === "columns");

// 표의 모든 행 높이: "even"이면 지금 표 전체 높이를 행 수로 똑같이 나눈다(전체 높이는 그대로).
// null이면 높이 지정을 지운다(내용에 맞춤).
function setAllRowHeights(editor: Editor, mode: "even" | null) {
  const { state, view } = editor;
  const table = parentTable(state.selection);
  if (!table) return;
  let value: number | null = null;
  if (mode === "even") {
    const dom = (view.nodeDOM(table.pos) as HTMLElement | null)?.querySelector("table");
    const rows = dom ? Array.from(dom.rows) : [];
    if (!rows.length) return;
    const total = rows.reduce((sum, r) => sum + r.getBoundingClientRect().height, 0);
    value = Math.max(16, Math.round(total / rows.length));
  }
  const tr = state.tr;
  table.node.forEach((child, offset) => {
    tr.setNodeMarkup(table.pos + 1 + offset, undefined, { ...child.attrs, height: value });
  });
  view.dispatch(tr);
  view.focus();
}

// 막대를 붙일 요소: 고른 이미지, 아니면 가장 안쪽의 표 또는 단 묶음
function anchorElement(editor: Editor): HTMLElement | null {
  const { state, view } = editor;
  if (imageSelected(state)) return view.nodeDOM(state.selection.from) as HTMLElement | null;
  const table = parentTable(state.selection);
  const columns = parentColumns(state.selection);
  const inner = table && (!columns || table.depth > columns.depth) ? table : columns;
  return inner ? (view.nodeDOM(inner.pos) as HTMLElement | null) : null;
}

export function BlockTools({
  editor,
  active,
  toolbarRef,
}: {
  editor: Editor;
  active: boolean;
  toolbarRef: RefObject<HTMLDivElement | null>;
}) {
  const pluginKey = useMemo(() => new PluginKey(`blockTools-${Math.random().toString(36).slice(2)}`), []);
  const hostRef = useBubbleRepair(editor, pluginKey, shouldShowBlockTools);
  // 요소 아래에 붙이되, 요소가 화면 아래로 넘치면 화면 아래쪽에 머문다.
  const anchor = useCallback(() => {
    const el = anchorElement(editor);
    if (!el) return null;
    return {
      getBoundingClientRect: () => {
        const rect = el.getBoundingClientRect();
        const bottom = Math.min(rect.bottom, window.innerHeight - 56);
        return new DOMRect(rect.left, bottom, rect.width, 0);
      },
    };
  }, [editor]);

  const s = useEditorState({
    editor,
    selector: ({ editor: e }) => {
      const cell = e.isActive("tableHeader") ? "tableHeader" : "tableCell";
      const columns = parentColumns(e.state.selection);
      return {
        table: e.isActive("table"),
        header: e.isActive("tableHeader"),
        canMerge: e.can().mergeCells(),
        canSplit: e.can().splitCell(),
        background: (e.getAttributes(cell).background as string | undefined) ?? null,
        columns: columns?.node.childCount ?? 0,
        // 지금 단 너비 ("70,30"; 너비가 없으면 "")
        columnWidths: (() => {
          const widths: number[] = [];
          columns?.node.forEach((c) => widths.push(Number(c.attrs.width) || 0));
          return widths.every((w) => !w) ? "" : widths.join(",");
        })(),
        image: imageSelected(e.state),
      };
    },
  });
  const chain = () => editor.chain().focus();

  const btn = (
    label: string,
    onClick: () => void,
    text: ReactNode,
    opts: { disabled?: boolean; danger?: boolean; on?: boolean } = {},
  ) => (
    <Tooltip label={label} withinPortal={false}>
      <ActionIcon
        variant={opts.on ? "filled" : "subtle"}
        color={opts.on ? "indigo" : "gray"}
        c={opts.on ? undefined : opts.disabled ? "dark.3" : opts.danger ? "red.4" : "gray.2"}
        size="sm"
        miw={28}
        w="auto"
        px={4}
        disabled={opts.disabled}
        onMouseDown={(e) => e.preventDefault()}
        onClick={onClick}
        aria-label={label}
      >
        <span style={{ fontSize: 12, fontWeight: 600, whiteSpace: "nowrap" }}>{text}</span>
      </ActionIcon>
    </Tooltip>
  );
  const sep = <Divider orientation="vertical" color="dark.4" />;
  const setWidth = (width: number | null) => chain().updateAttributes("image", { width, height: null }).run();

  return (
    <BubbleMenu
      ref={hostRef}
      editor={editor}
      pluginKey={pluginKey}
      options={TOOLS_OPTIONS}
      appendTo={appendToBody}
      getReferencedVirtualElement={anchor}
      className="bubble-host"
      shouldShow={shouldShowBlockTools}
    >
      <Group gap={2} wrap="wrap" ref={toolbarRef} className={`bubble-toolbar block-tools${active ? "" : " is-hidden"}`}>
        {s.table && (
          <>
            <span className="tools-label">표</span>
            {btn("위에 행 추가", () => chain().addRowBefore().run(), "↑행")}
            {btn("아래에 행 추가", () => chain().addRowAfter().run(), "↓행")}
            {btn("왼쪽에 열 추가", () => chain().addColumnBefore().run(), "←열")}
            {btn("오른쪽에 열 추가", () => chain().addColumnAfter().run(), "→열")}
            {sep}
            {btn("행 삭제", () => chain().deleteRow().run(), "행−", { danger: true })}
            {btn("열 삭제", () => chain().deleteColumn().run(), "열−", { danger: true })}
            {sep}
            {btn("칸 합치기 (여러 칸을 끌어 고른 뒤)", () => chain().mergeCells().run(), "합치기", { disabled: !s.canMerge })}
            {btn("칸 나누기", () => chain().splitCell().run(), "나누기", { disabled: !s.canSplit })}
            {btn(s.header ? "보통 칸으로" : "머리글 칸으로 (굵게·가운데)", () => chain().toggleHeaderCell().run(), s.header ? "머리글 해제" : "머리글")}
            <ColorPicker
              label="칸 배경색"
              colors={CELL_COLORS}
              current={s.background}
              swatch={<span className="cell-swatch" style={{ background: s.background ?? "transparent" }} />}
              onPick={(c) => chain().setCellAttribute("background", c).run()}
            />
            {sep}
            {btn("표 전체 높이는 그대로 두고 행 높이를 똑같이 나누기 (행 아래 선 끌기: 그 행만, Shift+끌기: 모든 행)", () => setAllRowHeights(editor, "even"), "행 높이 같게")}
            {btn("행 높이 지정 지우기 (내용에 맞춤)", () => setAllRowHeights(editor, null), "높이 초기화")}
            {sep}
            {btn("표 삭제", () => window.confirm("표를 통째로 지울까요?") && chain().deleteTable().run(), "표 삭제", { danger: true })}
          </>
        )}
        {s.columns > 0 && (
          <>
            {s.table && sep}
            <span className="tools-label">{s.columns}단 · 비율</span>
            {(RATIOS[s.columns] ?? []).map((r) => (
              <Fragment key={r.label}>
                {btn(r.tip, () => chain().setColumnWidths(r.ratio).run(), r.label, {
                  on: ratioKey(r.ratio) === s.columnWidths,
                })}
              </Fragment>
            ))}
            {sep}
            {btn("단 추가", () => chain().addColumn().run(), "단+", { disabled: s.columns >= 4 })}
            {btn("지금 단 빼기", () => chain().removeColumn().run(), "단−", { danger: true })}
            {btn("단 나누기 해제 (내용은 위아래로 이어 붙임)", () => chain().unsetColumns().run(), "해제")}
          </>
        )}
        {s.image && (
          <>
            <span className="tools-label">이미지</span>
            {btn("작게 (160px)", () => setWidth(160), "작게")}
            {btn("보통 (320px)", () => setWidth(320), "보통")}
            {btn("크게 (480px)", () => setWidth(480), "크게")}
            {btn("원래 크기 (칸 너비 안에서)", () => setWidth(null), "원래")}
            {sep}
            {btn("이미지 삭제", () => chain().deleteSelection().run(), "삭제", { danger: true })}
          </>
        )}
      </Group>
    </BubbleMenu>
  );
}
