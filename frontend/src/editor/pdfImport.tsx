// PDF에서 표 가져오기: PDF를 올리면 서버가 찾은 표를 미리 보여 주고, 고른 표를 커서 자리에 넣는다.
// 현재 / 메뉴에서는 빼 두었다 (기능은 유지). 다시 쓰려면 slash.tsx 항목에서 openPdfImport(editor)를 부른다.
// 표 모양(칸 합치기·배경색·글자색·굵기·칸 안 이미지)은 서버(app/pdf_tables.py)가 만든다.
import type { Editor, JSONContent } from "@tiptap/core";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

type ImportedTable = { page: number; index: number; rows: number; cols: number; content: JSONContent; preview_html: string };

async function analyze(file: File): Promise<ImportedTable[]> {
  const res = await fetch("/api/imports/pdf-tables", { method: "POST", body: file, headers: { "Content-Type": "application/pdf" } });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.errors?.[0]?.message ?? body?.message ?? "PDF를 읽지 못했습니다.");
  return body.tables as ImportedTable[];
}

function PdfImportDialog({
  file,
  onInsert,
  onClose,
}: {
  file: File;
  onInsert: (tables: ImportedTable[]) => void;
  onClose: () => void;
}) {
  const [tables, setTables] = useState<ImportedTable[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<number[]>([]);

  useEffect(() => {
    analyze(file).then(
      (found) => {
        setTables(found);
        setChecked(found.length === 1 ? [found[0].index] : []);
      },
      (e: Error) => setError(e.message),
    );
  }, [file]);

  const toggle = (index: number) =>
    setChecked((list) => (list.includes(index) ? list.filter((i) => i !== index) : [...list, index].sort((a, b) => a - b)));
  const picked = (tables ?? []).filter((t) => checked.includes(t.index));

  return (
    <div className="pdf-import-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className="pdf-import"
        role="dialog"
        aria-label="PDF에서 표 가져오기"
        onKeyDown={(e) => e.key === "Escape" && onClose()}
        tabIndex={-1}
      >
        <div className="pdf-import-head">
          <b>PDF에서 표 가져오기</b>
          <span className="pdf-import-file">{file.name}</span>
          <button type="button" className="pdf-import-x" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>
        <div className="pdf-import-body">
          {!tables && !error && <div className="pdf-import-msg">표를 찾는 중입니다…</div>}
          {error && <div className="pdf-import-msg is-error">{error}</div>}
          {tables && (
            <>
              <div className="pdf-import-msg">
                표 {tables.length}개를 찾았습니다. 넣을 표를 고르세요. 넣은 뒤에는 보통 표처럼 고칠 수 있습니다.
              </div>
              {tables.map((t) => (
                <label key={t.index} className={`pdf-import-item${checked.includes(t.index) ? " is-checked" : ""}`}>
                  <div className="pdf-import-item-head">
                    <input type="checkbox" checked={checked.includes(t.index)} onChange={() => toggle(t.index)} />
                    <span>
                      표 {t.index + 1} · {t.page}쪽 · {t.rows}행 × {t.cols}열
                    </span>
                  </div>
                  {/* 서버가 본문 규칙으로 만든 HTML (글자는 이스케이프됨) */}
                  <div className="pdf-import-preview rich-editor" dangerouslySetInnerHTML={{ __html: t.preview_html }} />
                </label>
              ))}
            </>
          )}
        </div>
        <div className="pdf-import-actions">
          <button type="button" onClick={onClose}>
            취소
          </button>
          <button type="button" className="is-primary" disabled={picked.length === 0} onClick={() => onInsert(picked)}>
            {picked.length ? `${picked.length}개 넣기` : "표를 고르세요"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function pickPdfFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/pdf,.pdf";
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.click();
  });
}

// PDF를 고르게 한 뒤 표 고르기 창을 띄운다. 고른 표는 지금 커서 자리에 순서대로 넣는다.
export async function openPdfImport(editor: Editor) {
  const file = await pickPdfFile();
  if (!file) return;
  const at = editor.state.selection.from;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const close = () => {
    root.unmount();
    host.remove();
  };
  root.render(
    <PdfImportDialog
      file={file}
      onClose={() => {
        close();
        editor.commands.focus();
      }}
      onInsert={(tables) => {
        close();
        const nodes = tables.flatMap((t) => t.content.content ?? []);
        editor.chain().focus(at).insertContent(nodes).run();
      }}
    />,
  );
}
