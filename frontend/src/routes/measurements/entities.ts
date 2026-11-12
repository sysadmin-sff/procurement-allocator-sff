import type {
  MeasurementsMeasurerMetrics,
  MeasurementsMetricsBlock,
  MeasurementsPeriod,
} from '../../api/measurements';
import { measurerLabel } from './format';
import styles from './Measurements.module.css';

/** A column/card subject: the company or one measurer group. Only selects
 * which API block to show — never combines blocks. */
export interface Entity {
  id: string;
  label: string;
  /** Measurer parameter for detail links; null — the group cannot be requested. */
  measurer: string | null | undefined;
  linkable: boolean;
  /** Stable index for the chart colour; -1 for the null group. */
  colorIndex: number;
}

const NULL_GROUP_ID = '__without_measurer__';

export function companyEntity(filterMeasurer: string | undefined): Entity {
  return { id: 'company', label: 'Компания', measurer: filterMeasurer, linkable: true, colorIndex: -1 };
}

export function measurerEntities(measurers: MeasurementsMeasurerMetrics[]): Entity[] {
  let colorIndex = 0;
  return measurers.map((m) => ({
    id: m.measurer_key ?? NULL_GROUP_ID,
    label: measurerLabel(m.measurer_key),
    measurer: m.measurer_key,
    linkable: m.measurer_key != null,
    colorIndex: m.measurer_key == null ? -1 : colorIndex++,
  }));
}

/** The API block of `entity` in a period (or the total section). */
export function blockOf(
  section: Pick<MeasurementsPeriod, 'company' | 'measurers'>,
  entity: Entity,
): MeasurementsMetricsBlock | undefined {
  if (entity.id === 'company') return section.company;
  return section.measurers.find((m) => (m.measurer_key ?? NULL_GROUP_ID) === entity.id);
}

const SEGMENT_CLASSES = [styles.seg0, styles.seg1, styles.seg2, styles.seg3, styles.seg4];

/** Chart colour of an entity; the null group is neutral. */
export function segmentClass(colorIndex: number): string {
  if (colorIndex < 0) return styles.segNone;
  return SEGMENT_CLASSES[colorIndex % SEGMENT_CLASSES.length];
}
