// Copies the agent's demo catalog and household into web/lib/store as trimmed static JSON.
// Run from web/: `npm run sync-store-data`. The agent/ folder is read, never written.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "agent", "src", "jhola", "data");
const out = join(here, "..", "lib", "store");

const catalog = JSON.parse(readFileSync(join(src, "catalog.json"), "utf8"));
const trimmed = catalog.map((p) => ({
  id: p.id,
  name: p.name,
  brand: p.brand,
  category: p.category,
  subcategory: p.subcategory ?? null,
  pack_size: p.pack_size,
  unit: p.unit,
  price_inr: p.price_inr,
  mrp_inr: p.mrp_inr ?? p.price_inr,
  seller_rating: p.seller_rating,
  in_stock: p.in_stock !== false,
  fulfilment: p.fulfilment,
  amazon_search_url: p.amazon_search_url,
  q: [p.name, p.brand, ...(p.tags ?? []), ...(p.aliases ?? [])].join(" ").toLowerCase(),
}));
writeFileSync(join(out, "catalog.json"), JSON.stringify(trimmed));

const h = JSON.parse(readFileSync(join(src, "household.json"), "utf8"));
const usual = { mom: new Set(), dad: new Set(), didi: new Set(), teen: new Set() };
for (const pref of Object.values(h.preferences ?? {})) usual.mom.add(pref.sku);
for (const row of h.purchase_history ?? []) usual[row.by]?.add(row.sku);
const household = {
  name: h.name,
  city: h.city,
  mandate: h.mandate,
  members: (h.members ?? []).map((m) => ({ id: m.id, name: m.name, display: m.display, role: m.role })),
  preferred_skus: [...new Set(Object.values(h.preferences ?? {}).map((p) => p.sku))],
  usual_by_member: Object.fromEntries(Object.entries(usual).map(([k, v]) => [k, [...v]])),
};
writeFileSync(join(out, "household.json"), JSON.stringify(household, null, 1));
console.log(`catalog: ${trimmed.length} products, household: ${household.members.length} members`);
