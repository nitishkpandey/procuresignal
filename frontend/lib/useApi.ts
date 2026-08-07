"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type RequestState<T> = {
  key: string;
  data: T | null;
  error: string | null;
};

export function useApi<T>(fn: () => Promise<T>, requestKey: string) {
  const [state, setState] = useState<RequestState<T>>({ key: "", data: null, error: null });
  const [nonce, setNonce] = useState(0);
  const request = useRef(fn);
  const currentKey = `${requestKey}:${nonce}`;

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    request.current = fn;
  }, [fn]);

  useEffect(() => {
    let active = true;
    request
      .current()
      .then((res) => {
        if (active) setState({ key: currentKey, data: res, error: null });
      })
      .catch((err: unknown) => {
        if (active) {
          setState({
            key: currentKey,
            data: null,
            error: err instanceof Error ? err.message : "Request failed",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [currentKey]);

  const current = state.key === currentKey;
  return {
    data: current ? state.data : null,
    loading: !current,
    error: current ? state.error : null,
    reload,
  };
}
