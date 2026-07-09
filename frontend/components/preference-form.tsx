"use client";

import { useEffect, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { getPreferences, savePreferences } from "@/lib/api";
import type { Preferences } from "@/lib/types";
import { useUserStore } from "@/store/user";

const PREFERENCE_GROUPS: {
  title: string;
  includeField: keyof Preferences;
  excludeField: keyof Preferences;
  includeLabel: string;
  excludeLabel: string;
}[] = [
  {
    title: "Supplier",
    includeField: "interested_suppliers",
    excludeField: "excluded_suppliers",
    includeLabel: "suppliers",
    excludeLabel: "excluded suppliers",
  },
  {
    title: "Location",
    includeField: "interested_regions",
    excludeField: "excluded_regions",
    includeLabel: "locations",
    excludeLabel: "excluded locations",
  },
  {
    title: "Categories",
    includeField: "interested_categories",
    excludeField: "excluded_categories",
    includeLabel: "categories",
    excludeLabel: "excluded categories",
  },
  {
    title: "Misc",
    includeField: "interested_signals",
    excludeField: "excluded_signals",
    includeLabel: "risk signals",
    excludeLabel: "excluded risk signals",
  },
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
    platform_language: "en",
  };
}

export function PreferenceForm() {
  const userId = useUserStore((s) => s.userId);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setPrefs(null);
    setLoadError(null);
    getPreferences(userId)
      .then((p) => {
        if (active) setPrefs(p ?? emptyPreferences(userId));
      })
      .catch((err: unknown) => {
        if (!active) return;
        setLoadError(err instanceof Error ? err.message : "Unable to load preferences.");
      });
    return () => {
      active = false;
    };
  }, [userId]);

  const reload = async () => {
    setPrefs(null);
    setLoadError(null);
    setStatus(null);
    try {
      const next = await getPreferences(userId);
      setPrefs(next ?? emptyPreferences(userId));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Unable to load preferences.");
    }
  };

  if (loadError)
    return (
      <main className="space-y-4">
        <PageHeader />
        <Card className="border-red-200 bg-red-50/70">
          <p className="text-sm font-semibold text-red-800">Preferences unavailable</p>
          <p className="mt-1 text-sm text-red-700">
            The preference service did not respond. Retry when the API is available.
          </p>
          <Button className="mt-3" variant="secondary" onClick={reload}>
            Retry
          </Button>
        </Card>
      </main>
    );

  if (!prefs)
    return (
      <main className="space-y-4">
        <PageHeader />
        <Spinner label="Loading preferences..." />
      </main>
    );

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
    <main className="space-y-5">
      <PageHeader />
      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/70">
        <label className="block text-sm font-medium text-slate-700" htmlFor="platform-language">
          Platform language
        </label>
        <select
          id="platform-language"
          aria-label="Platform language"
          value={prefs.platform_language || "en"}
          onChange={(e) => setPrefs({ ...prefs, platform_language: e.target.value })}
          className="mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 sm:max-w-xs"
        >
          <option value="en">English</option>
          <option value="de">German</option>
          <option value="fr">French</option>
          <option value="es">Spanish</option>
        </select>
      </section>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {PREFERENCE_GROUPS.map((group) => (
          <PreferenceSection key={group.title} title={group.title}>
            <TagField
              field={group.includeField}
              label={group.includeLabel}
              values={prefs[group.includeField] as string[]}
              onAdd={addItem}
              onRemove={removeItem}
            />
            <TagField
              field={group.excludeField}
              label={group.excludeLabel}
              values={prefs[group.excludeField] as string[]}
              onAdd={addItem}
              onRemove={removeItem}
            />
          </PreferenceSection>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={onSave}>Save preferences</Button>
        {status ? <span className="text-sm text-slate-600">{status}</span> : null}
      </div>
    </main>
  );
}

function PageHeader() {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/80">
      <p className="text-xs font-semibold uppercase text-slate-500">Company signal profile</p>
      <h1 className="mt-1 text-2xl font-semibold text-slate-950">Preferences</h1>
      <p className="mt-1 max-w-2xl text-sm text-slate-500">
        Keep signal matching focused on the categories, suppliers, regions, and risks that matter.
      </p>
    </section>
  );
}

function PreferenceSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/70">
      <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function TagField({
  field,
  label,
  values,
  onAdd,
  onRemove,
}: {
  field: keyof Preferences;
  label: string;
  values: string[];
  onAdd: (field: keyof Preferences, value: string) => void;
  onRemove: (field: keyof Preferences, value: string) => void;
}) {
  const [draft, setDraft] = useState("");
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50/80 p-3">
      <p className="mb-2 text-sm font-medium capitalize text-slate-700">{label}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onAdd(field, draft);
          setDraft("");
        }}
      >
        <Input
          aria-label={`Add ${label}`}
          placeholder={`Add ${label}…`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </form>
      <div className="mt-2 flex flex-wrap gap-1">
        {values.map((v) => (
          <Badge key={v} className="border-slate-200 bg-white text-slate-700">
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
