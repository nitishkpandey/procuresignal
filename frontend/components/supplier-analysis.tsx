"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { decideRecommendation, getAnalyses, getAnalysis } from "@/lib/api";
import type { AnalysisDetail, AnalysisRecommendation } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useUserStore } from "@/store/user";

const DECISION_STYLES: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-900",
  rejected: "bg-slate-200 text-slate-700",
  proposed: "bg-amber-100 text-amber-900",
};

/** Approving puts the organization's name behind an action. Members may ask for an
 * analysis but not decide on one, matching what the API enforces. */
function canDecide(role: string | undefined): boolean {
  return role === "owner" || role === "admin";
}

function droppedCitations(detail: AnalysisDetail | null): string[] {
  const check = detail?.steps.find((step) => step.kind === "evidence_check");
  const dropped = check?.payload?.dropped;
  return Array.isArray(dropped) ? dropped.map(String) : [];
}

function Recommendation({
  item,
  runId,
  decidable,
  onDecided,
}: {
  item: AnalysisRecommendation;
  runId: string;
  decidable: boolean;
  onDecided: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      await decideRecommendation(runId, item.ordinal, decision, note);
      onDecided();
    } catch {
      setError("That decision did not go through. Reload and try again.");
    } finally {
      setBusy(false);
    }
  };

  const decided = item.status !== "proposed";

  return (
    <Card className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold text-slate-950">{item.title}</h3>
        <Badge className={`${DECISION_STYLES[item.status] ?? ""} capitalize`}>
          {item.status}
        </Badge>
      </div>

      <p className="text-sm text-slate-600">{item.rationale}</p>

      {/* Evidence is expanded, not behind a disclosure. The impact badge hides its
          drivers because they explain a number the platform computed; these support a
          claim a language model made, and the reader needs them before deciding they
          agree rather than after. */}
      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
        <p className="text-xs font-semibold uppercase text-slate-500">Evidence</p>
        <ul className="mt-1 space-y-0.5">
          {item.evidence_event_keys.map((key) => (
            <li key={key} className="font-mono text-xs text-slate-700">
              {key}
            </li>
          ))}
        </ul>
      </div>

      {decided ? (
        <p className="text-sm text-slate-600">
          {item.decision_note ? `“${item.decision_note}”` : "No note was left."}
        </p>
      ) : decidable ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Input
            aria-label="Decision note"
            placeholder="Why, for the record"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void decide("approve")}>
              Approve
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() => void decide("reject")}
            >
              Reject
            </Button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
    </Card>
  );
}

export function SupplierAnalysis() {
  const role = useUserStore((s) => s.user?.role);
  const runs = useApi(() => getAnalyses(), "analyses");
  const items = useMemo(() => runs.data?.items ?? [], [runs.data?.items]);

  const [chosenId, setChosenId] = useState<string | null>(null);
  const activeId = chosenId ?? items[0]?.public_id ?? null;
  const detail = useApi(
    () => (activeId ? getAnalysis(activeId) : Promise.resolve(null)),
    `analysis:${activeId ?? "none"}`,
  );

  const dropped = droppedCitations(detail.data);

  return (
    <main className="space-y-5">
      <section className="border-b border-slate-200 pb-5">
        <p className="text-xs font-semibold uppercase text-slate-500">Analyses</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">Supplier analysis</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Start one from a supplier on a watchlist. Nothing an analysis proposes takes
          effect until somebody approves it.
        </p>
      </section>

      {runs.loading ? <Spinner /> : null}
      {runs.error ? (
        <p className="text-sm text-red-700" role="alert">
          {runs.error}
        </p>
      ) : null}

      {!runs.loading && !runs.error && items.length === 0 ? (
        <EmptyState
          title="No analyses yet"
          hint="Open a watchlist and choose Analyse on a supplier to start one."
        />
      ) : null}

      {items.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <ul className="space-y-2">
            {items.map((run) => {
              const active = run.public_id === activeId;
              return (
                <li key={run.public_id}>
                  <button
                    type="button"
                    aria-current={active}
                    onClick={() => setChosenId(run.public_id)}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                      active
                        ? "border-slate-950 bg-white shadow-sm"
                        : "border-slate-200 bg-white/70 hover:border-slate-400"
                    }`}
                  >
                    <span className="block font-medium text-slate-950">
                      {run.supplier_public_id}
                    </span>
                    <span className="block text-xs text-slate-500">
                      {new Date(run.started_at).toLocaleString()} · {run.recommendation_count}{" "}
                      proposed
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="space-y-4">
            {detail.loading ? <Spinner /> : null}

            {detail.data ? (
              <>
                <p className="text-xs text-slate-500">
                  {detail.data.model} · {detail.data.step_count} steps ·{" "}
                  {detail.data.prompt_tokens + detail.data.completion_tokens} tokens
                </p>

                {detail.data.status === "failed" ? (
                  <p
                    role="status"
                    className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
                  >
                    This analysis stopped early: {detail.data.failure_reason}. Nothing was
                    proposed.
                  </p>
                ) : null}

                {dropped.length > 0 ? (
                  <p
                    role="status"
                    className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900"
                  >
                    {dropped.length} citation{dropped.length === 1 ? "" : "s"} could not be
                    verified against any risk event and {dropped.length === 1 ? "was" : "were"}{" "}
                    removed. Read the rest of this analysis carefully.
                  </p>
                ) : null}

                {detail.data.recommendations.length === 0 &&
                detail.data.status !== "failed" ? (
                  <EmptyState
                    title="No recommendations"
                    hint="The evidence did not support one. That is an answer, not a failure."
                  />
                ) : null}

                {detail.data.recommendations.map((item) => (
                  <Recommendation
                    key={item.ordinal}
                    item={item}
                    runId={detail.data!.public_id}
                    decidable={canDecide(role)}
                    onDecided={detail.reload}
                  />
                ))}

                {/* Collapsed: most readers do not want the transcript, and the one
                    reviewing a bad recommendation wants nothing else. */}
                <details className="rounded-lg border border-slate-200 bg-white p-3">
                  <summary className="cursor-pointer select-none text-sm font-medium text-slate-700">
                    How it reached this
                  </summary>
                  <ol className="mt-2 space-y-1 text-xs text-slate-600">
                    {detail.data.steps.map((step) => (
                      <li key={step.ordinal}>
                        <span className="font-mono text-slate-500">{step.ordinal}.</span>{" "}
                        <span className="font-medium">{step.kind}</span>
                        {step.tool_name ? ` · ${step.tool_name}` : ""}
                      </li>
                    ))}
                  </ol>
                </details>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </main>
  );
}
