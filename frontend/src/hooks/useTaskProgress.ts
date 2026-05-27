import { useState, useRef, useCallback } from 'react';

interface ProgressState {
  progress: number;
  status: string;
  loaded: number;
  total: number;
  page: number;
  total_pages: number;
  error?: string;
  meta?: Record<string, any>;
}

interface UseTaskProgressOptions {
  /** Interval in ms for polling progress endpoint */
  pollInterval?: number;
  /** Base URL for progress API */
  baseUrl?: string;
}

interface UseTaskProgressReturn {
  /** Current progress state */
  prog: ProgressState;
  /** Start tracking a new task by its task_id */
  trackTask: (taskId: string) => void;
  /** Called when task completes (progress=100 or status='done' or 'failed') */
  onDone: (callback: (prog: ProgressState) => void) => void;
  /** Reset progress to initial state */
  reset: () => void;
}

const INITIAL: ProgressState = {
  progress: 0, status: '', loaded: 0, total: 0, page: 0, total_pages: 0,
};

export function useTaskProgress(opts: UseTaskProgressOptions = {}): UseTaskProgressReturn {
  const { pollInterval = 500, baseUrl = 'http://localhost:8000' } = opts;
  const [prog, setProg] = useState<ProgressState>(INITIAL);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const doneCallback = useRef<((prog: ProgressState) => void) | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const trackTask = useCallback((taskId: string) => {
    stopPolling();

    const poll = async () => {
      try {
        const r = await fetch(`${baseUrl}/api/query-progress/${taskId}`);
        const p: ProgressState = await r.json();

        // Map old 'done'/'failed' status to standardized format
        const status = p.status || '';
        const isDone = status === 'done' || p.progress >= 100;
        const isFailed = status === 'failed' || (p as any).error;

        setProg({
          progress: p.progress ?? 0,
          status: isFailed ? (p.error || '查询失败') : p.status || '',
          loaded: p.loaded || 0,
          total: p.total || 0,
          page: p.page || 0,
          total_pages: p.total_pages || 0,
          error: isFailed ? (p.error || '未知错误') : undefined,
          meta: (p as any).meta,
        });

        if (isDone || isFailed) {
          stopPolling();
          if (doneCallback.current) {
            doneCallback.current({
              progress: isFailed ? 0 : 100,
              status: isFailed ? (p.error || '查询失败') : 'done',
              loaded: p.loaded || 0,
              total: p.total || 0,
              page: p.page || 0,
              total_pages: p.total_pages || 0,
              error: isFailed ? (p.error || '未知错误') : undefined,
              meta: (p as any).meta,
            });
          }
        }
      } catch {
        // Network error during poll - ignore, will retry
      }
    };

    // Immediate first poll
    poll();
    pollRef.current = setInterval(poll, pollInterval);
  }, [baseUrl, pollInterval, stopPolling]);

  const onDone = useCallback((callback: (prog: ProgressState) => void) => {
    doneCallback.current = callback;
  }, []);

  const reset = useCallback(() => {
    stopPolling();
    setProg(INITIAL);
  }, [stopPolling]);

  return { prog, trackTask, onDone, reset };
}
