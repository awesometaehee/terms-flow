// 서식 있는 본문 편집기. 글자를 선택하면 서식 도구 막대가 뜨고, {{ 를 입력하면 변수를 고를 수 있다.
// 저장 형식은 서버(app/richtext.py)가 허용하는 노드·서식만 쓴다.
import "./editor.css";

import { ActionIcon, ColorSwatch, Divider, Group, Menu, Popover, SimpleGrid, Tooltip } from "@mantine/core";
import { Highlight } from "@tiptap/extension-highlight";
import { TextAlign } from "@tiptap/extension-text-align";
import { Color, TextStyle } from "@tiptap/extension-text-style";
import { Placeholder } from "@tiptap/extensions";
import { PluginKey, type EditorState } from "@tiptap/pm/state";
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import { StarterKit } from "@tiptap/starter-kit";
import { useContext, useEffect, useMemo, useRef, useState } from "react";

import type { RichDoc } from "../api/client";
import { sameDoc } from "../lib/richdoc";
import { Variable, VariableSuggestion, VariablesContext } from "./variables";

const TEXT_COLORS = ["#111111", "#d92d20", "#dc6803", "#039855", "#1570ef", "#6941c6", "#667085"];
const HIGHLIGHTS = ["#fff59d", "#fde68a", "#bbf7d0", "#bfdbfe", "#fbcfe8", "#e5e7eb"];

export const EMPTY_DOC: RichDoc = { type: "doc", content: [{ type: "paragraph" }] };

// BubbleMenu 설정은 렌더링마다 새로 만들면 플러그인이 다시 등록되어 표시 상태를 잃는다. 모듈 상수로 둔다.
const BUBBLE_OPTIONS = { placement: "top-start" } as const;
// 막대를 body에 붙인다. 기본값(에디터 부모)이면 overflow: hidden인 카드 밖으로 나가는 부분이 잘린다.
const appendToBody = () => document.body;

// 글자를 선택했을 때만 보인다. 포커스에 따른 숨김은 Toolbar의 active가 맡는다.
function shouldShowToolbar({ editor, state }: { editor: Editor; state: EditorState }): boolean {
  return editor.isEditable && !state.selection.empty;
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
      Placeholder.configure({ placeholder: "내용을 입력하세요 — {{ 를 입력하면 변수를 넣을 수 있습니다" }),
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
      {editable && <Toolbar editor={editor} />}
      <EditorContent editor={editor} />
    </div>
  );
}

function Toolbar({ editor }: { editor: Editor }) {
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
  const toolbarRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const pluginKey = useMemo(() => new PluginKey(`bubbleMenu-${Math.random().toString(36).slice(2)}`), []);

  // 개발 모드(React StrictMode)에서는 BubbleMenu 플러그인이 등록→해제→재등록되면서, 해제 정리 작업이
  // 다음 프레임에 막대 요소를 DOM에서 떼어 낸다. 플러그인은 보이는 상태로 알고 있어 다시 나타나지 않으므로,
  // 보여야 하는데 요소가 빠져 있으면 숨김→표시로 되살린다. (운영 빌드에서는 일어나지 않는다.)
  useEffect(() => {
    const repair = () =>
      requestAnimationFrame(() => {
        const host = hostRef.current;
        if (!host || host.isConnected || editor.isDestroyed) return;
        if (!shouldShowToolbar({ editor, state: editor.state })) return;
        editor.view.dispatch(editor.state.tr.setMeta(pluginKey, "hide"));
        editor.view.dispatch(editor.state.tr.setMeta(pluginKey, "show"));
      });
    editor.on("focus", repair);
    editor.on("selectionUpdate", repair);
    return () => {
      editor.off("focus", repair);
      editor.off("selectionUpdate", repair);
    };
  }, [editor, pluginKey]);

  // 포커스가 이 에디터나 도구 막대 안에 있을 때만 막대를 보인다.
  // (막대 안의 메뉴를 쓴 뒤 바깥을 누르면 에디터는 blur를 받지 못하므로 직접 추적한다.)
  const [active, setActive] = useState(editor.isFocused);
  useEffect(() => {
    const inside = (node: EventTarget | null) =>
      node instanceof Node && (editor.view.dom.contains(node) || !!toolbarRef.current?.contains(node));
    const onFocus = () => setActive(true);
    const onBlur = ({ event }: { event: FocusEvent }) => {
      if (!inside(event.relatedTarget)) setActive(false);
    };
    const onMouseDown = (event: MouseEvent) => {
      if (!inside(event.target)) setActive(false);
    };
    editor.on("focus", onFocus);
    editor.on("blur", onBlur);
    document.addEventListener("mousedown", onMouseDown, true);
    return () => {
      editor.off("focus", onFocus);
      editor.off("blur", onBlur);
      document.removeEventListener("mousedown", onMouseDown, true);
    };
  }, [editor]);

  const btn = (label: string, active: boolean, onClick: () => void, text: string) => (
    <Tooltip label={label} withinPortal={false}>
      <ActionIcon
        variant={active ? "filled" : "subtle"}
        color={active ? "indigo" : "gray"}
        c={active ? undefined : "gray.2"}
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

function ColorPicker({
  label,
  colors,
  current,
  swatch,
  onPick,
}: {
  label: string;
  colors: string[];
  current: string | null;
  swatch: React.ReactNode;
  onPick: (color: string | null) => void;
}) {
  return (
    <Popover withinPortal={false} position="bottom" shadow="md" trapFocus={false} returnFocus={false}>
      <Popover.Target>
        <Tooltip label={label} withinPortal={false}>
          <ActionIcon variant="subtle" c="gray.2" size="sm" onMouseDown={(e) => e.preventDefault()} aria-label={label}>
            {swatch}
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p={6}>
        <SimpleGrid cols={colors.length + 1} spacing={4}>
          {colors.map((c) => (
            <ColorSwatch
              key={c}
              color={c}
              size={18}
              component="button"
              style={{ cursor: "pointer", outline: c === current ? "2px solid #4f46e5" : undefined }}
              onMouseDown={(e: React.MouseEvent) => e.preventDefault()}
              onClick={() => onPick(c)}
            />
          ))}
          <ActionIcon size={18} variant="default" onMouseDown={(e) => e.preventDefault()} onClick={() => onPick(null)} aria-label="지우기">
            ✕
          </ActionIcon>
        </SimpleGrid>
      </Popover.Dropdown>
    </Popover>
  );
}
