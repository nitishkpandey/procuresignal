import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/chat-window", () => ({
  ChatWindow: ({ conversationId }: { conversationId: string }) => (
    <div>Chat window {conversationId}</div>
  ),
}));

vi.mock("@/lib/api", () => ({
  clearConversationHistory: vi.fn(),
  createConversation: vi.fn(),
  listConversations: vi.fn(),
}));
import * as api from "@/lib/api";
import { ChatView } from "@/components/chat-view";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useUserStore.setState({ userId: "u1", platformLanguage: "en" });
  vi.mocked(api.listConversations).mockResolvedValue({
    user_id: "u1",
    conversations: [],
    total_count: 0,
  });
  vi.mocked(api.clearConversationHistory).mockResolvedValue({
    user_id: "u1",
    deleted_conversations: 1,
    deleted_messages: 2,
  });
});

describe("ChatView", () => {
  it("renders a full assistant workspace when there are no conversations", async () => {
    render(<ChatView />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    expect(screen.getByRole("heading", { name: "Procurement assistant" })).toBeInTheDocument();
    expect(screen.getByText("No conversation selected")).toBeInTheDocument();
  });

  it("uses the selected platform language on the chat workspace", async () => {
    useUserStore.setState({ userId: "u1", platformLanguage: "de" });
    render(<ChatView />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());

    expect(screen.getByRole("heading", { name: "Beschaffungsassistent" })).toBeInTheDocument();
    expect(screen.getByText("Keine Unterhaltung ausgewaehlt")).toBeInTheDocument();
  });

  it("shows a retry state when conversations cannot load", async () => {
    vi.mocked(api.listConversations).mockRejectedValueOnce(new Error("Network Error"));
    render(<ChatView />);
    await waitFor(() => expect(screen.getByText("Conversations unavailable")).toBeInTheDocument());
    expect(screen.getByText(/The assistant service did not respond/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("clears conversation history after confirmation", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce({
      user_id: "u1",
      conversations: [
        {
          conversation_id: "c1",
          title: "Supplier question",
          message_count: 2,
          last_message_at: "2026-07-09T08:00:00Z",
        },
      ],
      total_count: 1,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ChatView />);
    await waitFor(() => expect(screen.getByText("Supplier question")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Clear history" }));

    expect(window.confirm).toHaveBeenCalledWith("Clear all chat history for this email?");
    expect(api.clearConversationHistory).toHaveBeenCalledWith("u1");
    await waitFor(() => expect(screen.getByText("No conversation selected")).toBeInTheDocument());
    expect(screen.queryByText("Supplier question")).not.toBeInTheDocument();
  });
});
