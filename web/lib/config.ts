// Site-wide settings. Edit here, not in individual pages.

// TODO: replace with a real inbox before submitting the WhatsApp Business sign-up.
export const CONTACT_EMAIL = "hello@jhola.example";

export const SITE_NAME = "Jhola";
export const SITE_TITLE = "Jhola - Household ordering on WhatsApp";
export const SITE_DESCRIPTION =
  "Jhola turns the handwritten parchi, voice note or text your family already sends into safe, rule-checked household orders on WhatsApp, with live voice in the store.";
export const HACKATHON_NAME = "First Commit";
export const LAST_UPDATED = "19 September 2026";

// On Vercel this resolves to the production domain; locally it falls back to localhost.
export const SITE_URL = process.env.VERCEL_PROJECT_PRODUCTION_URL
  ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
  : "http://localhost:3000";
