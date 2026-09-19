"use client";

import { useId, useState, type ReactNode } from "react";
import { KeyRound, Lock } from "lucide-react";
import { setAdminKey, useAdminKey } from "@/lib/jhola/hooks";
import { IS_LIVE } from "@/lib/jhola/client";
import { Button } from "./ui";

export const NEED_KEY = "Enter the admin key (top right) to use this.";

export function AdminKeyControl() {
  const key = useAdminKey();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const id = useId();

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setDraft(key);
          setOpen((o) => !o);
        }}
        aria-expanded={open}
        aria-controls={id}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
          key ? "border-leaf/40 bg-leaf-soft text-leaf" : "border-ink/20 bg-paper text-ink hover:border-ink/50"
        }`}
      >
        <KeyRound className="h-3.5 w-3.5" aria-hidden />
        <span>{key ? "Admin key set" : "Admin key"}</span>
      </button>
      {open ? (
        <form
          id={id}
          onSubmit={(e) => {
            e.preventDefault();
            setAdminKey(draft.trim());
            setOpen(false);
          }}
          className="absolute right-0 top-full z-40 mt-2 w-[min(18rem,calc(100vw-2rem))] rounded-2xl border border-line bg-paper p-4 shadow-xl"
        >
          <label htmlFor={`${id}-input`} className="text-sm font-semibold">
            Admin key
          </label>
          <p className="mt-0.5 text-xs text-ink-soft">
            Needed to approve orders, activate rules and reset the demo. Stored only in this browser.
            {IS_LIVE ? null : " In mock mode any value works."}
          </p>
          <input
            id={`${id}-input`}
            type="password"
            autoComplete="off"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="mt-2 w-full rounded-lg border border-line bg-cream px-3 py-2 text-sm outline-none focus:border-ink"
          />
          <div className="mt-3 flex justify-end gap-2">
            {key ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setAdminKey("");
                  setDraft("");
                  setOpen(false);
                }}
              >
                Clear
              </Button>
            ) : null}
            <Button type="submit" size="sm">
              Save
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

// Wraps a guarded action: disabled with a tooltip until an admin key is present.
export function Guarded({ children }: { children: (key: string, disabled: boolean) => ReactNode }) {
  const key = useAdminKey();
  const disabled = !key;
  return (
    <span title={disabled ? NEED_KEY : undefined} className="inline-flex items-center gap-1">
      {disabled ? <Lock className="h-3 w-3 text-ink-soft" aria-hidden /> : null}
      {children(key, disabled)}
      {disabled ? <span className="sr-only">{NEED_KEY}</span> : null}
    </span>
  );
}
