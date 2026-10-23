// 해시 기반 최소 라우터 (#/products/123). 화면 수가 적어 라우터 라이브러리를 쓰지 않는다.
import { Anchor, type AnchorProps } from "@mantine/core";
import { type ReactNode, useEffect, useState } from "react";

function currentPath(): string {
  return window.location.hash.replace(/^#/, "") || "/documents";
}

export function useRoute(): string[] {
  const [path, setPath] = useState(currentPath);
  useEffect(() => {
    const onChange = () => setPath(currentPath());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return path.split("?")[0].split("/").filter(Boolean);
}

export function useQueryParam(name: string): string | null {
  const query = currentPath().split("?")[1] ?? "";
  return new URLSearchParams(query).get(name);
}

export function navigate(path: string): void {
  window.location.hash = path;
}

export function Link({ to, children, ...props }: { to: string; children: ReactNode } & AnchorProps) {
  return (
    <Anchor href={`#${to}`} {...props}>
      {children}
    </Anchor>
  );
}
