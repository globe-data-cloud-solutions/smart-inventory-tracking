"use client";

import { useScanner } from "@/hooks/useScanner";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/Button";

interface BarcodeScannerProps {
  onScan: (code: string) => void;
}

export function BarcodeScanner({ onScan }: BarcodeScannerProps) {
  const { videoRef, isActive, error, start, stop } = useScanner(onScan);

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative w-full max-w-sm overflow-hidden rounded-lg bg-black">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video
          ref={videoRef}
          className="h-64 w-full object-cover"
          playsInline
          muted
        />
        {!isActive && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60">
            <span className="text-sm text-white">{t("scanner.idle")}</span>
          </div>
        )}
      </div>

      {error && (
        <p className="text-sm text-red-600">{error}</p>
      )}

      <div className="flex gap-2">
        {!isActive ? (
          <Button onClick={() => void start()}>{t("scanner.start")}</Button>
        ) : (
          <Button variant="outline" onClick={stop}>{t("scanner.stop")}</Button>
        )}
      </div>
    </div>
  );
}
