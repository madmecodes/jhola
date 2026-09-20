import Image from "next/image";

/**
 * Household member avatars. Photos are AI-generated stand-ins for the demo
 * household; no real person is depicted. Falls back to initials when a member
 * has no photo (for example a household created live on WhatsApp).
 */
const PHOTOS: Record<string, string> = {
  mom: "/avatars/mom.jpg",
  dad: "/avatars/dad.jpg",
  didi: "/avatars/didi.jpg",
  teen: "/avatars/teen.jpg",
  dadaji: "/avatars/dadaji.jpg",
};

export function memberPhoto(id?: string | null) {
  if (!id) return undefined;
  return PHOTOS[id.toLowerCase()];
}

export function Avatar({
  id,
  initials,
  tone = "bg-sand text-ink",
  size = 36,
  className = "",
  alt = "",
}: {
  id?: string | null;
  initials: string;
  tone?: string;
  size?: number;
  className?: string;
  alt?: string;
}) {
  const src = memberPhoto(id);
  const box = `shrink-0 overflow-hidden rounded-full ${className}`;

  if (src) {
    return (
      <span className={box} style={{ width: size, height: size }}>
        <Image
          src={src}
          alt={alt}
          width={size * 2}
          height={size * 2}
          className="h-full w-full object-cover"
          sizes={`${size}px`}
        />
      </span>
    );
  }

  return (
    <span
      className={`grid place-items-center font-semibold ${tone} ${box}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }}
      aria-hidden={alt ? undefined : true}
    >
      {initials}
    </span>
  );
}
