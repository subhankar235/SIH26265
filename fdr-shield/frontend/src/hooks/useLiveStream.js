import { useEffect, useState, useRef } from 'react';

/**
 * Custom hook providing real-time Server-Sent Events (SSE) with automatic
 * polling fallback when SSE is blocked or fails (Phase 8.5 requirement).
 *
 * @param {string} url - The SSE endpoint URL
 * @param {Array<string>} eventTypes - Specific event names to listen to
 * @param {Function} onEvent - Callback when an event arrives
 * @param {number} fallbackIntervalMs - Polling interval if SSE blocked (default 3000ms)
 */
export function useLiveStream(url, eventTypes = [], onEvent, fallbackIntervalMs = 3000) {
  const [sseActive, setSseActive] = useState(false);
  const [sseBlocked, setSseBlocked] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!url) return;
    let stream;
    let pollTimer;
    let lastId = null;

    try {
      const api = import.meta.env.VITE_API_URL || '/api/v1';
      const fullUrl = url.startsWith('http') ? url : `${api}${url.startsWith('/') ? '' : '/'}${url}`;
      stream = new EventSource(fullUrl, { withCredentials: true });

      stream.onopen = () => {
        setSseActive(true);
        setSseBlocked(false);
      };

      const handleEvent = (e) => {
        if (e.lastEventId) lastId = e.lastEventId;
        if (onEventRef.current) {
          try {
            const data = e.data ? JSON.parse(e.data) : null;
            onEventRef.current(e.type, data, e.lastEventId);
          } catch {
            onEventRef.current(e.type, e.data, e.lastEventId);
          }
        }
      };

      stream.onmessage = handleEvent;
      eventTypes.forEach((type) => stream.addEventListener(type, handleEvent));

      stream.onerror = () => {
        // SSE connection dropped or blocked by proxy/firewall -> switch to polling fallback (8.5)
        setSseActive(false);
        setSseBlocked(true);
      };
    } catch {
      setSseActive(false);
      setSseBlocked(true);
    }

    return () => {
      if (stream) stream.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [url, JSON.stringify(eventTypes)]);

  return { sseActive, sseBlocked, pollInterval: sseBlocked ? fallbackIntervalMs : false };
}
