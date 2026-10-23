// 에디터 위에 뜨는 도구 막대(서식 막대·표/단/이미지 도구)가 함께 쓰는 것.
import { ActionIcon, ColorSwatch, Popover, SimpleGrid, Tooltip } from "@mantine/core";
import type { EditorState, PluginKey } from "@tiptap/pm/state";
import type { Editor } from "@tiptap/react";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

// 막대를 body에 붙인다. 기본값(에디터 부모)이면 overflow: hidden인 카드 밖으로 나가는 부분이 잘린다.
export const appendToBody = () => document.body;

type ShouldShow = (props: { editor: Editor; state: EditorState }) => boolean;

// 개발 모드(React StrictMode)에서는 BubbleMenu 플러그인이 등록→해제→재등록되면서, 해제 정리 작업이
// 다음 프레임에 막대 요소를 DOM에서 떼어 낸다. 플러그인은 보이는 상태로 알고 있어 다시 나타나지 않으므로,
// 보여야 하는데 요소가 빠져 있으면 숨김→표시로 되살린다. (운영 빌드에서는 일어나지 않는다.)
export function useBubbleRepair(editor: Editor, pluginKey: PluginKey, shouldShow: ShouldShow) {
  const hostRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const repair = () =>
      requestAnimationFrame(() => {
        const host = hostRef.current;
        if (!host || host.isConnected || editor.isDestroyed) return;
        if (!shouldShow({ editor, state: editor.state })) return;
        editor.view.dispatch(editor.state.tr.setMeta(pluginKey, "hide"));
        editor.view.dispatch(editor.state.tr.setMeta(pluginKey, "show"));
      });
    editor.on("focus", repair);
    editor.on("selectionUpdate", repair);
    return () => {
      editor.off("focus", repair);
      editor.off("selectionUpdate", repair);
    };
  }, [editor, pluginKey, shouldShow]);
  return hostRef;
}

// 포커스가 이 에디터나 그 도구 막대 안에 있을 때만 막대를 보인다.
// (막대 안의 메뉴를 쓴 뒤 바깥을 누르면 에디터는 blur를 받지 못하므로 직접 추적한다.)
export function useEditorActive(editor: Editor, toolbars: RefObject<HTMLElement | null>[]): boolean {
  const [active, setActive] = useState(editor.isFocused);
  const toolbarsRef = useRef(toolbars);
  toolbarsRef.current = toolbars;
  useEffect(() => {
    const inside = (node: EventTarget | null) =>
      node instanceof Node &&
      (editor.view.dom.contains(node) || toolbarsRef.current.some((ref) => ref.current?.contains(node)));
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
  return active;
}

export function ColorPicker({
  label,
  colors,
  current,
  swatch,
  onPick,
}: {
  label: string;
  colors: string[];
  current: string | null;
  swatch: ReactNode;
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
              aria-label={c}
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
