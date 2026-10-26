// 줄 처음에서 / 를 입력하면 표·단 나누기·이미지를 넣는 목록을 띄운다. 모양과 키 조작은 {{ 변수 목록과 같다.
import { Extension, type Editor, type Range } from "@tiptap/core";
import { PluginKey } from "@tiptap/pm/state";
import { ReactRenderer } from "@tiptap/react";
import { Suggestion, exitSuggestion, type SuggestionKeyDownProps, type SuggestionProps } from "@tiptap/suggestion";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";

import { pickImageFile, uploadImage } from "./layout";
import { openImagePicker } from "./imagePicker";
import { openTablePicker } from "./tablePicker";

const SLASH_KEY = new PluginKey("slashCommand");

type SlashItem = {
  title: string;
  hint: string;
  // 검색어 (한글·영문)
  keywords: string;
  // 표 칸·단 안에서는 넣을 수 없는 것
  topLevelOnly?: "table" | "columns";
  run: (editor: Editor, range: Range) => void;
};

const ITEMS: SlashItem[] = [
  {
    title: "표",
    hint: "행·열 수를 골라 넣기",
    keywords: "표 테이블 table",
    topLevelOnly: "table",
    run: (editor, range) => {
      editor.chain().focus().deleteRange(range).run();
      openTablePicker(editor);
    },
  },
  {
    title: "2단",
    hint: "두 칸으로 나란히 배치",
    keywords: "2단 단 나누기 columns grid 배치",
    topLevelOnly: "columns",
    run: (editor, range) => editor.chain().focus().deleteRange(range).insertColumns(2).run(),
  },
  {
    title: "3단",
    hint: "세 칸으로 나란히 배치",
    keywords: "3단 단 나누기 columns grid 배치",
    topLevelOnly: "columns",
    run: (editor, range) => editor.chain().focus().deleteRange(range).insertColumns(3).run(),
  },
  {
    title: "이미지",
    hint: "파일 올리기 (붙여 넣기·끌어 놓기도 됩니다). 자료실에도 쌓입니다",
    keywords: "이미지 사진 그림 image 올리기 업로드",
    run: (editor, range) => {
      editor.chain().focus().deleteRange(range).run();
      void (async () => {
        const file = await pickImageFile();
        if (!file) return;
        try {
          const src = await uploadImage(file);
          editor.chain().focus().setImage({ src }).run();
        } catch (e) {
          window.alert((e as Error).message);
        }
      })();
    },
  },
  {
    title: "자료실 이미지",
    hint: "이미지 자료실에서 골라 넣기 (여러 장)",
    keywords: "자료실 이미지 사진 그림 image library",
    run: (editor, range) => {
      editor.chain().focus().deleteRange(range).run();
      openImagePicker(editor);
    },
  },
  {
    title: "제목",
    hint: "큰 제목 (제목 2)",
    keywords: "제목 heading",
    run: (editor, range) => editor.chain().focus().deleteRange(range).setHeading({ level: 2 }).run(),
  },
  {
    title: "글머리 목록",
    hint: "• 목록",
    keywords: "목록 글머리 bullet list",
    run: (editor, range) => editor.chain().focus().deleteRange(range).toggleBulletList().run(),
  },
  {
    title: "번호 목록",
    hint: "1. 목록",
    keywords: "목록 번호 ordered list",
    run: (editor, range) => editor.chain().focus().deleteRange(range).toggleOrderedList().run(),
  },
];

function matchItems(editor: Editor, query: string): SlashItem[] {
  const inCell = editor.isActive("tableCell") || editor.isActive("tableHeader");
  const inColumn = editor.isActive("column");
  const q = query.trim().toLowerCase();
  return ITEMS.filter((item) => {
    if (inCell && item.topLevelOnly) return false; // 표 칸 안에는 표·단을 넣지 않는다
    if (inColumn && item.topLevelOnly === "columns") return false; // 단 안에 단을 넣지 않는다
    return !q || item.keywords.toLowerCase().includes(q) || item.title.includes(q);
  });
}

type ListHandle = { onKeyDown: (props: SuggestionKeyDownProps) => boolean };

const SlashList = forwardRef<ListHandle, SuggestionProps<SlashItem>>(function SlashList(props, ref) {
  const [index, setIndex] = useState(0);
  useEffect(() => setIndex(0), [props.items]);
  const pick = (i: number) => {
    const item = props.items[i];
    if (item) props.command(item);
  };
  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (props.items.length === 0) return false;
      if (event.key === "ArrowDown") {
        setIndex((i) => (i + 1) % props.items.length);
        return true;
      }
      if (event.key === "ArrowUp") {
        setIndex((i) => (i - 1 + props.items.length) % props.items.length);
        return true;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        pick(index);
        return true;
      }
      return false;
    },
  }));
  return (
    <div className="variable-suggest" role="listbox" aria-label="넣기">
      <div className="variable-suggest-title">넣기 {props.query ? `· "${props.query}"` : ""}</div>
      {props.items.length === 0 && <div className="variable-suggest-empty">일치하는 항목이 없습니다</div>}
      {props.items.map((item, i) => (
        <button
          key={item.title}
          type="button"
          role="option"
          aria-selected={i === index}
          className={`variable-suggest-item${i === index ? " is-active" : ""}`}
          onMouseDown={(e) => e.preventDefault()}
          onMouseEnter={() => setIndex(i)}
          onClick={() => pick(i)}
        >
          <span className="label">{item.title}</span>
          <span className="value">{item.hint}</span>
        </button>
      ))}
    </div>
  );
});

export const SlashCommand = Extension.create({
  name: "slashCommand",

  addProseMirrorPlugins() {
    return [
      Suggestion<SlashItem, SlashItem>({
        editor: this.editor,
        pluginKey: SLASH_KEY,
        char: "/",
        startOfLine: true,
        placement: "bottom-start",
        items: ({ editor, query }) => matchItems(editor, query),
        command: ({ editor, range, props }) => props.run(editor, range),
        render: () => {
          let component: ReactRenderer<ListHandle, SuggestionProps<SlashItem>> | null = null;
          let unmount: (() => void) | undefined;
          const close = () => {
            unmount?.();
            unmount = undefined;
            component?.destroy();
            component = null;
          };
          return {
            onStart: (props) => {
              close();
              component = new ReactRenderer(SlashList, { props, editor: props.editor });
              // 위치를 잡는 바깥 요소에 z-index를 줘야 모달 위에 뜬다.
              component.element.classList.add("suggest-popup");
              unmount = props.mount(component.element);
            },
            onUpdate: (props) => component?.updateProps(props),
            onKeyDown: (props) => {
              if (props.event.key === "Escape") {
                exitSuggestion(props.view, SLASH_KEY);
                return true;
              }
              return component?.ref?.onKeyDown(props) ?? false;
            },
            onExit: close,
          };
        },
      }),
    ];
  },
});
