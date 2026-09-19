// A handwritten shopping list (parchi) drawn with CSS and a handwriting font.
const lines: { text: string; hi?: boolean; struck?: boolean }[] = [
  { text: "aata 5kg" },
  { text: "doodh 2" },
  { text: "धनिया" , hi: true },
  { text: "aloo 1 kg" },
  { text: "टमाटर आधा किलो", hi: true },
  { text: "arhar dal 1kg" },
  { text: "chawal 5 kg" },
];

export default function Parchi({ className = "" }: { className?: string }) {
  return (
    <div
      className={`ruled relative rounded-[4px] pb-3 pl-8 pr-4 pt-7 shadow-[0_6px_14px_-6px_rgba(31,42,90,0.35)] ${className}`}
      aria-label="Handwritten shopping list: aata 5 kg, doodh 2, dhaniya, aloo 1 kg, tamatar half kilo, arhar dal 1 kg, chawal 5 kg"
      role="img"
    >
      <span className="absolute left-1/2 top-[-7px] h-4 w-12 -translate-x-1/2 rotate-[-3deg] bg-turmeric/55" aria-hidden />
      <p className="font-hand absolute right-3 top-1.5 text-sm text-jute" aria-hidden>
        19/9
      </p>
      <ul className="font-hand text-ink" aria-hidden>
        {lines.map((l) => (
          <li key={l.text} className={`leading-[26px] ${l.hi ? "text-[17px]" : "text-[21px]"}`}>
            {l.text}
          </li>
        ))}
      </ul>
    </div>
  );
}
