/**
 * LoadingIndicator — Bouncing dots typing indicator.
 * Matches the sample's typing-bounce animation.
 */
export default function LoadingIndicator() {
  return (
    <div className="loading-indicator" aria-label="Thinking…">
      <span className="loading-dot" style={{ animationDelay: '0ms' }} />
      <span className="loading-dot" style={{ animationDelay: '200ms' }} />
      <span className="loading-dot" style={{ animationDelay: '400ms' }} />
      <span className="loading-label">Thinking…</span>
    </div>
  );
}