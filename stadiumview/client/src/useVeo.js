import { useState, useCallback, useRef } from 'react';

const API = import.meta.env.VITE_API_BASE || '';

export function useVeo() {
  const [state, setState] = useState({ status: 'idle' }); // idle | generating | done | failed
  const pollRef = useRef(null);

  const generate = useCallback(async (seatId, section, row, sport = 'basketball') => {
    setState({ status: 'generating', estimatedSeconds: 60 });

    try {
      const res = await fetch(`${API}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seatId, section, row, sport }),
      });
      const data = await res.json();

      if (data.status === 'cached') {
        setState({ status: 'done', videoUrl: data.videoUrl });
        return data.videoUrl;
      }

      // Poll for completion
      const jobId = data.jobId;
      return await new Promise((resolve, reject) => {
        pollRef.current = setInterval(async () => {
          try {
            const poll = await fetch(`${API}/api/status/${jobId}`);
            const job = await poll.json();
            if (job.status === 'done') {
              clearInterval(pollRef.current);
              setState({ status: 'done', videoUrl: job.videoUrl });
              resolve(job.videoUrl);
            } else if (job.status === 'failed') {
              clearInterval(pollRef.current);
              setState({ status: 'failed', error: job.error });
              reject(new Error(job.error));
            }
          } catch (err) {
            clearInterval(pollRef.current);
            setState({ status: 'failed', error: err.message });
            reject(err);
          }
        }, 5000);
      });
    } catch (err) {
      setState({ status: 'failed', error: err.message });
      throw err;
    }
  }, []);

  const reset = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    setState({ status: 'idle' });
  }, []);

  return { ...state, generate, reset };
}
