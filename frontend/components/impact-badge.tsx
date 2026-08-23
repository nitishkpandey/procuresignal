"use client";

import { Badge } from "@/components/ui/badge";
import type { SupplierImpact } from "@/lib/types";

/**
 * Band colours, with the band name always rendered as text beside them. Roughly one man
 * in twelve cannot separate the amber from the red, so a badge that carries its meaning
 * only in a background colour carries it for eleven of them.
 */
const BAND_STYLES: Record<string, string> = {
  severe: "bg-red-100 text-red-900",
  elevated: "bg-amber-100 text-amber-900",
  low: "bg-slate-100 text-slate-700",
  none: "bg-slate-100 text-slate-500",
};

function bandLabel(band: string): string {
  return band === "none" ? "No risk events" : band;
}

export function ImpactBadge({ impact }: { impact: SupplierImpact }) {
  const style = BAND_STYLES[impact.band] ?? BAND_STYLES.none;

  return (
    <div className="space-y-1">
      <Badge className={`${style} capitalize`}>{bandLabel(impact.band)}</Badge>

      {impact.drivers.length > 0 ? (
        <details className="text-xs text-slate-600">
          {/* A disclosure rather than a hover tooltip: hover has no keyboard or touch
              equivalent, and the drivers are the part a buyer has to be able to quote. */}
          <summary className="cursor-pointer select-none text-slate-500 hover:text-slate-800">
            Why
          </summary>
          <ul className="mt-1 space-y-1 border-l border-slate-200 pl-2">
            {impact.drivers.map((driver) => (
              <li key={driver.event_key}>
                <span className="font-medium capitalize text-slate-800">
                  {driver.risk_type.replace(/_/g, " ")}
                </span>
                <span className="text-slate-500"> · {driver.severity}</span>
                <span className="text-slate-500"> · {driver.source_name}</span>
                <p className="text-slate-600">{driver.evidence_snippet}</p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
