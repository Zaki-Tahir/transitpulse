import { useEffect, useRef, useState } from "react";
import { clientId } from "./api";
import type { ServerMessage } from "./types";
import { VehicleStore } from "./vehicles";

export type Connection = "connecting" | "live" | "reconnecting";

interface Handlers {
  onStatus: (lines: Extract<ServerMessage, { type: "status" }>["lines"]) => void;
  onCommute: (alert: Extract<ServerMessage, { type: "commute" }>) => void;
}

/**
 * Keeps a WebSocket open to /ws and feeds the vehicle store. Reconnects with exponential
 * backoff (1s, 2s, 4s... up to 30s); every reconnect starts with a fresh snapshot, so nothing
 * missed while offline matters.
 */
export function useLive(handlers: Handlers) {
  const store = useRef(new VehicleStore()).current;
  const [connection, setConnection] = useState<Connection>("connecting");
  const [count, setCount] = useState(0);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${location.host}/ws?client_id=${clientId()}`);
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as ServerMessage;
        if (msg.type === "snapshot") {
          attempt = 0;
          setConnection("live");
          store.applySnapshot(msg.t, msg.v);
        } else if (msg.type === "delta") {
          store.applyDelta(msg.t, msg.u, msg.r);
        } else if (msg.type === "status") {
          handlersRef.current.onStatus(msg.lines);
        } else if (msg.type === "commute") {
          handlersRef.current.onCommute(msg);
        }
        setCount(store.vehicles.size);
      };
      socket.onclose = () => {
        if (closed) return;
        setConnection("reconnecting");
        timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** attempt++));
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [store]);

  return { store, connection, count };
}
