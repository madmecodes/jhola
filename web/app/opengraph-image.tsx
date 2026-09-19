import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";

export const alt = "Jhola - Household ordering on WhatsApp";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  const [logo, photo] = await Promise.all([
    readFile(join(process.cwd(), "public/logo-192.png"), "base64"),
    readFile(join(process.cwd(), "assets/og-photo.jpg"), "base64"),
  ]);

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: "#FBF6EC", color: "#1F2A5A" }}>
        <div
          style={{
            width: 740,
            height: "100%",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "72px 64px 72px 80px",
            fontFamily: "serif",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
            <img src={`data:image/png;base64,${logo}`} width={96} height={96} alt="" />
            <div style={{ fontSize: 64, fontWeight: 700 }}>Jhola</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 58, fontWeight: 700, lineHeight: 1.05 }}>Send the parchi.</div>
            <div style={{ fontSize: 58, fontWeight: 700, lineHeight: 1.05, color: "#A77B4F" }}>Jhola handles the rest.</div>
            <div style={{ marginTop: 26, fontSize: 29, lineHeight: 1.3, color: "#4A5480" }}>
              Household ordering on WhatsApp, with family rules the AI cannot bypass.
            </div>
          </div>
          <div style={{ display: "flex", height: 14, background: "#E0A526", borderRadius: 7, width: 220 }} />
        </div>
        <div style={{ display: "flex", flex: 1, padding: "28px 28px 28px 0" }}>
          <img
            src={`data:image/jpeg;base64,${photo}`}
            width={432}
            height={574}
            alt=""
            style={{ width: 432, height: 574, objectFit: "cover", borderRadius: 36, border: "6px solid #1F2A5A" }}
          />
        </div>
      </div>
    ),
    size,
  );
}
