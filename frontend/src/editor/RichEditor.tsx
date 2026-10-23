// 서식 있는 본문 편집기. 글자를 선택하면 서식 도구 막대가 뜨고, {{ 를 입력하면 변수를 고를 수 있다.
// 줄 처음에서 / 를 입력하면 표·단 나누기·이미지를 넣는다. 표·단·이미지 안에서는 그 도구 막대가 뜬다.
// 저장 형식은 서버(app/richtext.py)가 허용하는 노드·서식만 쓴다.
import "./editor.css";

import { ActionIcon, ColorSwatch, Divider, Group, Menu, Tooltip } from "@mantine/core";
import { Highlight } from "@tiptap/extension-highlight";
import { Table, TableRow } from "@tiptap/extension-table";
import { TextAlign } from "@tiptap/extension-text-align";
import { Color, TextStyle } from "@tiptap/extension-text-style";
import { Placeholder } from "@tiptap/extensions";
import { NodeSelection, PluginKey, type EditorState } from "@tiptap/pm/state";
import { CellSelection } from "@tiptap/pm/tables";
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import { StarterKit } from "@tiptap/starter-kit";
import { useCallback, useContext, useEffect, useMemo, useRef, type RefObject } from "react";

import type { RichDoc } from "../api/client";
import { sameDoc } from "../lib/richdoc";
import { BlockTools } from "./BlockTools";
import { ColorPicker, appendToBody, useBubbleRepair, useEditorActive } from "./bubble";
import { Column, Columns, ImagePaste, RichImage, RichTableCell, RichTableHeader } from "./layout";
import { SlashCommand } from "./slash";
import { Variable, VariableSuggestion, VariablesContext } from "./variables";

const TEXT_COLORS = ["#111111", "#d92d20", "#dc6803", "#039855", "#1570ef", "#6941c6", "#667085"];
const HIGHLIGHTS = ["#fff59d", "#fde68a", "#bbf7d0", "#bfdbfe", "#fbcfe8", "#e5e7eb"];

export const EMPTY_DOC: RichDoc = { type: "doc", content: [{ type: "paragraph" }] };

// BubbleMenu 설정은 렌더링마다 새로 만들면 플러그인이 다시 등록되어 표시 상태를 잃는다. 모듈 상수로 둔다.
const BUBBLE_OPTIONS = { placement: "top-start" } as const;
// 글자를 선택했을 때만 보인다 (이미지 선택은 이미지 도구가 맡는다). 포커스에 따른 숨김은 active가 맡는다.
function shouldShowToolbar({ editor, state }: { editor: Editor; state: EditorState }): boolean {
  return editor.isEditable && !state.selection.empty && !(state.selection instanceof NodeSelection);
}

