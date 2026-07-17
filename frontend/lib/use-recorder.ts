"use client";

import { useEffect, useRef, useState } from "react";

/** Shared MediaRecorder logic. onStop fires with an audio/webm Blob.
 *  Pass onChunk to also receive 300ms slices live (realtime WS streaming). */
export function useRecorder(onStop: (blob: Blob) => void, onChunk?: (blob: Blob) => void) {
  const [recording, setRecording] = useState(false);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const cbRef = useRef(onStop);
  const chunkRef = useRef(onChunk);

  useEffect(() => {
    cbRef.current = onStop;
    chunkRef.current = onChunk;
  });

  async function start() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mr = new MediaRecorder(stream);
    chunks.current = [];
    mr.ondataavailable = (e) => {
      if (e.data.size) {
        chunks.current.push(e.data);
        chunkRef.current?.(e.data);
      }
    };
    mr.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      setRecording(false);
      const blob = new Blob(chunks.current, { type: "audio/webm" });
      if (blob.size >= 500) cbRef.current(blob);
    };
    // timeslice → periodic dataavailable events for live chunk streaming
    mr.start(chunkRef.current ? 300 : undefined);
    recRef.current = mr;
    setRecording(true);
  }

  function stop() {
    recRef.current?.stop();
  }

  return { recording, start, stop };
}
