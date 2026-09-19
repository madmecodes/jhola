import type { NextConfig } from "next";

// When NEXT_PUBLIC_JHOLA_API is set, the console calls /jhola-api/* and Vercel proxies it to the
// backend, so the backend does not need CORS for the browser.
const JHOLA_API = process.env.NEXT_PUBLIC_JHOLA_API?.replace(/\/+$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return JHOLA_API ? [{ source: "/jhola-api/:path*", destination: `${JHOLA_API}/:path*` }] : [];
  },
};

export default nextConfig;
