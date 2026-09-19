type Props = { className?: string; title?: string };

// Minimal cloth bag mark. Same drawing as app/icon.svg, without the tile.
export default function BagMark({ className, title }: Props) {
  return (
    <svg viewBox="0 0 48 48" className={className} role={title ? "img" : undefined} aria-hidden={title ? undefined : true}>
      {title ? <title>{title}</title> : null}
      <path d="M17 17c0-5 3.1-9 7-9s7 4 7 9" fill="none" stroke="var(--turmeric)" strokeWidth="3.4" strokeLinecap="round" />
      <path d="M8 17h32l-2.6 22.4A3.6 3.6 0 0 1 33.8 42.6H14.2a3.6 3.6 0 0 1-3.6-3.2z" fill="var(--ink)" />
      <path d="M12 25h24M13 32h22" stroke="var(--cream)" strokeWidth="1.6" strokeLinecap="round" strokeDasharray="2.4 2.6" opacity=".7" />
    </svg>
  );
}
