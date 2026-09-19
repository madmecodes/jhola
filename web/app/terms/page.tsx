import type { Metadata } from "next";
import LegalPage from "@/components/LegalPage";
import { CONTACT_EMAIL, HACKATHON_NAME } from "@/lib/config";

export const metadata: Metadata = {
  title: "Terms of use",
  description: "Terms for using the Jhola student demo.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of use"
      intro={`Jhola is a student project built for the ${HACKATHON_NAME} hackathon. By using it, you agree to these short terms.`}
    >
      <section>
        <h2>A demo, not a shop</h2>
        <p>
          Jhola demonstrates household ordering on WhatsApp. No real purchases are made, no goods are delivered
          and no real payments or UPI mandates are created. Any prices, carts, approvals and payments you see are
          simulated.
        </p>
      </section>
      <section>
        <h2>Acceptable use</h2>
        <ul>
          <li>Do not send content that is illegal, harmful or that you do not have the right to share.</li>
          <li>Do not send sensitive information such as bank details, card numbers or passwords.</li>
          <li>Do not try to disrupt or abuse the service.</li>
        </ul>
      </section>
      <section>
        <h2>Provided as is</h2>
        <p>
          The service is provided &quot;as is&quot;, without warranties of any kind. It may be unavailable, change
          or stop at any time. AI output can be wrong, so do not rely on Jhola for anything important.
        </p>
      </section>
      <section>
        <h2>Limitation of liability</h2>
        <p>
          To the extent permitted by law, the project team is not liable for any loss arising from use of the demo.
        </p>
      </section>
      <section>
        <h2>No affiliation</h2>
        <p>
          Jhola is an independent student project. Brand and product names mentioned are used only as examples and
          do not imply any partnership or endorsement.
        </p>
      </section>
      <section>
        <h2>Contact</h2>
        <p>
          Questions: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </section>
    </LegalPage>
  );
}
