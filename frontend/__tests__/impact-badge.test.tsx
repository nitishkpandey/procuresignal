import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImpactBadge } from "@/components/impact-badge";
import type { SupplierImpact } from "@/lib/types";

function impact(overrides: Partial<SupplierImpact> = {}): SupplierImpact {
  return {
    supplier_public_id: "s-1",
    supplier_name: "Acme Parts GmbH",
    value: 0.53,
    band: "severe",
    drivers: [
      {
        event_key: "acme-bankruptcy",
        risk_type: "bankruptcy",
        severity: "critical",
        confidence: 0.9,
        published_at: "2026-08-21T09:00:00Z",
        contribution: 0.81,
        evidence_snippet: "The group filed for protection from creditors.",
        source_name: "Handelsblatt",
      },
      {
        event_key: "acme-strike",
        risk_type: "strike",
        severity: "medium",
        confidence: 0.8,
        published_at: "2026-08-22T09:00:00Z",
        contribution: 0.32,
        evidence_snippet: "Workers at the Stuttgart plant walked out.",
        source_name: "Reuters",
      },
    ],
    ...overrides,
  };
}

describe("ImpactBadge", () => {
  it("names the band rather than showing a bare number", () => {
    render(<ImpactBadge impact={impact()} />);

    expect(screen.getByText(/severe/i)).toBeInTheDocument();
  });

  it("lists the events behind the score, strongest first", () => {
    render(<ImpactBadge impact={impact()} />);

    // A procurement decision defended with an unexplainable number is not defensible,
    // so the drivers are in the markup rather than behind a second request.
    const drivers = screen.getAllByRole("listitem");
    expect(drivers[0]).toHaveTextContent(/bankruptcy/i);
    expect(drivers[0]).toHaveTextContent(/Handelsblatt/);
    expect(drivers[1]).toHaveTextContent(/strike/i);
  });

  it("says plainly when there is nothing to report", () => {
    render(<ImpactBadge impact={impact({ band: "none", value: 0, drivers: [] })} />);

    expect(screen.getByText(/no risk events/i)).toBeInTheDocument();
  });

  it("does not claim a driver list it does not have", () => {
    render(<ImpactBadge impact={impact({ band: "none", value: 0, drivers: [] })} />);

    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("distinguishes a sanctions floor from ordinary bad news", () => {
    /**
     * The value is a fraction of one and the band is severe. Showing the number alone
     * would read as "barely anything"; showing the band alone would hide that the
     * arithmetic disagrees. A buyer needs to know this is a compliance stop.
     */
    const sanctioned = impact({
      value: 0.01,
      band: "severe",
      drivers: [
        {
          event_key: "designated",
          risk_type: "sanctions",
          severity: "low",
          confidence: 0.2,
          published_at: "2026-08-11T09:00:00Z",
          contribution: 0.02,
          evidence_snippet: "Added to the consolidated designations list.",
          source_name: "Official Journal",
        },
      ],
    });

    render(<ImpactBadge impact={sanctioned} />);

    expect(screen.getByText(/severe/i)).toBeInTheDocument();
    expect(screen.getByText(/sanctions/i)).toBeInTheDocument();
  });

  it("is readable without colour", () => {
    // Band is carried as text, not only as a background class: roughly one in twelve
    // men cannot separate the amber and red these bands would otherwise rely on.
    const { container } = render(<ImpactBadge impact={impact({ band: "elevated" })} />);

    expect(container.textContent).toMatch(/elevated/i);
  });
});
