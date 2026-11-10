import {
  measurementsQueryString,
  type MeasurementsVisitsQuery,
} from '../../api/measurements';

/** The detail page URL: same parameter names as GET /measurements/metrics/visits. */
export function visitsHref(query: MeasurementsVisitsQuery): string {
  return `/measurements/visits${measurementsQueryString(query)}`;
}

/** Router state handed to the detail page so «← К метрикам» restores the filters. */
export interface VisitsBackState {
  back?: string;
}
