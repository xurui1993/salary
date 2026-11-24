import React from 'react';

interface DemoDataChipProps {
  /** Whether demo data is currently active on this view */
  demoActive: boolean;
  /** Whether the user can re-enable demo data (unauthenticated & no live records) */
  canShowDemo: boolean;
  /** Toggle handler to hide or show demo data */
  onToggle: () => void;
  /** Optional tooltip hint */
  hint?: string;
}

/**
 * Compact, subtle toolbar indicator for frontend preview/demo datasets.
 * Automatically disappears once the user signs in to a real platform or live backend records exist.
 */
export function DemoDataChip(_props: DemoDataChipProps) {
  return null;
}
