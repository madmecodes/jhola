type Props = { eyebrow: string; title: string; children?: React.ReactNode; id?: string };

export default function SectionHeading({ eyebrow, title, children, id }: Props) {
  return (
    <div className="max-w-2xl">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-jute">{eyebrow}</p>
      <h2 id={id} className="font-display mt-3 text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
        {title}
      </h2>
      {children ? <p className="mt-4 text-base leading-relaxed text-ink-soft sm:text-lg">{children}</p> : null}
    </div>
  );
}
