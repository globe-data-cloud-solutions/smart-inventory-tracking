"use client";

import { useEffect, useRef } from "react";

/** Error banner for the top of a panel body; scrolls itself into view when it appears or changes. */
export function PanelError({ message }: { message: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (message) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [message]);
  if (!message) return null;
  return (
    <div ref={ref} role="alert" data-testid="panel-error" className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-4">
      {message}
    </div>
  );
}
