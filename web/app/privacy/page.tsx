import type { Metadata } from "next";
import LegalPage from "@/components/LegalPage";
import { CONTACT_EMAIL, HACKATHON_NAME } from "@/lib/config";

export const metadata: Metadata = {
  title: "Privacy policy",
  description: "How Jhola handles the WhatsApp messages, images and voice notes you send it.",
  alternates: { canonical: "/privacy" },
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy policy"
      intro={`Jhola is a student project built for the ${HACKATHON_NAME} hackathon. This page explains, in plain words, what we do with the information you send us.`}
    >
      <section>
        <h2>What we process</h2>
        <ul>
          <li>Messages you send to Jhola on WhatsApp, including text, photos of shopping lists and voice notes.</li>
          <li>Your WhatsApp phone number and profile name, which WhatsApp shares with us so we can reply.</li>
          <li>Household settings the admin creates, such as member names, roles and spending rules.</li>
          <li>The resulting carts, decisions and audit log entries.</li>
        </ul>
      </section>
      <section>
        <h2>Why we process it</h2>
        <p>
          Only to run the Jhola ordering demo: reading your list, matching items, checking household rules,
          asking for approvals and keeping an audit trail for the family admin. We do not use your data for
          advertising.
        </p>
      </section>
      <section>
        <h2>Who we share it with</h2>
        <p>
          We do not sell or rent your data. It is processed and stored on Amazon Web Services (AWS), which hosts
          the service, and it passes through WhatsApp (Meta) because that is where the conversation happens. No
          real shop or retailer receives your orders; ordering and payments are simulated.
        </p>
      </section>
      <section>
        <h2>How long we keep it</h2>
        <p>
          We keep data only as long as needed to run and evaluate the demo. After the project ends, we delete it.
        </p>
      </section>
      <section>
        <h2>Your choices</h2>
        <p>
          You can stop using Jhola at any time by not messaging it. You can ask us to delete everything linked to
          your phone number by writing to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. We will confirm
          once it is done.
        </p>
      </section>
      <section>
        <h2>Contact</h2>
        <p>
          Questions about this policy: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </section>
    </LegalPage>
  );
}
