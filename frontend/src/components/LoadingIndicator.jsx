/**
 * LoadingIndicator — Three animated bouncing dots.
 * Shown while waiting for the first token from the AI.
 */
export default function LoadingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-2 px-1">
      <span className="text-sm text-surface-500 dark:text-surface-400 mr-2">
        Thinking
      </span>
      <span className="w-2 h-2 rounded-full bg-brand-500 animate-bounce-dot-1" />
      <span className="w-2 h-2 rounded-full bg-brand-400 animate-bounce-dot-2" />
      <span className="w-2 h-2 rounded-full bg-brand-300 animate-bounce-dot-3" />
    </div>
  );
}
