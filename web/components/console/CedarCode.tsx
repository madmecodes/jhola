import type { ReactNode } from "react";

// Tiny Cedar highlighter: tokenises with one regex and colours via CSS classes in globals.css.
const TOKEN =
  /(\/\/[^\n]*)|("(?:[^"\\]|\\.)*")|(@\w+)|\b(permit|forbid|when|unless|principal|action|resource|context|in|has|like|if|then|else|is)\b|\b(true|false)\b|(\b\d+(?:\.\d+)?\b)|(\b[A-Z]\w*(?=::))|(==|!=|&&|\|\||<=|>=|<|>|!)/g;

const CLASSES = ["cd-comment", "cd-string", "cd-annot", "cd-kw", "cd-bool", "cd-num", "cd-type", "cd-op"];

function highlight(src: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(src))) {
    if (m.index > last) out.push(src.slice(last, m.index));
    const group = m.slice(1).findIndex((g) => g !== undefined);
    out.push(
      <span key={i++} className={CLASSES[group]}>
        {m[0]}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < src.length) out.push(src.slice(last));
  return out;
}

export default function CedarCode({ code, className = "" }: { code: string; className?: string }) {
  return (
    <pre className={`cedar overflow-x-auto rounded-xl p-3.5 font-mono text-[12.5px] leading-relaxed ${className}`}>
      <code>{highlight(code)}</code>
    </pre>
  );
}
