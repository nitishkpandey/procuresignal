import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getAnalyses: vi.fn(),
  getAnalysis: vi.fn(),
  decideRecommendation: vi.fn(),
}));

import { SupplierAnalysis } from "@/components/supplier-analysis";
import * as api from "@/lib/api";
import type { AnalysisDetail, AnalysisRecommendation } from "@/lib/types";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

function recommendation(
  overrides: Partial<AnalysisRecommendation> = {},
): AnalysisRecommendation {
  return {
    ordinal: 0,
    title: "Qualify a second source for injection modules",
    rationale: "The incumbent has an open recall and an unresolved strike.",
    evidence_event_keys: ["acme-strike-2026-08", "acme-quality-2026-08"],
    status: "proposed",
    decided_at: null,
    decision_note: null,
    ...overrides,
  };
}

function detail(overrides: Partial<AnalysisDetail> = {}): AnalysisDetail {
  return {
    public_id: "run-1",
    supplier_public_id: "acme-parts",
    status: "completed",
    model: "gpt-5.4-mini",
    step_count: 4,
    prompt_tokens: 2497,
    completion_tokens: 305,
    started_at: "2026-08-23T09:00:00Z",
    finished_at: "2026-08-23T09:00:12Z",
    failure_reason: null,
    recommendation_count: 1,
    steps: [
      { ordinal: 0, kind: "tool_call", tool_name: "get_supplier_impact", payload: {} },
      { ordinal: 1, kind: "tool_result", tool_name: "get_supplier_impact", payload: {} },
      { ordinal: 2, kind: "model_message", tool_name: null, payload: { text: "..." } },
      {
        ordinal: 3,
        kind: "evidence_check",
        tool_name: null,
        payload: { verified: ["acme-strike-2026-08"], dropped: [] },
      },
    ],
    recommendations: [recommendation()],
    ...overrides,
  };
}

beforeEach(() => {
  // This project's vitest config does not clear mocks between tests, which makes call
  // counts leak and "was never called" assertions pass by test order.
  vi.clearAllMocks();
  localStorage.clear();
  useUserStore.setState({ user: authUser({ role: "admin" }), platformLanguage: "en" });
  vi.mocked(api.getAnalyses).mockResolvedValue({
    items: [
      {
        public_id: "run-1",
        supplier_public_id: "acme-parts",
        status: "completed",
        model: "gpt-5.4-mini",
        step_count: 4,
        prompt_tokens: 2497,
        completion_tokens: 305,
        started_at: "2026-08-23T09:00:00Z",
        finished_at: "2026-08-23T09:00:12Z",
        failure_reason: null,
        recommendation_count: 1,
      },
    ],
    total: 1,
  });
  vi.mocked(api.getAnalysis).mockResolvedValue(detail());
  vi.mocked(api.decideRecommendation).mockImplementation(
    async (_id, ordinal, decision) =>
      recommendation({
        ordinal,
        status: decision === "approve" ? "approved" : "rejected",
        decided_at: "2026-08-23T10:00:00Z",
      }),
  );
});

