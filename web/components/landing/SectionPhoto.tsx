import Image, { type StaticImageData } from "next/image";

type Props = {
  src: StaticImageData;
  alt: string;
  className?: string;
  tone?: "light" | "dark";
  sizes?: string;
};

// Rounded editorial photo card used beside section headings.
export default function SectionPhoto({ src, alt, className = "", tone = "light", sizes = "(min-width: 1024px) 520px, 100vw" }: Props) {
  const frame = tone === "dark" ? "border-cream/15 bg-cream/[0.04]" : "border-line bg-sand";
  return (
    <figure className={`relative overflow-hidden rounded-3xl border p-1.5 ${frame} ${className}`}>
      <Image
        src={src}
        alt={alt}
        sizes={sizes}
        placeholder="blur"
        className="aspect-[3/2] h-auto w-full rounded-[1.2rem] object-cover"
      />
    </figure>
  );
}
