// Site-wide settings. Edit here, not in individual pages.

export const CONTACT_EMAIL = "ayushguptadev1@gmail.com";

export const SITE_NAME = "Jhola";
export const SITE_TITLE = "Jhola - the approval layer for agents that spend your money";
export const SITE_DESCRIPTION =
  "Jhola is the approval layer for agents that spend your money: the model builds the cart, a Cedar policy engine outside the model decides whether it may pay, and every decision cites the rule that made it.";
export const HACKATHON_NAME = "First Commit";
export const LAST_UPDATED = "20 September 2026";

// On Vercel this resolves to the production domain; locally it falls back to localhost.
export const SITE_URL = process.env.VERCEL_PROJECT_PRODUCTION_URL
  ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
  : "http://localhost:3000";