describe("SupplierAnalysis", () => {
  // Every assertion waits for loaded content rather than markup present while loading.
  it("lists the analyses this organization has run", async () => {
    render(<SupplierAnalysis />);

    expect(await screen.findByText(/acme-parts/)).toBeInTheDocument();
  });

  it("shows a recommendation with its evidence already visible", async () => {
    /**
     * Not behind a disclosure, unlike the impact badge's drivers. Those explain a number
     * the platform computed; this explains a claim a language model made, and the reader
     * needs the evidence in front of them before they decide they agree.
     */
    render(<SupplierAnalysis />);

    expect(await screen.findByText(/Qualify a second source/)).toBeInTheDocument();
    expect(screen.getByText(/acme-strike-2026-08/)).toBeInTheDocument();
    expect(screen.getByText(/acme-quality-2026-08/)).toBeInTheDocument();
  });

  it("says which model produced the analysis", async () => {
    // Two models are two behaviours. A recommendation whose provenance is invisible
    // cannot be compared against one from a different model.
    render(<SupplierAnalysis />);

    expect(await screen.findByText(/gpt-5\.4-mini/)).toBeInTheDocument();
  });

  it("keeps the transcript out of the way but reachable", async () => {
    /**
     * Most readers do not want it. The one reviewing a bad recommendation wants nothing
     * else, so it is collapsed rather than absent.
     */
    const { container } = render(<SupplierAnalysis />);

    await screen.findByText(/Qualify a second source/);
    const disclosure = container.querySelector("details");

    // `<details>` keeps its children in the DOM when shut, which is why "collapsed" is
    // asserted as the disclosure being closed rather than as the steps being absent.
    // It stays a `<details>` because it works with a keyboard and without JavaScript.
    expect(disclosure).not.toBeNull();
    expect(disclosure).not.toHaveAttribute("open");

    await userEvent.click(screen.getByText(/how it reached this/i));

    expect(disclosure).toHaveAttribute("open");
    // The tool appears twice — the call and its result.
    expect(screen.getAllByText(/get_supplier_impact/)).toHaveLength(2);
  });

  it("lets an admin approve a recommendation", async () => {
    render(<SupplierAnalysis />);

    await userEvent.click(await screen.findByRole("button", { name: /^approve$/i }));

    await waitFor(() =>
      expect(api.decideRecommendation).toHaveBeenCalledWith("run-1", 0, "approve", ""),
    );
  });

  it("lets an admin reject with a reason", async () => {
    render(<SupplierAnalysis />);

    await screen.findByText(/Qualify a second source/);
    await userEvent.type(
      screen.getByRole("textbox", { name: /note/i }),
      "We already dual-source this.",
    );
    await userEvent.click(screen.getByRole("button", { name: /^reject$/i }));

    await waitFor(() =>
      expect(api.decideRecommendation).toHaveBeenCalledWith(
        "run-1",
        0,
        "reject",
        "We already dual-source this.",
      ),
    );
  });

  it("shows the decision in place of the controls once made", async () => {
    /**
     * Decisions are one-way server-side and answer 409 on a second attempt. Leaving the
     * buttons live would offer the user an action that can only fail.
     */
    vi.mocked(api.getAnalysis).mockResolvedValue(
      detail({
        recommendations: [
          recommendation({
            status: "approved",
            decided_at: "2026-08-23T10:00:00Z",
            decision_note: "Agreed in the Tuesday review.",
          }),
        ],
      }),
    );

    render(<SupplierAnalysis />);

    expect(await screen.findByText(/approved/i)).toBeInTheDocument();
    expect(screen.getByText(/Agreed in the Tuesday review/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it("does not offer approval to someone who cannot approve", async () => {
    // A member can ask for an analysis but not put the organization's name behind one.
    useUserStore.setState({ user: authUser({ role: "member" }), platformLanguage: "en" });

    render(<SupplierAnalysis />);

    await screen.findByText(/Qualify a second source/);
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^reject$/i })).not.toBeInTheDocument();
  });

  it("says plainly when a run produced nothing", async () => {
    /**
     * An analysis with no recommendations is a real and useful outcome — the evidence
     * did not support one. An empty panel would read as a broken page.
     */
    vi.mocked(api.getAnalysis).mockResolvedValue(
      detail({ recommendations: [], recommendation_count: 0 }),
    );

    render(<SupplierAnalysis />);

    expect(await screen.findByText(/no recommendations/i)).toBeInTheDocument();
  });

  it("surfaces why a run failed rather than showing an empty result", async () => {
    vi.mocked(api.getAnalysis).mockResolvedValue(
      detail({
        status: "failed",
        failure_reason: "budget_exhausted",
        recommendations: [],
        recommendation_count: 0,
      }),
    );

    render(<SupplierAnalysis />);

    // Matched on the text, not on role="status": Spinner also claims that role, so a
    // role query resolves against the loading state instead of the loaded one.
    expect(await screen.findByText(/stopped early/i)).toHaveTextContent(/budget_exhausted/);
  });

  it("tells the reader when the agent cited something that does not exist", async () => {
    /**
     * The signal that says this output needs a closer read. Dropping the citations
     * silently would hide the one fact a reviewer most needs to know.
     */
    vi.mocked(api.getAnalysis).mockResolvedValue(
      detail({
        steps: [
          {
            ordinal: 0,
            kind: "evidence_check",
            tool_name: null,
            payload: { verified: ["acme-strike-2026-08"], dropped: ["invented-key"] },
          },
        ],
      }),
    );

    render(<SupplierAnalysis />);

    expect(await screen.findByText(/could not be verified/i)).toBeInTheDocument();
  });

  it("tells the user when nothing has been analysed yet", async () => {
    vi.mocked(api.getAnalyses).mockResolvedValue({ items: [], total: 0 });

    render(<SupplierAnalysis />);

    expect(await screen.findByText(/no analyses yet/i)).toBeInTheDocument();
  });
});
