import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getMessages: vi.fn() }));
import * as api from "@/lib/api";
import { ChatWindow } from "@/components/chat-window";
import type { ChatFrame } from "@/lib/types";

beforeEach(() => {
  vi.mocked(api.getMessages).mockResolvedValue({
    conversation_id: "c1",
    total_count: 0,
    messages: [],
  });
});

describe("ChatWindow", () => {
  it("sends a message and renders streamed reply", async () => {
    let handlers: { onFrame: (f: ChatFrame) => void; onOpen?: () => void } | null = null;
    const fakeFactory = (_u: string, _c: string, h: typeof handlers) => {
      handlers = h;
      return { send: vi.fn(), close: vi.fn() };
    };

    render(<ChatWindow userId="u1" conversationId="c1" socketFactory={fakeFactory as never} />);
    await waitFor(() => expect(api.getMessages).toHaveBeenCalled());

    const input = screen.getByLabelText("Message");
    await userEvent.type(input, "What is the tariff?{enter}");
    expect(screen.getByText("What is the tariff?")).toBeInTheDocument();

    act(() => {
      handlers!.onFrame({ type: "start", content: "" });
      handlers!.onFrame({ type: "stream", content: "It " });
      handlers!.onFrame({ type: "stream", content: "raises costs." });
      handlers!.onFrame({ type: "end", content: "done" });
    });

    await waitFor(() => expect(screen.getByText("It raises costs.")).toBeInTheDocument());
  });
});
