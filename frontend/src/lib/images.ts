// 이미지 자료실 API. 편집기에서 올린 이미지도 자료실에 쌓인다.
export type LibraryImage = {
  id: string;
  name: string;
  // 본문 이미지 노드의 src
  url: string;
  content_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  created_at: string;
};

export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
export const IMAGE_ACCEPT = IMAGE_TYPES.join(",");

async function failure(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null);
  return new Error(body?.errors?.[0]?.message ?? body?.message ?? fallback);
}

export async function uploadLibraryImage(file: File): Promise<LibraryImage> {
  if (!IMAGE_TYPES.includes(file.type)) throw new Error(`${file.name}: PNG·JPG·GIF·WEBP 이미지만 올릴 수 있습니다.`);
  const res = await fetch("/api/images", {
    method: "POST",
    body: file,
    headers: { "Content-Type": file.type, "X-File-Name": encodeURIComponent(file.name) },
  });
  if (!res.ok) throw await failure(res, `${file.name}: 이미지를 올리지 못했습니다.`);
  return (await res.json()) as LibraryImage;
}

export async function listLibraryImages(q = ""): Promise<LibraryImage[]> {
  const res = await fetch(`/api/images${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
  if (!res.ok) throw await failure(res, "이미지 목록을 불러오지 못했습니다.");
  return (await res.json()) as LibraryImage[];
}

export function downloadUrl(image: LibraryImage): string {
  return `/api/images/${image.id}/download`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}