export function RichEditor({
  content,
  onChange,
  editable = true,
  placeholderVariables = true,
  resetKey,
}: {
  // 처음 보여 줄 본문. 이후 바뀐 content는 resetKey가 바뀔 때만 에디터에 반영한다.
  content: RichDoc;
  onChange?: (doc: RichDoc) => void;
  editable?: boolean;
  placeholderVariables?: boolean;
  // 바깥에서 본문을 통째로 바꿀 때(원본으로 되돌리기·새 버전 적용·편집 취소) 바꾸는 값
  resetKey?: string | number;
}) {
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  // 변수 목록은 화면에서 바뀔 수 있으므로 에디터 확장에는 ref를 읽는 함수로 넘긴다.
  const variables = useContext(VariablesContext);
  const variablesRef = useRef(variables);
  variablesRef.current = variables;
  const getVariables = () => (placeholderVariables ? Object.values(variablesRef.current) : []);
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        code: false,
        codeBlock: false,
        blockquote: false,
        horizontalRule: false,
        link: { openOnClick: false, autolink: true, protocols: ["http", "https", "mailto"] },
      }),
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      Variable.configure({ getVariables }),
      VariableSuggestion.configure({ getVariables }),
      Table.configure({ resizable: true, cellMinWidth: 40, lastColumnResizable: false }),
      TableRow,
      RichTableHeader,
      RichTableCell,
      Columns,
      Column,
      RichImage,
      ImagePaste,
      SlashCommand,
      Placeholder.configure({
        placeholder: "내용을 입력하세요 — {{ 변수 넣기 · 줄 처음에서 / 표·단 나누기·이미지",
      }),
    ],
    content,
    editable,
    immediatelyRender: true,
    onUpdate: ({ editor: e }) => onChangeRef.current?.(e.getJSON() as RichDoc),
  });

  // 입력 중에는 부모가 내려주는 content를 에디터에 다시 넣지 않는다. 빠르게 입력하면 content가
  // 한두 글자 늦게 도착해, 이를 다시 넣으면 방금 입력한 글자가 사라지거나 중복되기 때문이다.
  // 바깥에서 본문을 바꿀 때는 부모가 resetKey를 바꾸고, 그때만 content로 교체한다.
  const contentRef = useRef(content);
  contentRef.current = content;
  useEffect(() => {
    if (!editor) return;
    if (!sameDoc(editor.getJSON(), contentRef.current)) {
      editor.commands.setContent(contentRef.current, { emitUpdate: false });
    }
  }, [editor, resetKey]);

  useEffect(() => {
    editor?.setEditable(editable);
  }, [editor, editable]);

  if (!editor) return null;
  return (
    <div className={`rich-editor${editable ? "" : " is-readonly"}`}>
      {editable && <EditorTools editor={editor} />}
      <EditorContent editor={editor} />
    </div>
  );
}

// 서식 막대와 표·단·이미지 도구. 둘 중 어느 막대를 눌러도 에디터가 '사용 중'으로 남는다.
function EditorTools({ editor }: { editor: Editor }) {
  const textRef = useRef<HTMLDivElement>(null);
  const blockRef = useRef<HTMLDivElement>(null);
  const active = useEditorActive(editor, [textRef, blockRef]);
  return (
    <>
      <Toolbar editor={editor} active={active} toolbarRef={textRef} />
      <BlockTools editor={editor} active={active} toolbarRef={blockRef} />
    </>
  );
}

