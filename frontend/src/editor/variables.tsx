// 변수 칩: 본문 안의 [서비스명] 같은 값 자리. JSON은 {type: "variable", attrs: {key}}로 서버와 같다.
// 넣는 방법: 본문에서 {{ 를 입력해 목록에서 고르거나, {{키}} 를 끝까지 입력한다.
import { Extension, InputRule, Node, mergeAttributes } from "@tiptap/core";
import { PluginKey } from "@tiptap/pm/state";
import { NodeViewWrapper, ReactNodeViewRenderer, ReactRenderer, type ReactNodeViewProps } from "@tiptap/react";
import { Suggestion, exitSuggestion, type SuggestionKeyDownProps, type SuggestionProps } from "@tiptap/suggestion";
import { createContext, forwardRef, useContext, useEffect, useImperativeHandle, useState } from "react";

export type VariableInfo = { key: string; label: string; value?: string | null };

// 에디터 밖(문서 화면)에서 변수 이름·값을 내려준다. 값이 있으면 칩에 값을 함께 보여 준다.
export const VariablesContext = createContext<Record<string, VariableInfo>>({});

function VariableChip({ node, selected }: ReactNodeViewProps) {
  const variables = useContext(VariablesContext);
  const key = String(node.attrs.key);
  const info = variables[key];
  const label = info?.label ?? key;
  return (
    <NodeViewWrapper
      as="span"
      className={`var-chip${selected ? " is-selected" : ""}${info?.value ? "" : " is-empty"}`}
      title={info?.value ? `${label}: ${info.value}` : `${label} (값 없음)`}
      data-variable={key}
    >
      [{info?.value || label}]
    </NodeViewWrapper>
  );
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    variable: { insertVariable: (key: string) => ReturnType };
  }
}

// {{ 자동완성 플러그인 키 (칩 변환·Esc 때 목록을 닫는 데 쓴다)
const SUGGESTION_KEY = new PluginKey("variableSuggestion");

type VariableOptions = {
  // 현재 쓸 수 있는 변수 목록 (화면에서 바뀔 수 있어 함수로 받는다)
  getVariables: () => VariableInfo[];
};

export const Variable = Node.create<VariableOptions>({
  name: "variable",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addOptions() {
    return { getVariables: () => [] };
  },

  addAttributes() {
    return { key: { default: null } };
  },

  parseHTML() {
    return [{ tag: "span[data-variable]", getAttrs: (el) => ({ key: el.getAttribute("data-variable") }) }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-variable": node.attrs.key }), `[${node.attrs.key}]`];
  },

  renderText({ node }) {
    return `[${node.attrs.key}]`;
  },

  addNodeView() {
    return ReactNodeViewRenderer(VariableChip);
  },

  addCommands() {
    return {
      insertVariable:
        (key) =>
        ({ commands }) =>
          commands.insertContent([{ type: this.name, attrs: { key } }, { type: "text", text: " " }]),
    };
  },

  // {{키}} 를 끝까지 입력하면 등록된 변수일 때 칩으로 바꾼다.
  addInputRules() {
    return [
      new InputRule({
        find: /\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}$/,
        handler: ({ state, range, match }) => {
          const key = match[1];
          if (!this.options.getVariables().some((v) => v.key === key)) return null;
          // 입력한 {{키}} 전체를 칩으로 바꾸고(TipTap nodeInputRule과 같은 방식), 열린 변수 목록도 닫는다.
          const { tr } = state;
          tr.insert(range.from, this.type.create({ key }))
            .delete(tr.mapping.map(range.from), tr.mapping.map(range.to))
            .setMeta(SUGGESTION_KEY, { exit: true });
        },
      }),
    ];
  },
});

// --- {{ 입력 시 변수 고르기 ---------------------------------------------------------

function matchVariables(variables: VariableInfo[], query: string): VariableInfo[] {
  const q = query.trim().toLowerCase();
  return variables
    .filter((v) => !q || v.label.toLowerCase().includes(q) || v.key.toLowerCase().includes(q))
    .slice(0, 12);
}

type ListHandle = { onKeyDown: (props: SuggestionKeyDownProps) => boolean };

const VariableList = forwardRef<ListHandle, SuggestionProps<VariableInfo>>(function VariableList(props, ref) {
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
    <div className="variable-suggest" role="listbox" aria-label="변수 고르기">
      <div className="variable-suggest-title">변수 넣기 {props.query ? `· "${props.query}"` : ""}</div>
      {props.items.length === 0 && <div className="variable-suggest-empty">일치하는 변수가 없습니다</div>}
      {props.items.map((v, i) => (
        <button
          key={v.key}
          type="button"
          role="option"
          aria-selected={i === index}
          className={`variable-suggest-item${i === index ? " is-active" : ""}`}
          onMouseDown={(e) => e.preventDefault()}
          onMouseEnter={() => setIndex(i)}
          onClick={() => pick(i)}
        >
          <span className="label">[{v.label}]</span>
          <span className="key">{v.key}</span>
          {v.value && <span className="value">{v.value}</span>}
        </button>
      ))}
    </div>
  );
});

export const VariableSuggestion = Extension.create<VariableOptions>({
  name: "variableSuggestion",

  addOptions() {
    return { getVariables: () => [] };
  },

  addProseMirrorPlugins() {
    return [
      Suggestion<VariableInfo, VariableInfo>({
        editor: this.editor,
        pluginKey: SUGGESTION_KEY,
        char: "{{",
        // 글자 바로 뒤에서도 {{ 로 시작할 수 있게 한다 (기본값은 공백 뒤에서만).
        allowedPrefixes: null,
        placement: "bottom-start",
        items: ({ query }) => matchVariables(this.options.getVariables(), query.replace(/\}+$/, "")),
        command: ({ editor, range, props }) => {
          editor.chain().focus().deleteRange(range).insertVariable(props.key).run();
        },
        render: () => {
          let component: ReactRenderer<ListHandle, SuggestionProps<VariableInfo>> | null = null;
          let unmount: (() => void) | undefined;
          // {{키}} 가 칩으로 바뀌는 순간처럼 종료 없이 다시 시작되는 경우가 있어, 이전 목록을 먼저 정리한다.
          const close = () => {
            unmount?.();
            unmount = undefined;
            component?.destroy();
            component = null;
          };
          return {
            onStart: (props) => {
              close();
              component = new ReactRenderer(VariableList, { props, editor: props.editor });
              // 위치를 잡는 바깥 요소에 z-index를 줘야 모달 위에 뜬다.
              component.element.classList.add("suggest-popup");
              unmount = props.mount(component.element);
            },
            onUpdate: (props) => component?.updateProps(props),
            onKeyDown: (props) => {
              if (props.event.key === "Escape") {
                // 이 {{ 는 그대로 글자로 두고 목록만 닫는다.
                exitSuggestion(props.view, SUGGESTION_KEY);
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
