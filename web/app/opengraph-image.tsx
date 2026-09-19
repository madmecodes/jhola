import { ImageResponse } from "next/og";

export const alt = "Jhola - Household ordering on WhatsApp";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 80,
          background: "#FBF6EC",
          color: "#1F2A5A",
          fontFamily: "serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <svg width="96" height="96" viewBox="0 0 64 64">
            <rect width="64" height="64" rx="14" fill="#1F2A5A" />
            <path d="M24 24c0-6 3.6-10 8-10s8 4 8 10" fill="none" stroke="#E0A526" strokeWidth="4" strokeLinecap="round" />
            <path d="M15 24h34l-3 26a4 4 0 0 1-4 3.6H22a4 4 0 0 1-4-3.6z" fill="#FBF6EC" />
          </svg>
          <div style={{ fontSize: 64, fontWeight: 700 }}>Jhola</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.05 }}>Send the parchi.</div>
          <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.05, color: "#A77B4F" }}>Jhola handles the rest.</div>
          <div style={{ marginTop: 28, fontSize: 32, color: "#4A5480" }}>
            Household ordering on WhatsApp, with family rules the AI cannot bypass.
          </div>
        </div>
        <div style={{ display: "flex", height: 14, background: "#E0A526", borderRadius: 7, width: 220 }} />
      </div>
    ),
    size,
  );
}