function Toolbar({
  editor,
  active,
  toolbarRef,
}: {
  editor: Editor;
  active: boolean;
  toolbarRef: RefObject<HTMLDivElement | null>;
}) {
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      underline: e.isActive("underline"),
      strike: e.isActive("strike"),
      bullet: e.isActive("bulletList"),
      ordered: e.isActive("orderedList"),
      link: e.isActive("link"),
      heading: ([1, 2, 3] as const).find((level) => e.isActive("heading", { level })) ?? 0,
      align: (["left", "center", "right", "justify"] as const).find((a) => e.isActive({ textAlign: a })) ?? "left",
      color: (e.getAttributes("textStyle").color as string | undefined) ?? null,
      highlight: (e.getAttributes("highlight").color as string | undefined) ?? null,
    }),
  });
  const chain = () => editor.chain().focus();
  const pluginKey = useMemo(() => new PluginKey(`bubbleMenu-${Math.random().toString(36).slice(2)}`), []);
  const hostRef = useBubbleRepair(editor, pluginKey, shouldShowToolbar);
  // 표 칸 여러 개를 골랐을 때는 칸을 가리지 않도록 표 위쪽에 띄운다. (그 밖에는 선택한 글자 위)
  const anchor = useCallback(() => {
    const { selection } = editor.state;
    if (!(selection instanceof CellSelection)) return null;
    const cell = editor.view.nodeDOM(selection.$anchorCell.pos) as HTMLElement | null;
    const table = cell?.closest("table");
    if (!table) return null;
    return {
      getBoundingClientRect: () => {
        const rect = table.getBoundingClientRect();
        return new DOMRect(rect.left, Math.max(rect.top, 64), rect.width, 0);
      },
    };
  }, [editor]);

  const btn = (label: string, on: boolean, onClick: () => void, text: string) => (
    <Tooltip label={label} withinPortal={false}>
      <ActionIcon
        variant={on ? "filled" : "subtle"}
        color={on ? "indigo" : "gray"}
        c={on ? undefined : "gray.2"}
        size="sm"
        onMouseDown={(e) => e.preventDefault()}
        onClick={onClick}
        aria-label={label}
      >
        <span style={{ fontSize: 13, fontWeight: 600 }}>{text}</span>
      </ActionIcon>
    </Tooltip>
  );
  const setLink = () => {
    const previous = editor.getAttributes("link").href as string | undefined;
    const url = window.prompt("링크 주소 (http://, https://, mailto:)", previous ?? "https://");
    if (url === null) return;
    if (url === "") chain().extendMarkRange("link").unsetLink().run();
    else if (/^(https?:\/\/|mailto:)/i.test(url)) chain().extendMarkRange("link").setLink({ href: url }).run();
    else window.alert("http(s):// 또는 mailto: 로 시작해야 합니다.");
  };

  return (
    <BubbleMenu
      ref={hostRef}
      editor={editor}
      pluginKey={pluginKey}
      options={BUBBLE_OPTIONS}
      appendTo={appendToBody}
      getReferencedVirtualElement={anchor}
      className="bubble-host"
      shouldShow={shouldShowToolbar}
    >
      <Group gap={2} wrap="nowrap" ref={toolbarRef} className={`bubble-toolbar${active ? "" : " is-hidden"}`}>
        <Menu withinPortal={false} position="bottom-start" trapFocus={false} returnFocus={false}>
          <Menu.Target>
            <ActionIcon variant="subtle" c="gray.2" size="sm" w={44} onMouseDown={(e) => e.preventDefault()}>
              <span style={{ fontSize: 12, fontWeight: 700 }}>{state.heading ? `H${state.heading}` : "P"} ▾</span>
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => chain().setParagraph().run()}>본문</Menu.Item>
            {([1, 2, 3] as const).map((level) => (
              <Menu.Item key={level} onClick={() => chain().setHeading({ level }).run()}>
                제목 {level}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
        <Divider orientation="vertical" color="dark.4" />
        {btn("굵게", state.bold, () => chain().toggleBold().run(), "B")}
        {btn("기울임", state.italic, () => chain().toggleItalic().run(), "I")}
        {btn("밑줄", state.underline, () => chain().toggleUnderline().run(), "U")}
        {btn("취소선", state.strike, () => chain().toggleStrike().run(), "S")}
        <Divider orientation="vertical" color="dark.4" />
        <ColorPicker
          label="글자 색"
          colors={TEXT_COLORS}
          current={state.color}
          swatch={<span style={{ fontWeight: 700, borderBottom: `3px solid ${state.color ?? "#e5e7eb"}` }}>A</span>}
          onPick={(c) => (c ? chain().setColor(c).run() : chain().unsetColor().run())}
        />
        <ColorPicker
          label="형광펜"
          colors={HIGHLIGHTS}
          current={state.highlight}
          swatch={<ColorSwatch color={state.highlight ?? "#fff59d"} size={14} />}
          onPick={(c) => (c ? chain().setHighlight({ color: c }).run() : chain().unsetHighlight().run())}
        />
        <Divider orientation="vertical" color="dark.4" />
        {btn("왼쪽 정렬", state.align === "left", () => chain().setTextAlign("left").run(), "⇤")}
        {btn("가운데 정렬", state.align === "center", () => chain().setTextAlign("center").run(), "≡")}
        {btn("오른쪽 정렬", state.align === "right", () => chain().setTextAlign("right").run(), "⇥")}
        {btn("양쪽 정렬", state.align === "justify", () => chain().setTextAlign("justify").run(), "☰")}
        <Divider orientation="vertical" color="dark.4" />
        {btn("글머리 기호", state.bullet, () => chain().toggleBulletList().run(), "•")}
        {btn("번호 목록", state.ordered, () => chain().toggleOrderedList().run(), "1.")}
        {btn("들여쓰기", false, () => chain().sinkListItem("listItem").run(), "→")}
        {btn("내어쓰기", false, () => chain().liftListItem("listItem").run(), "←")}
        <Divider orientation="vertical" color="dark.4" />
        {btn("링크", state.link, setLink, "🔗")}
      </Group>
    </BubbleMenu>
  );
}
