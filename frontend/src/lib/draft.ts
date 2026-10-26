// 자동 임시저장: 저장하지 않은 편집 내용을 서버(/api/drafts)에 보관해 다른 PC에서도 이어 쓴다.
// 서버 저장(새 버전)과는 별개다. 다시 열었을 때 남아 있으면 불러올지 묻고, 저장에 성공하면 지운다.
// 로그인이 없어 사람별이 아니라 모듈·문서별 하나다.
import { useCallback, useEffect, useRef, useState } from "react";

const DELAY_MS = 1000;

export type StoredDraft<T> = {
  value: T;
  // 임시본을 만들 때의 서버 상태 (모듈 리비전 번호·문서 lock_version). 다르면 그사이 다른 저장이 있었다.
  base: string;
  savedAt: number;
};

type DraftOut = { key: string; base: string; value: unknown; title: string | null; updated_at: string };

const url = (key: string) => `/api/drafts/${encodeURIComponent(key)}`;

export async function fetchDraft<T>(key: string): Promise<StoredDraft<T> | null> {
  const res = await fetch(url(key));
  if (res.status === 404 || !res.ok) return null;
  const body = (await res.json()) as DraftOut;
  return { value: body.value as T, base: body.base, savedAt: Date.parse(body.updated_at) };
}

// 같은 임시본에 대한 보관·삭제 요청은 보낸 순서대로 처리되게 앞 요청이 끝난 뒤 보낸다.
// (보관 요청이 늦게 도착해 방금 지운 임시본을 되살리는 일을 막는다.)
const queues = new Map<string, Promise<unknown>>();
function inOrder<T>(key: string, send: () => Promise<T>): Promise<T> {
  const previous = queues.get(key) ?? Promise.resolve();
  const next = previous.catch(() => undefined).then(send);
  queues.set(key, next);
  void next.finally(() => queues.get(key) === next && queues.delete(key)).catch(() => undefined);
  return next;
}

type DraftBody = { base: string; value: unknown; title: string | null };

function sendPut(key: string, body: DraftBody, keepalive = false) {
  return fetch(url(key), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive,
  });
}

function putDraft(key: string, body: DraftBody, keepalive = false) {
  return inOrder(key, () => sendPut(key, body, keepalive));
}

export function removeDraft(key: string) {
  return inOrder(key, () => fetch(url(key), { method: "DELETE" })).catch(() => undefined);
}

/**
 * key: 임시본 이름 ("module:<id>", "document:<id>", "module-new:<id>")
 * value: 지금 편집 상태, dirty: 저장하지 않은 변경이 있는지, base: 지금 서버 상태 (불러오기 전이면 null)
 * title: 목록에 보일 이름 (새 모듈)
 *
 * found: 화면을 열 때 남아 있던 임시본 (불러오기·버리기를 고르기 전까지 유지)
 * savedAt: 이번에 마지막으로 임시저장한 시각, failed: 마지막 임시저장이 실패했는지
 */
export function useDraft<T>(
  key: string,
  value: T | null,
  dirty: boolean,
  base: string | null,
  { title = null, check = true }: { title?: string | null; check?: boolean } = {},
) {
  const [found, setFound] = useState<StoredDraft<T> | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const checked = useRef<string | null>(null);
  // 탭을 닫기 직전에 보낼, 아직 보관하지 않은 내용
  const pending = useRef<{ base: string; value: T; title: string | null } | null>(null);
  // 지운(저장 성공·버리기) 그 내용. 저장 직후 화면이 한 번 더 그려질 때 같은 내용을 다시 보관하지 않게 한다.
  const latest = useRef(value);
  latest.current = value;
  const cleared = useRef<string | null>(null);

  // 서버 상태가 준비되면 한 번 남아 있는 임시본을 확인한다.
  useEffect(() => {
    if (!check || base === null || checked.current === key) return;
    checked.current = key;
    let alive = true;
    void fetchDraft<T>(key).then((draft) => alive && setFound(draft));
    return () => {
      alive = false;
    };
  }, [key, base, check]);

  // 바뀐 뒤 잠시 멈추면 보관한다.
  useEffect(() => {
    if (!dirty || value === null || base === null) return;
    if (cleared.current !== null) {
      if (cleared.current === JSON.stringify(value)) return;
      cleared.current = null; // 그 뒤로 새로 고친 내용은 다시 보관한다
    }
    pending.current = { base, value, title };
    const timer = window.setTimeout(() => {
      const body = pending.current;
      if (!body) return;
      putDraft(key, body).then(
        (res) => {
          setFailed(!res.ok);
          if (res.ok) {
            setSavedAt(Date.now());
            if (pending.current === body) pending.current = null;
          }
        },
        () => setFailed(true),
      );
    }, DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [key, value, dirty, base, title]);

  // 탭을 닫거나 다른 주소로 나가면 남은 내용을 바로 보낸다.
  useEffect(() => {
    const flush = () => {
      if (pending.current) {
        const body = pending.current;
        pending.current = null;
        // keepalive: 창이 닫혀도 요청을 끝까지 보낸다. 앞 요청이 없으면 바로 시작된다.
        void putDraft(key, body, true);
      }
    };
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush(); // 화면을 떠날 때(다른 메뉴로 이동·창 닫기)
    };
  }, [key]);

  // 이번에 만든 임시본이 있는데 변경이 없어지면(되돌리기 등) 지운다. 열 때 남아 있던 임시본은 건드리지 않는다.
  useEffect(() => {
    if (!dirty && savedAt !== null) {
      pending.current = null;
      void removeDraft(key);
      setSavedAt(null);
    }
  }, [dirty, savedAt, key]);

  // 저장에 성공했거나 버리기를 고르면 지운다.
  const clear = useCallback(() => {
    pending.current = null;
    cleared.current = JSON.stringify(latest.current);
    setSavedAt(null);
    setFound(null);
    return removeDraft(key);
  }, [key]);
  const dismiss = useCallback(() => setFound(null), []);

  return { found, savedAt, failed, clear, dismiss };
}

export function formatDraftTime(ms: number): string {
  const d = new Date(ms);
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  return sameDay ? time : `${d.toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} ${time}`;
}
