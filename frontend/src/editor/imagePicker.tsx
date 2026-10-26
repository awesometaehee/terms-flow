// 자료실에서 이미지 고르기: 여러 장을 고르면 고른 순서대로 커서 자리에 넣는다.
import type { Editor } from "@tiptap/core";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { type LibraryImage, listLibraryImages } from "../lib/images";

function ImagePickerDialog({ onInsert, onClose }: { onInsert: (images: LibraryImage[]) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [images, setImages] = useState<LibraryImage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<LibraryImage[]>([]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      listLibraryImages(q).then(setImages, (e: Error) => setError(e.message));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [q]);

  const toggle = (img: LibraryImage) =>
    setPicked((list) => (list.some((p) => p.id === img.id) ? list.filter((p) => p.id !== img.id) : [...list, img]));
  const order = (img: LibraryImage) => picked.findIndex((p) => p.id === img.id) + 1;

  return (
    <div className="pdf-import-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="pdf-import" role="dialog" aria-label="자료실에서 이미지 고르기" onKeyDown={(e) => e.key === "Escape" && onClose()}>
        <div className="pdf-import-head">
          <b>자료실에서 이미지 고르기</b>
          <input
            className="image-picker-search"
            placeholder="이름으로 찾기"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus
            aria-label="이름으로 찾기"
          />
          <button type="button" className="pdf-import-x" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>
        <div className="pdf-import-body">
          {error && <div className="pdf-import-msg is-error">{error}</div>}
          {!images && !error && <div className="pdf-import-msg">불러오는 중…</div>}
          {images && images.length === 0 && (
            <div className="pdf-import-msg">{q ? "찾는 이미지가 없습니다." : "자료실에 이미지가 없습니다. 왼쪽 메뉴 [이미지]에서 올리세요."}</div>
          )}
          {images && images.length > 0 && (
            <div className="image-picker-grid">
              {images.map((img) => (
                <button
                  key={img.id}
                  type="button"
                  className={`image-picker-item${order(img) ? " is-picked" : ""}`}
                  onClick={() => toggle(img)}
                  aria-pressed={!!order(img)}
                  title={img.name}
                >
                  <span className="image-picker-thumb">
                    <img src={img.url} alt={img.name} loading="lazy" />
                    {order(img) > 0 && <span className="image-picker-order">{order(img)}</span>}
                  </span>
                  <span className="image-picker-name">{img.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="pdf-import-actions">
          <button type="button" onClick={onClose}>
            취소
          </button>
          <button type="button" className="is-primary" disabled={picked.length === 0} onClick={() => onInsert(picked)}>
            {picked.length ? `${picked.length}장 넣기` : "이미지를 고르세요"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function openImagePicker(editor: Editor) {
  const at = editor.state.selection.from;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const close = () => {
    root.unmount();
    host.remove();
  };
  root.render(
    <ImagePickerDialog
      onClose={() => {
        close();
        editor.commands.focus();
      }}
      onInsert={(images) => {
        close();
        editor
          .chain()
          .focus(at)
          .insertContent(images.map((img) => ({ type: "image", attrs: { src: img.url, alt: img.name } })))
          .run();
      }}
    />,
  );
}
