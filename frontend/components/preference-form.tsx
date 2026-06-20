"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { getPreferences, savePreferences } from "@/lib/api";
import type { Preferences } from "@/lib/types";
import { useUserStore } from "@/store/user";

const FIELDS: (keyof Preferences)[] = [
  "interested_categories",
  "interested_suppliers",
  "interested_regions",
  "interested_signals",
  "excluded_categories",
  "excluded_suppliers",
  "excluded_regions",
  "excluded_signals",
];

export function emptyPreferences(userId: string): Preferences {
  return {
    user_id: userId,
    interested_categories: [],
    interested_suppliers: [],
    interested_regions: [],
    interested_signals: [],
    excluded_categories: [],
    excluded_suppliers: [],
    excluded_regions: [],
    excluded_signals: [],
  };
}

export function PreferenceForm() {
  const userId = useUserStore((s) => s.userId);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getPreferences(userId).then((p) => {
      if (active) setPrefs(p ?? emptyPreferences(userId));
    });
    return () => {
      active = false;
    };
  }, [userId]);

  if (!prefs) return <Spinner label="Loading preferences…" />;

  const addItem = (field: keyof Preferences, value: string) => {
    const v = value.trim();
    if (!v) return;
    const current = prefs[field] as string[];
    if (current.includes(v)) return;
    setPrefs({ ...prefs, [field]: [...current, v] });
  };

  const removeItem = (field: keyof Preferences, value: string) => {
    const current = prefs[field] as string[];
    setPrefs({ ...prefs, [field]: current.filter((x) => x !== value) });
  };

  const onSave = async () => {
    setStatus(null);
    try {
      await savePreferences({ ...prefs, user_id: userId });
      setStatus("Saved.");
    } catch (err) {
      setStatus(err instanceof Error ? `Save failed: ${err.message}` : "Save failed.");
    }
  };

  return (
    <main className="space-y-4">
      <h1 className="text-xl font-semibold">Preferences</h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {FIELDS.map((field) => (
          <TagField
            key={field}
            field={field}
            values={prefs[field] as string[]}
            onAdd={addItem}
            onRemove={removeItem}
          />
        ))}
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={onSave}>Save preferences</Button>
        {status ? <span className="text-sm text-slate-600">{status}</span> : null}
      </div>
    </main>
  );
}

function TagField({
  field,
  values,
  onAdd,
  onRemove,
}: {
  field: keyof Preferences;
  values: string[];
  onAdd: (field: keyof Preferences, value: string) => void;
  onRemove: (field: keyof Preferences, value: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const label = String(field).replace(/_/g, " ");
  return (
    <div className="rounded-md border border-slate-200 p-3">
      <p className="mb-2 text-sm font-medium capitalize text-slate-700">{label}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onAdd(field, draft);
          setDraft("");
        }}
      >
        <Input
          aria-label={`Add ${String(field)}`}
          placeholder={`Add ${label}…`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </form>
      <div className="mt-2 flex flex-wrap gap-1">
        {values.map((v) => (
          <Badge key={v} className="bg-slate-100 text-slate-700">
            {v}
            <button
              type="button"
              aria-label={`Remove ${v}`}
              className="ml-1 text-slate-500"
              onClick={() => onRemove(field, v)}
            >
              ×
            </button>
          </Badge>
        ))}
      </div>
    </div>
  );
}
