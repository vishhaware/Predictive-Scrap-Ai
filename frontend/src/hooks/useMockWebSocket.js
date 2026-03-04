import { useEffect, useRef } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';

/**
 * Connects to the backend WebSocket via Vite proxy (/ws).
 * Handles reconnect with backoff, health polling, and machine switching.
 */
export function useWebSocket() {
    const currentMachine = useTelemetryStore(s => s.currentMachine);

    const wsRef = useRef(null);
    const reconnectTimerRef = useRef(null);
    const healthTimerRef = useRef(null);
    const pingTimerRef = useRef(null);
    const reconnectAttemptRef = useRef(0);
    const shouldReconnectRef = useRef(true);

    useEffect(() => {
        const BASE_RECONNECT_MS = 1500;
        const MAX_RECONNECT_MS = 15000;
        const HEALTH_CHECK_MS = 8000;
        const PING_INTERVAL_MS = 20000;

        function normalizeWsBase(url) {
            if (!url || typeof url !== 'string') return null;
            const trimmed = url.trim();
            if (!trimmed) return null;
            if (trimmed.startsWith('ws://') || trimmed.startsWith('wss://')) {
                return trimmed.replace(/\/+$/, '');
            }
            if (trimmed.startsWith('http://')) {
                return `ws://${trimmed.slice('http://'.length)}`.replace(/\/+$/, '');
            }
            if (trimmed.startsWith('https://')) {
                return `wss://${trimmed.slice('https://'.length)}`.replace(/\/+$/, '');
            }
            return trimmed.replace(/\/+$/, '');
        }

        const envWsBase = normalizeWsBase(import.meta.env.VITE_BACKEND_WS_URL);
        const envHttpBase = normalizeWsBase(import.meta.env.VITE_BACKEND_URL);
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const proxyWsBase = `${protocol}//${window.location.host}`;
        const isLocalHost = ['127.0.0.1', 'localhost'].includes(window.location.hostname);
        const directLocalBackend = `${protocol}//127.0.0.1:8000`;
        // Prefer explicit backend URLs first; in local dev use direct backend
        // before falling back to Vite proxy to avoid noisy proxy socket aborts.
        const wsBase = envWsBase
            || envHttpBase
            || ((import.meta.env.DEV && isLocalHost) ? directLocalBackend : proxyWsBase);
        const wsUrl = `${wsBase}/ws`;
        shouldReconnectRef.current = true;

        function connect() {
            if (!shouldReconnectRef.current) return;
            const existing = wsRef.current;
            if (
                existing &&
                (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)
            ) {
                return;
            }

            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                reconnectAttemptRef.current = 0;
                useTelemetryStore.getState().setBackendStatus('online');
                if (pingTimerRef.current) clearInterval(pingTimerRef.current);
                pingTimerRef.current = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'ping' }));
                    }
                }, PING_INTERVAL_MS);

                // Send current machine selection
                const currentMachine = useTelemetryStore.getState().currentMachine;
                ws.send(JSON.stringify({ type: 'switch_machine', machine_id: currentMachine }));
            };

            ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === 'cycle_update' && msg.cycle) {
                        useTelemetryStore.getState().pushCycle(msg.cycle);
                        return;
                    }
                    if (msg.type === 'pong') {
                        useTelemetryStore.getState().setBackendStatus('online');
                        return;
                    }
                    if (msg.type === 'error') {
                        useTelemetryStore.getState().setBackendStatus('degraded');
                    }
                } catch (e) {
                    console.error('WS parse error:', e);
                }
            };

            ws.onclose = async () => {
                wsRef.current = null;
                if (!shouldReconnectRef.current) return;
                useTelemetryStore.getState().setBackendStatus('degraded');
                if (pingTimerRef.current) {
                    clearInterval(pingTimerRef.current);
                    pingTimerRef.current = null;
                }

                const attempt = reconnectAttemptRef.current;
                reconnectAttemptRef.current += 1;
                const jitter = Math.floor(Math.random() * 400);
                const delay = Math.min(BASE_RECONNECT_MS * (2 ** attempt) + jitter, MAX_RECONNECT_MS);

                const health = await useTelemetryStore.getState().checkBackendHealth();
                if (!health) {
                    useTelemetryStore.getState().setBackendStatus('offline');
                }
                if (!shouldReconnectRef.current) return;

                reconnectTimerRef.current = setTimeout(connect, delay);
            };

            ws.onerror = (err) => {
                console.error('WS error:', err);
                // Avoid forcing close here; browsers usually emit close after error.
                useTelemetryStore.getState().setBackendStatus('degraded');
            };
        }

        connect();

        healthTimerRef.current = setInterval(() => {
            const ws = wsRef.current;
            if (!ws || ws.readyState !== WebSocket.OPEN) {
                void useTelemetryStore.getState().checkBackendHealth();
            }
        }, HEALTH_CHECK_MS);

        return () => {
            shouldReconnectRef.current = false;
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
                reconnectTimerRef.current = null;
            }
            if (healthTimerRef.current) {
                clearInterval(healthTimerRef.current);
                healthTimerRef.current = null;
            }
            if (pingTimerRef.current) {
                clearInterval(pingTimerRef.current);
                pingTimerRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close(1000, 'component unmount');
                wsRef.current = null;
            }
            useTelemetryStore.getState().setBackendStatus('offline');
        };
    }, []);

    useEffect(() => {
        const ws = wsRef.current;
        if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'switch_machine',
                machine_id: currentMachine,
            }));
        }
    }, [currentMachine]);
}

// Keep backward-compatible export name
export { useWebSocket as useMockWebSocket };
