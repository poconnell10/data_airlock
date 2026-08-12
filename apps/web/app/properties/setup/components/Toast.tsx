"use client";

import { useEffect } from "react";
import { Check } from "lucide-react";

export function Toast({
  message,
  onDone,
}: {
  message: string | null;
  onDone: () => void;
}) {
  useEffect(() => {
    if (!message) return;
    const t = window.setTimeout(onDone, 2800);
    return () => window.clearTimeout(t);
  }, [message, onDone]);

  if (!message) return null;

  return (
    <div className="setup-toast" role="status">
      <Check className="h-3.5 w-3.5" strokeWidth={3} />
      <span>{message}</span>
    </div>
  );
}
