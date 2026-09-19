import Image from "next/image";
import logo from "@/public/logo.png";

type Props = { className?: string; alt?: string };

// Official Jhola mark: turmeric jute bag with leaves on an indigo disc.
export default function Logo({ className = "h-8 w-8", alt = "" }: Props) {
  return <Image src={logo} alt={alt} sizes="64px" className={`shrink-0 rounded-full ${className}`} />;
}
