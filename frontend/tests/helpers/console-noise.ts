/**
 * Next.js dev-server hot-reload noise; never filter anything else here.
 *
 * In `next dev`, a Fast Refresh (HMR) cycle that lands while a fetch is in
 * flight logs: "Failed to fetch RSC payload for <url>. Falling back to browser
 * navigation. TypeError: Failed to fetch" with a stack through
 * fastRefreshReducerImpl / hot-reloader-client. It is dev-mode noise, not an
 * app error. Matches only that message; any other "Failed to fetch" stays an error.
 */
export function isDevHmrNoise(text: string): boolean {
  if (!text.includes("Failed to fetch RSC payload")) return false;
  return (
    text.includes("fastRefresh") ||
    text.includes("hot-reloader") ||
    text.includes("Falling back to browser navigation")
  );
}
