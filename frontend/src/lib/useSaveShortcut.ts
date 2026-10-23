// Ctrl+S(맥은 Cmd+S)로 저장. 브라우저의 '페이지 저장' 대신 화면의 저장을 실행한다.
import { useEffect, useRef } from "react";

export function useSaveShortcut(save: () => void, enabled: boolean): void {
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (enabled) saveRef.current();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}
