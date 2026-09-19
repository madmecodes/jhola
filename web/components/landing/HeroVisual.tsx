import ChatMockup from "./ChatMockup";

// The hero illustration lives in this one component so it can be swapped later,
// for example with a generated image:
//   import Image from "next/image";
//   return <Image src="/hero.png" alt="..." width={720} height={900} priority />;
export default function HeroVisual() {
  return (
    <div className="relative">
      <div
        aria-hidden
        className="absolute -inset-x-2 sm:-inset-x-6 top-10 bottom-4 -z-10 rounded-[3rem] bg-turmeric-soft/70 [transform:rotate(-3deg)]"
      />
      <ChatMockup />
    </div>
  );
}
