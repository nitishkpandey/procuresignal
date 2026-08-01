import type { ChatFrame } from "@/lib/types";

export function wsBaseUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
}

export const WEBSOCKET_BEARER_SUBPROTOCOL = "bearer";

export interface ChatSocketHandlers {
  onFrame: (frame: ChatFrame) => void;
  onOpen?: () => void;
  onClose?: (code: number) => void;
  onError?: () => void;
}

/**
 * Open the chat socket for a conversation.
 *
 * The access token rides in the subprotocol list rather than the URL: a browser cannot
 * set an Authorization header on a WebSocket, and a query string would put the token
 * into access logs, proxy logs, and browser history. Identity is never in the path —
 * the server derives it from the token.
 */
export function openChatSocket(
  accessToken: string,
  conversationId: string,
  handlers: ChatSocketHandlers,
): { send: (message: string) => void; close: () => void } {
  const url = `${wsBaseUrl()}/api/ws/chat/${encodeURIComponent(conversationId)}`;
  const socket = new WebSocket(url, [WEBSOCKET_BEARER_SUBPROTOCOL, accessToken]);

  socket.onopen = () => handlers.onOpen?.();
  socket.onclose = (event) => handlers.onClose?.(event.code);
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
