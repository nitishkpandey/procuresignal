import type { ChatFrame } from "@/lib/types";

export function wsBaseUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
}

export interface ChatSocketHandlers {
  onFrame: (frame: ChatFrame) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: () => void;
}

export function openChatSocket(
  userId: string,
  conversationId: string,
  handlers: ChatSocketHandlers,
): { send: (message: string) => void; close: () => void } {
  const url = `${wsBaseUrl()}/api/ws/chat/${encodeURIComponent(userId)}/${encodeURIComponent(
    conversationId,
  )}`;
  const socket = new WebSocket(url);

  socket.onopen = () => handlers.onOpen?.();
  socket.onclose = () => handlers.onClose?.();
  socket.onerror = () => handlers.onError?.();
  socket.onmessage = (event) => {
    try {
      const frame = JSON.parse(event.data) as ChatFrame;
      handlers.onFrame(frame);
    } catch {
      handlers.onError?.();
    }
  };

  return {
    send: (message: string) => socket.send(JSON.stringify({ message })),
    close: () => socket.close(),
  };
}
