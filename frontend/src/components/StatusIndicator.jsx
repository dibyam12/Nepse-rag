import React from 'react';
import { Database, GitBranch, FileText, Globe, Sparkles, Search, Cpu, Network, BookOpen, Radio } from 'lucide-react';

const STATUS_ICONS = {
  // DB / price queries
  database:   Database,
  querying:   Database,
  'price':    Database,
  'indicator': Database,
  // Graph / sector
  sector:     Network,
  peer:       Network,
  mapping:    Network,
  graph:      Network,
  // News / web scraping
  news:       Globe,
  scraping:   Globe,
  'sharesansar': Globe,
  'merolagani':  Globe,
  // Knowledge base / vector
  knowledge:  BookOpen,
  'knowledge base': BookOpen,
  // Synthesis / analysis / LLM
  synthesizing: Sparkles,
  analyzing:    Sparkles,
  generating:   Sparkles,
  analysis:     Sparkles,
  // Generic
  searching:  Search,
};

export default function StatusIndicator({ statusMessage, steps }) {
  // Find appropriate icon based on keywords in the current message
  const getIcon = (msg) => {
    if (!msg) return Sparkles;
    const lower = msg.toLowerCase();
    for (const [key, IconComponent] of Object.entries(STATUS_ICONS)) {
      if (lower.includes(key)) return IconComponent;
    }
    return Cpu;
  };

  // If we have a steps history, render a timeline
  if (steps && steps.length > 0) {
    const latestStep = steps[steps.length - 1];
    const Icon = getIcon(latestStep);
    return (
      <div className="status-indicator-container">
        {/* Completed steps */}
        {steps.slice(0, -1).map((step, i) => {
          const StepIcon = getIcon(step);
          return (
            <div key={i} className="status-step-done">
              <StepIcon className="status-step-icon-done" size={12} />
              <span className="status-step-text-done">{step}</span>
            </div>
          );
        })}
        {/* Active step */}
        <div className="status-step-active">
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
