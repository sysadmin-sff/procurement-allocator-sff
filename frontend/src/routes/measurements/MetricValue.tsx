import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { VisitsBackState } from './links';
import styles from './Measurements.module.css';

/** A number that opens the detail page when `href` is given, plain text otherwise. */
export function MetricValue({
  href,
  testId,
  className,
  children,
}: {
  href?: string;
  testId?: string;
  className?: string;
  children: ReactNode;
}) {
  const location = useLocation();
  if (href == null) {
    return (
      <span className={className} data-testid={testId}>
        {children}
      </span>
    );
  }
  const state: VisitsBackState = { back: location.search };
  return (
    <Link
      to={href}
      state={state}
      className={[styles.metricLink, className].filter(Boolean).join(' ')}
      data-testid={testId}
    >
      {children}
    </Link>
  );
}
