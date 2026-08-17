"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  createWatchlist,
  getWatchlist,
  getWatchlists,
  searchSuppliers,
  unwatchSupplier,
  watchSupplier,
} from "@/lib/api";
import type { WatchedSupplier } from "@/lib/types";
import { useApi } from "@/lib/useApi";

/**
 * Surface what the server said rather than "something went wrong". A team that hits a
 * duplicate name needs to know it is a duplicate, otherwise they retry the same name.
 */
function detailOf(error: unknown, fallback: string): string {
  if (typeof error !== "object" || !error || !("response" in error)) return fallback;
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  return typeof detail === "string" && detail ? detail : fallback;
}

function supplierCountLabel(count: number): string {
  if (count === 0) return "No suppliers yet";
  return count === 1 ? "1 supplier" : `${count} suppliers`;
}

export function WatchlistView() {
  const lists = useApi(() => getWatchlists(), "watchlists");
  const items = useMemo(() => lists.data?.items ?? [], [lists.data?.items]);

  const [chosenId, setChosenId] = useState<string | null>(null);
  // Falling back to the first list so the panel is never blank on arrival; an explicit
  // choice wins once the buyer makes one.
  const activeId = chosenId ?? items[0]?.public_id ?? null;
  const detail = useApi(
    () => (activeId ? getWatchlist(activeId) : Promise.resolve(null)),
    `watchlist:${activeId ?? "none"}`,
  );

  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [supplierQuery, setSupplierQuery] = useState("");
  const [candidates, setCandidates] = useState<WatchedSupplier[]>([]);

  const submitName = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    setCreateError(null);
    try {
      await createWatchlist(name);
      setNewName("");
      lists.reload();
    } catch (err) {
      setCreateError(detailOf(err, "Could not create the watchlist."));
    } finally {
      setBusy(false);
    }
  };

  const runSearch = async () => {
    const q = supplierQuery.trim();
    if (!q) return;
    try {
      const { items: found } = await searchSuppliers(q);
      setCandidates(found);
    } catch {
      setCandidates([]);
    }
  };

  const add = async (supplierId: string) => {
    if (!activeId) return;
    await watchSupplier(activeId, supplierId);
    setCandidates([]);
    setSupplierQuery("");
    detail.reload();
    lists.reload();
  };

  const remove = async (supplierId: string) => {
    if (!activeId) return;
    await unwatchSupplier(activeId, supplierId);
    detail.reload();
    lists.reload();
  };

  return (
    <main className="space-y-5">
      <section className="border-b border-slate-200 pb-5">
        <p className="text-xs font-semibold uppercase text-slate-500">Watchlists</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">Suppliers you watch</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Alert rules only fire for suppliers on one of these lists. Everyone in your
          organization sees the same lists.
        </p>
      </section>

      <form
        className="flex flex-col gap-2 sm:flex-row sm:items-start"
        onSubmit={(e) => {
          e.preventDefault();
          void submitName();
        }}
      >
        <Input
          aria-label="New watchlist name"
          placeholder="Tier 1 suppliers"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <Button type="submit" disabled={busy || !newName.trim()}>
          Create
        </Button>
      </form>
      {createError ? (
        <p className="text-sm text-red-700" role="alert">
          {createError}
        </p>
      ) : null}

      {lists.loading ? <Spinner /> : null}
      {lists.error ? (
        <p className="text-sm text-red-700" role="alert">
          {lists.error}
        </p>
      ) : null}

      {!lists.loading && !lists.error && items.length === 0 ? (
        <EmptyState
          title="No watchlists yet"
          hint="Create a list, add the suppliers you depend on, and alerts will follow them."
        />
      ) : null}

      {items.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <ul className="space-y-2">
            {items.map((list) => {
              const active = list.public_id === activeId;
              return (
                <li key={list.public_id}>
                  <button
                    type="button"
                    aria-current={active}
                    onClick={() => setChosenId(list.public_id)}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                      active
                        ? "border-slate-950 bg-white shadow-sm"
                        : "border-slate-200 bg-white/70 hover:border-slate-400"
                    }`}
                  >
                    <span className="block font-medium text-slate-950">{list.name}</span>
                    <span className="block text-xs text-slate-500">
                      {supplierCountLabel(list.supplier_count)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <Card className="space-y-4">
            {detail.loading ? <Spinner /> : null}
            {detail.data ? (
              <>
                <h2 className="text-lg font-semibold text-slate-950">{detail.data.name}</h2>

                <form
                  className="flex flex-col gap-2 sm:flex-row"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void runSearch();
                  }}
                >
                  <Input
                    aria-label="Find a supplier to watch"
                    placeholder="Search the supplier registry"
                    value={supplierQuery}
                    onChange={(e) => setSupplierQuery(e.target.value)}
                  />
                  <Button type="submit" variant="secondary">
                    Search
                  </Button>
                </form>

                {candidates.length > 0 ? (
                  <ul className="space-y-1 rounded-lg border border-slate-200 p-2">
                    {candidates.map((candidate) => (
                      <li
                        key={candidate.public_id}
                        className="flex items-center justify-between gap-2 text-sm"
                      >
                        <span className="text-slate-800">{candidate.canonical_name}</span>
                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => void add(candidate.public_id)}
                        >
                          Watch
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : null}

                {detail.data.suppliers.length === 0 ? (
                  <p className="text-sm text-slate-500">
                    Nothing on this list yet — search above to add a supplier.
                  </p>
                ) : (
                  <ul className="divide-y divide-slate-200">
                    {detail.data.suppliers.map((supplier) => (
                      <li
                        key={supplier.public_id}
                        className="flex items-center justify-between gap-3 py-2"
                      >
                        <span className="text-sm font-medium text-slate-900">
                          {supplier.canonical_name}
                        </span>
                        <span className="flex items-center gap-3">
                          {supplier.country ? (
                            <span className="text-xs text-slate-500">{supplier.country}</span>
                          ) : null}
                          <button
                            type="button"
                            aria-label={`Stop watching ${supplier.canonical_name}`}
                            onClick={() => void remove(supplier.public_id)}
                            className="text-xs font-medium text-slate-500 underline underline-offset-2 hover:text-slate-900"
                          >
                            Remove
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : null}
          </Card>
        </div>
      ) : null}
    </main>
  );
}
