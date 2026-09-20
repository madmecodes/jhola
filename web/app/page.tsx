import SiteHeader from "@/components/SiteHeader";
import SiteFooter from "@/components/SiteFooter";
import Hero from "@/components/landing/Hero";
import WhyNow from "@/components/landing/WhyNow";
import HowItWorks from "@/components/landing/HowItWorks";
import HouseholdRules from "@/components/landing/HouseholdRules";
import Safety from "@/components/landing/Safety";
import Faq from "@/components/landing/Faq";

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main>
        <Hero />
        <WhyNow />
        <HowItWorks />
        <HouseholdRules />
        <Safety />
        <Faq />
      </main>
      <SiteFooter />
    </>
  );
}
