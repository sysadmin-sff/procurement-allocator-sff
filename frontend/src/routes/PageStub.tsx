import type { ReactNode } from 'react';
import styles from './PageStub.module.css';

interface PageStubProps {
  eyebrow: string;
  title: string;
  description: string;
  children?: ReactNode;
}

export function PageStub({ eyebrow, title, description, children }: PageStubProps) {
  return (
    <div className={styles.wrap}>
      <div className={styles.card}>
        <div className={styles.eyebrow}>{eyebrow}</div>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.description}>{description}</p>
        {children}
      </div>
    </div>
  );
}
