import Image from "next/image";
import heroPhoto from "@/public/images/hero-parchi.webp";
import ChatMockup from "./ChatMockup";

// Photo panel of a real parchi on a kitchen counter, with the WhatsApp mockup in front.
export default function HeroVisual() {
  return (
    <div className="relative isolate pb-8 pt-32 sm:py-10">
      <div
        aria-hidden
        className="absolute -right-3 bottom-0 left-10 top-0 -z-10 rounded-[2.5rem] bg-turmeric-soft/80 [transform:rotate(3deg)] sm:left-20"
      />
      <div className="absolute bottom-3 right-0 top-3 left-6 -z-10 overflow-hidden rounded-[2.5rem] border border-line bg-sand shadow-[0_24px_50px_-30px_rgba(31,42,90,0.5)] sm:left-16">
        <Image
          src={heroPhoto}
          alt="A note and pencil on a kitchen counter beside a jute bag, a steel tumbler, coriander, turmeric and green chillies"
          fill
          preload
          placeholder="blur"
          sizes="(min-width: 1024px) 480px, 90vw"
          className="object-cover object-[center_35%]"
        />
        <div aria-hidden className="absolute inset-0 bg-gradient-to-t from-ink/35 via-transparent to-transparent" />
      </div>
      <div className="sm:pr-10 lg:pr-16">
        <ChatMockup />
      </div>
    </div>
  );
}
