import React from 'react';
import { Database, GitBranch, FileText, Globe, Sparkles, Search, Cpu, Network, BookOpen, CheckCircle2 } from 'lucide-react';

const STATUS_ICONS = {
  // DB / price queries
  database:    Database,
  querying:    Database,
  'price':     Database,
  'indicator': Database,
  'sql':       Database,
  // Graph / sector
  sector:      Network,
  peer:        Network,
  mapping:     Network,
  graph:       Network,
  // News / web scraping
  news:        Globe,
  scraping:    Globe,
  'sharesansar': Globe,
  'merolagani':  Globe,
  // Knowledge base / vector
  knowledge:   BookOpen,
  'knowledge base': BookOpen,
  vector:      BookOpen,
  // Synthesis / analysis / LLM
  synthesizing: Sparkles,
  analyzing:    Sparkles,
  generating:   Sparkles,
  analysis:     Sparkles,
  'context window': Sparkles,
  // Generic
  searching:   Search,
  routing:     GitBranch,
  classified:  GitBranch,
};

/**
 * Pick the best icon from keywords in a status message.
 */
function getIcon(msg) {
  if (!msg) return Sparkles;
  const lower = msg.toLowerCase();
  for (const [key, IconComponent] of Object.entries(STATUS_ICONS)) {
    if (lower.includes(key)) return IconComponent;
  }
  return Cpu;
}

/**
 * StatusIndicator
 *
 * Renders a live step timeline during streaming:
 *   - Completed steps show a green checkmark and muted text
 *   - The active (latest) step pulses with an animated dot
 *   - Each new step slides in from below
 */
export default function StatusIndicator({ statusMessage, steps }) {
  // Multi-step timeline
  if (steps && steps.length > 0) {
    const latestStep = steps[steps.length - 1];
    const Icon = getIcon(latestStep);

    return (
      <div className="status-indicator-container">
        {/* Completed steps */}
        {steps.slice(0, -1).map((step, i) => {
          const StepIcon = getIcon(step);
          return (
            <div key={i} className="status-step-done status-slide-in">
              <CheckCircle2 className="status-step-icon-done" size={12} />
              <span className="status-step-text-done">{step}</span>
            </div>
          );
        })}

        {/* Active step */}
        <div className="status-step-active status-slide-in">
          <div className="status-icon-wrapper">
            <Icon className="status-lucide-icon animate-pulse" size={16} />
          </div>
          <div className="status-text-wrapper">
            <span className="status-dot animate-ping" />
            <span className="status-text">{latestStep}</span>
          </div>
        </div>
      </div>
    );
  }

  // Fallback: single status message
  const Icon = getIcon(statusMessage);
  return (
    <div className="status-indicator-container">
      <div className="status-icon-wrapper">
        <Icon className="status-lucide-icon animate-pulse" size={16} />
      </div>
      <div className="status-text-wrapper">
        <span className="status-dot animate-ping" />
        <span className="status-text">{statusMessage || 'Thinking...'}</span>
      </div>
    </div>
  );
}
