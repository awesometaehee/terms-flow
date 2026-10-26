// 표 크기 고르기: 칸 격자에 마우스를 올려 행×열을 고르거나, 숫자로 직접 넣는다.
// 에디터 커서 아래에 body에 붙여 띄운다 (모달 안 에디터에서도 위에 보이게).
import type { Editor } from "@tiptap/core";
import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";

const GRID_ROWS = 8;
const GRID_COLS = 10;
// 서버 규칙: 칸은 행마다 30개, 행은 300개까지
const MAX_ROWS = 300;
const MAX_COLS = 30;

type Size = { rows: number; cols: number };

function clamp(value: number, max: number): number {
  return Math.min(max, Math.max(1, Math.round(value) || 1));
}

function TablePicker({ onPick, onCancel }: { onPick: (size: Size, header: boolean) => void; onCancel: () => void }) {
  const [hover, setHover] = useState<Size>({ rows: 3, cols: 3 });
  const [header, setHeader] = useState(true);
  const [rowsText, setRowsText] = useState("3");
  const [colsText, setColsText] = useState("3");
  const gridRef = useRef<HTMLDivElement>(null);

  // 격자를 움직이면 숫자 칸도 따라 바뀐다.
  const choose = (size: Size) => {
    setHover(size);
    setRowsText(String(size.rows));
    setColsText(String(size.cols));
  };
  const submit = () => onPick({ rows: clamp(Number(rowsText), MAX_ROWS), cols: clamp(Number(colsText), MAX_COLS) }, header);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const moves: Record<string, Size> = {
      ArrowRight: { rows: hover.rows, cols: Math.min(GRID_COLS, hover.cols + 1) },
      ArrowLeft: { rows: hover.rows, cols: Math.max(1, hover.cols - 1) },
      ArrowDown: { rows: Math.min(GRID_ROWS, hover.rows + 1), cols: hover.cols },
      ArrowUp: { rows: Math.max(1, hover.rows - 1), cols: hover.cols },
    };
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    } else if (e.key === "Enter") {
      e.preventDefault();
      submit();
    } else if (moves[e.key] && e.currentTarget === gridRef.current) {
      e.preventDefault();
      choose(moves[e.key]);
    }
  };

  return (
    <div className="table-picker" role="dialog" aria-label="표 크기 고르기" onKeyDown={onKeyDown}>
      <div className="table-picker-title">
        표 넣기 · <b>{rowsText || "?"}행 × {colsText || "?"}열</b>
      </div>
      <div
        ref={gridRef}
        className="table-picker-grid"
        tabIndex={0}
        style={{ gridTemplateColumns: `repeat(${GRID_COLS}, 18px)` }}
        aria-label="마우스나 방향키로 크기를 고르고 Enter"
      >
        {Array.from({ length: GRID_ROWS * GRID_COLS }, (_, i) => {
          const row = Math.floor(i / GRID_COLS) + 1;
          const col = (i % GRID_COLS) + 1;
          const on = row <= hover.rows && col <= hover.cols;
          return (
            <button
              key={i}
              type="button"
              tabIndex={-1}
              className={`table-picker-cell${on ? " is-on" : ""}${header && row === 1 && on ? " is-header" : ""}`}
              aria-label={`${row}행 ${col}열`}
              onMouseEnter={() => choose({ rows: row, cols: col })}
              onClick={() => onPick({ rows: row, cols: col }, header)}
            />
          );
        })}
      </div>
      <div className="table-picker-inputs">
        <label>
          행 <input type="number" min={1} max={MAX_ROWS} value={rowsText} onChange={(e) => setRowsText(e.target.value)} aria-label="행 수" />
        </label>
        <label>
          열 <input type="number" min={1} max={MAX_COLS} value={colsText} onChange={(e) => setColsText(e.target.value)} aria-label="열 수" />
        </label>
        <label className="table-picker-check">
          <input type="checkbox" checked={header} onChange={(e) => setHeader(e.target.checked)} /> 첫 행 머리글
        </label>
      </div>
      <div className="table-picker-actions">
        <button type="button" className="table-picker-cancel" onClick={onCancel}>
          취소
        </button>
        <button type="button" className="table-picker-ok" onClick={submit}>
          넣기
        </button>
      </div>
      <div className="table-picker-hint">격자보다 큰 표는 숫자로 입력하세요 (행 {MAX_ROWS}·열 {MAX_COLS}까지)</div>
    </div>
  );
}

// 커서 위치 아래에 표 크기 고르기를 연다. 고르면 그 자리에 표를 넣는다.
export function openTablePicker(editor: Editor) {
  const host = document.createElement("div");
  host.className = "table-picker-host";
  host.style.visibility = "hidden"; // 자리를 잡은 뒤 보인다
  document.body.appendChild(host);
  const root = createRoot(host);

  const close = () => {
    document.removeEventListener("mousedown", onOutside, true);
    root.unmount();
    host.remove();
  };
  const onOutside = (e: MouseEvent) => {
    if (!host.contains(e.target as Node)) {
      close();
    }
  };
  document.addEventListener("mousedown", onOutside, true);

  root.render(
    <TablePicker
      onCancel={() => {
        close();
        editor.commands.focus();
      }}
      onPick={({ rows, cols }, header) => {
        close();
        editor.chain().focus().insertTable({ rows, cols, withHeaderRow: header }).run();
      }}
    />,
  );

  // 화면 밖으로 나가지 않게 커서 아래(모자라면 위)에 놓는다. 그려진 뒤 크기와 커서 위치를 잰다.
  requestAnimationFrame(() => {
    const coords = editor.view.coordsAtPos(editor.state.selection.from);
    const box = host.getBoundingClientRect();
    const below = coords.bottom + 6;
    const top = below + box.height > window.innerHeight ? coords.top - box.height - 6 : below;
    host.style.top = `${Math.max(8, top)}px`;
    host.style.left = `${Math.max(8, Math.min(coords.left, window.innerWidth - box.width - 8))}px`;
    host.style.visibility = "";
    // 보이게 한 뒤에 포커스를 준다 (숨긴 요소는 포커스를 받지 못해 방향키·Enter·Esc가 에디터로 간다).
    host.querySelector<HTMLElement>(".table-picker-grid")?.focus();
  });
}
