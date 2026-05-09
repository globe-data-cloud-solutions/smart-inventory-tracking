"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BarcodeScanner } from "@/lib/scanner";

export function useScanner(onScan: (code: string) => void) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const scannerRef = useRef<BarcodeScanner | null>(null);
  const [isActive, setIsActive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async () => {
    if (!videoRef.current) return;
    try {
      scannerRef.current = new BarcodeScanner();
      await scannerRef.current.start(videoRef.current, onScan);
      setIsActive(true);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Camera unavailable");
    }
  }, [onScan]);

  const stop = useCallback(() => {
    scannerRef.current?.stop();
    setIsActive(false);
  }, []);

  useEffect(() => {
    return () => { scannerRef.current?.stop(); };
  }, []);

  return { videoRef, isActive, error, start, stop };
}
