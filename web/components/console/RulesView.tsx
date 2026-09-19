"use client";

import { useState } from "react";
import { CheckCircle2, ChevronDown, Sparkles, Trash2, XCircle } from "lucide-react";
import { api, errorMessage } from "@/lib/jhola/client";
import { usePolling } from "@/lib/jhola/hooks";
import type { RuleDraft } from "@/lib/jhola/types";
import { Guarded } from "./AdminKey";
import CedarCode from "./CedarCode";
import { Button, Card, EmptyState, ErrorState, PageHeader, SectionTitle, SkeletonList } from "./ui";

const EXAMPLES = [
  "Didi can only buy groceries up to Rs 300 on weekends",
  "Aarav cannot order snacks",
  "Dad can order up to Rs 2000 without asking",
];

function Composer({ onActivated }: { onActivated: () => void }) {
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [activating, setActivating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [thinking, setThinking] = useState<string | null>(null);

  async function doDraft() {
    if (!text.trim()) return;
    setDrafting(true);
    setError(null);
    setDone(null);
    setDraft(null);
    try {
      setThinking(null);
      setDraft(await api.draftRule(text.trim(), (t) => setThinking(t)));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setDrafting(false);
      setThinking(null);
    }
  }

  async function activate(key: string) {
    if (!draft) return;
    setActivating(true);
    setError(null);
    try {
      const res = await api.activateRule(draft.cedar, text.trim(), key);
      setDone(`Rule ${res.rule?.id ?? ""} is active. Cedar now enforces it on every order.`);
      setDraft(null);
      setText("");
      onActivated();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setActivating(false);
    }
  }

  const tests = draft?.test_results ?? [];
  const passed = tests.filter((t) => t.pass).length;

  return (
    <Card className="p-5">
      <h2 className="font-display text-xl font-semibold">Write a rule in plain words</h2>
      <p className="mt-1 text-sm text-ink-soft">
        <strong className="text-ink">The AI drafts. The policy engine validates. A human activates.</strong>
      </p>
      <form
        className="mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          doDraft();
        }}
      >
        <label htmlFor="rule-text" className="sr-only">
          Rule in plain words
        </label>
        <textarea
          id="rule-text"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Didi can only buy groceries up to Rs 300 on weekends"
          className="w-full resize-y rounded-xl border border-line bg-cream px-3.5 py-3 text-sm outline-none focus:border-ink"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={drafting || !text.trim()}>
            <Sparkles className="h-4 w-4" aria-hidden /> {drafting ? "Drafting" : "Draft with AI"}
          </Button>
          <span className="text-xs text-ink-soft">Try:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setText(ex)}
              className="rounded-full border border-line bg-paper px-2.5 py-1 text-xs text-ink-soft hover:border-ink/40 hover:text-ink"
            >
              {ex}
            </button>
          ))}
        </div>
      </form>

      {error ? <div className="mt-4"><ErrorState message={error} /></div> : null}
      {done ? (
        <p role="status" className="mt-4 rounded-xl border border-leaf/30 bg-leaf-soft px-3 py-2 text-sm text-leaf">
          {done}
        </p>
      ) : null}
      {drafting ? (
        <div className="mt-4 space-y-2">
          <p role="status" className="text-sm text-ink-soft">
            {thinking ? `Jhola is thinking. ${thinking}` : "Drafting the Cedar policy and running the auto-tests..."}
          </p>
          <SkeletonList rows={2} className="h-24" />
        </div>
      ) : null}

      {draft ? (
        <div className="mt-5 space-y-4" aria-live="polite">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-jute">Generated Cedar</p>
              <CedarCode code={draft.cedar} className="mt-1.5" />
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-jute">What it means</p>
                <p className="mt-1.5 text-sm">{draft.explanation_en}</p>
                <p className="mt-1 text-sm italic text-ink-soft">{draft.explanation_hinglish}</p>
              </div>
              {draft.validation.ok ? (
                <p className="flex items-center gap-2 rounded-xl border border-leaf/30 bg-leaf-soft px-3 py-2 text-sm font-semibold text-leaf">
                  <CheckCircle2 className="h-4 w-4" aria-hidden /> Valid against the household schema
                </p>
              ) : (
                <div className="rounded-xl border border-terracotta/30 bg-terracotta-soft px-3 py-2 text-sm">
                  <p className="flex items-center gap-2 font-semibold text-terracotta">
                    <XCircle className="h-4 w-4" aria-hidden /> Invalid. Cedar rejected this draft.
                  </p>
                  <ul className="mt-1 list-disc pl-6 text-ink">
                    {draft.validation.errors.map((err) => (
                      <li key={err}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          {tests.length ? (
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-jute">
                Auto-tests: {passed} of {tests.length} passed
              </p>
              <div className="mt-1.5 overflow-x-auto rounded-xl border border-line">
                <table className="w-full min-w-[28rem] text-left text-sm">
                  <thead className="bg-sand text-xs text-ink-soft">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-semibold">Case</th>
                      <th scope="col" className="px-3 py-2 font-semibold">Expected</th>
                      <th scope="col" className="px-3 py-2 font-semibold">Actual</th>
                      <th scope="col" className="px-3 py-2 font-semibold">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {tests.map((t) => (
                      <tr key={t.case}>
                        <td className="px-3 py-2">{t.case}</td>
                        <td className="px-3 py-2 font-mono text-xs">{t.expected}</td>
                        <td className="px-3 py-2 font-mono text-xs">{t.actual}</td>
                        <td className="px-3 py-2">
                          <span className={`font-semibold ${t.pass ? "text-leaf" : "text-terracotta"}`}>{t.pass ? "Pass" : "Fail"}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <Guarded>
              {(key, disabled) => (
                <Button
                  variant="leaf"
                  disabled={disabled || activating || !draft.validation.ok || (tests.length > 0 && passed < tests.length)}
                  onClick={() => activate(key)}
                >
                  {activating ? "Activating" : "Activate rule"}
                </Button>
              )}
            </Guarded>
            {!draft.validation.ok ? <span className="text-xs text-ink-soft">Fix the rule text and draft again. Invalid rules cannot be activated.</span> : null}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

export default function RulesView() {
  const household = usePolling(() => api.household(), 15000);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rules = (household.data?.rules ?? []).filter((r) => r.active !== false);

  async function remove(id: string, key: string) {
    if (!window.confirm(`Remove rule ${id}?`)) return;
    setDeleting(id);
    setError(null);
    try {
      await api.deleteRule(id, key);
      await household.refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div>
      <PageHeader title="Household rules" hindi="घर के नियम">
        Rules are Cedar policies, checked outside the AI on every line item and every payment. The model can suggest a cart; it cannot
        change what Cedar allows.
      </PageHeader>

      <div className="space-y-8">
        <Composer onActivated={() => household.refresh()} />

        <section aria-labelledby="active-rules">
          <SectionTitle id="active-rules" title="Active rules" hint={household.data ? `${rules.length} policies in force` : undefined} />
          {error ? <div className="mb-3"><ErrorState message={error} /></div> : null}
          {household.loading ? (
            <SkeletonList rows={4} className="h-20" />
          ) : household.error && !household.data ? (
            <ErrorState message={household.error} onRetry={household.refresh} />
          ) : rules.length === 0 ? (
            <EmptyState title="No rules yet" />
          ) : (
            <ul className="space-y-3">
              {rules.map((r) => (
                <li key={r.id}>
                  <details className="group rounded-2xl border border-line bg-paper">
                    <summary className="flex cursor-pointer items-start gap-3 rounded-2xl px-4 py-3 hover:bg-cream/60">
                      <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-center gap-2">
                          <code className="rounded-md border border-ink/15 bg-cream px-1.5 py-0.5 font-mono text-[11px]">{r.id}</code>
                          <span
                            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                              r.source === "custom" ? "bg-turmeric-soft text-[#7a5500]" : "bg-sand text-ink-soft"
                            }`}
                          >
                            {r.source === "custom" ? "Custom" : "Base"}
                          </span>
                        </p>
                        <p className="mt-1.5 text-sm font-semibold">{r.title_en}</p>
                        {r.title_hinglish && r.title_hinglish !== r.title_en ? <p className="text-sm italic text-ink-soft">{r.title_hinglish}</p> : null}
                      </div>
                      <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-ink-soft transition-transform group-open:rotate-180" aria-hidden />
                    </summary>
                    <div className="border-t border-line p-3">
                      <CedarCode code={r.cedar} />
                      {r.source === "custom" ? (
                        <div className="mt-3 flex justify-end">
                          <Guarded>
                            {(key, disabled) => (
                              <Button variant="danger" size="sm" disabled={disabled || deleting !== null} onClick={() => remove(r.id, key)}>
                                <Trash2 className="h-3.5 w-3.5" aria-hidden /> {deleting === r.id ? "Removing" : "Remove rule"}
                              </Button>
                            )}
                          </Guarded>
                        </div>
                      ) : null}
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
