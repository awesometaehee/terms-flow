// 표·단·이미지 안에 있을 때 그 아래에 뜨는 도구 막대 (행·열 추가/삭제, 칸 합치기, 칸 색, 단 비율, 이미지 크기).
import { ActionIcon, Divider, Group, Tooltip } from "@mantine/core";
import { findParentNode } from "@tiptap/core";
import { NodeSelection, PluginKey, type EditorState } from "@tiptap/pm/state";
import { useEditorState, type Editor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import { useCallback, useMemo, type ReactNode, type RefObject } from "react";

import { ColorPicker, appendToBody, useBubbleRepair } from "./bubble";

const CELL_COLORS = ["#d9e2f3", "#e2efda", "#fff2cc", "#fce4d6", "#ededed", "#f2f2f2", "#1f3864"];
const TOOLS_OPTIONS = { placement: "bottom-start", offset: 6 } as const;

function imageSelected(state: EditorState): boolean {
  return state.selection instanceof NodeSelection && state.selection.node.type.name === "image";
}

export function shouldShowBlockTools({ editor, state }: { editor: Editor; state: EditorState }): boolean {
  return editor.isEditable && (editor.isActive("table") || editor.isActive("columns") || imageSelected(state));
}

const parentTable = findParentNode((node) => node.type.name === "table");
const parentColumns = findParentNode((node) => node.type.name === "columns");

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
        image: imageSelected(e.state),
      };
    },
  });
  const chain = () => editor.chain().focus();

  const btn = (label: string, onClick: () => void, text: ReactNode, opts: { disabled?: boolean; danger?: boolean } = {}) => (
    <Tooltip label={label} withinPortal={false}>
      <ActionIcon
        variant="subtle"
        c={opts.disabled ? "dark.3" : opts.danger ? "red.4" : "gray.2"}
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
            {btn("표 삭제", () => window.confirm("표를 통째로 지울까요?") && chain().deleteTable().run(), "표 삭제", { danger: true })}
          </>
        )}
        {s.columns > 0 && (
          <>
            {s.table && sep}
            <span className="tools-label">{s.columns}단</span>
            {s.columns === 2 && (
              <>
                {btn("같은 너비", () => chain().setColumnWidths(null).run(), "1:1")}
                {btn("오른쪽 넓게", () => chain().setColumnWidths([1, 2]).run(), "1:2")}
                {btn("왼쪽 넓게", () => chain().setColumnWidths([2, 1]).run(), "2:1")}
                {btn("왼쪽 아주 넓게", () => chain().setColumnWidths([7, 3]).run(), "7:3")}
              </>
            )}
            {s.columns === 3 && (
              <>
                {btn("같은 너비", () => chain().setColumnWidths(null).run(), "1:1:1")}
                {btn("가운데 넓게", () => chain().setColumnWidths([1, 2, 1]).run(), "1:2:1")}
              </>
            )}
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
