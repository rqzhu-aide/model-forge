import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunDetail, RunEvent } from "../api/types";
import { isRunActive } from "../utils/format";

export function runEventTransport(active: boolean, streamAvailable: boolean): string {
  if (!active) return "Recorded snapshot";
  return streamAvailable ? "Live stream" : "Polling";
}

export function useRunEvents(projectId: string, run: RunDetail | undefined) {
  const queryClient = useQueryClient();
  const [streamAvailable, setStreamAvailable] = useState(true);
  const runId = run?.run_id ?? "";
  const active = run ? isRunActive(run.state) : false;

  const eventsQuery = useQuery({
    queryKey: ["run-events", projectId, runId],
    queryFn: () => api.listRunEvents(projectId, runId),
    enabled: Boolean(runId),
    refetchInterval: active && !streamAvailable ? 4_000 : false,
  });

  const lastSequence = useMemo(
    () => eventsQuery.data?.reduce((maximum, event) => Math.max(maximum, event.sequence), 0) ?? 0,
    [eventsQuery.data],
  );

  useEffect(() => {
    if (!runId || !active || typeof EventSource === "undefined") {
      setStreamAvailable(false);
      return;
    }

    const stream = new EventSource(api.runEventStreamUrl(projectId, runId, lastSequence));
    setStreamAvailable(true);

    stream.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as RunEvent;
        queryClient.setQueryData<RunEvent[]>(["run-events", projectId, runId], (current = []) => {
          if (current.some((item) => item.event_id === event.event_id)) return current;
          return [...current, event].sort((left, right) => left.sequence - right.sequence);
        });
        void queryClient.invalidateQueries({ queryKey: ["run", projectId, runId] });
      } catch {
        setStreamAvailable(false);
        stream.close();
      }
    };
    stream.onerror = () => {
      setStreamAvailable(false);
      stream.close();
    };

    return () => stream.close();
  }, [active, lastSequence, projectId, queryClient, runId]);

  return {
    ...eventsQuery,
    transport: runEventTransport(active, streamAvailable),
  };
}
