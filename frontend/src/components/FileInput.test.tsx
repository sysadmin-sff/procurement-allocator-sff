import { createRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { FileInput } from './FileInput';
import { fileMatchesAccept } from './fileAccept';

/* jsdom has no DataTransfer constructor and only accepts a real FileList on
   input.files — stub both so the drop path can be exercised. */
class FakeDataTransfer {
  private list: File[] = [];
  items = { add: (file: File) => this.list.push(file) };
  get files() {
    return this.list as unknown as FileList;
  }
}

function stubFilesProperty(input: HTMLInputElement) {
  let current: FileList | null = null;
  Object.defineProperty(input, 'files', {
    configurable: true,
    get: () => current,
    set: (value: FileList) => {
      current = value;
    },
  });
}

function drop(zone: HTMLElement, file: File) {
  const dataTransfer = { files: [file], types: ['Files'] };
  fireEvent.dragOver(zone, { dataTransfer });
  fireEvent.drop(zone, { dataTransfer });
}

describe('fileMatchesAccept', () => {
  it('matches extensions and mime wildcards', () => {
    const pdf = new File(['x'], 'Quote.PDF', { type: 'application/pdf' });
    const png = new File(['x'], 'photo.png', { type: 'image/png' });
    const doc = new File(['x'], 'a.docx', { type: 'application/msword' });
    expect(fileMatchesAccept(pdf, '.pdf,image/*')).toBe(true);
    expect(fileMatchesAccept(png, '.pdf,image/*')).toBe(true);
    expect(fileMatchesAccept(doc, '.pdf,image/*')).toBe(false);
    expect(fileMatchesAccept(doc, undefined)).toBe(true);
  });
});

describe('FileInput', () => {
  beforeEach(() => {
    vi.stubGlobal('DataTransfer', FakeDataTransfer);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('keeps the input inside its label so a click opens the picker on macOS', () => {
    render(<FileInput accept=".pdf" />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.closest('label')).toHaveTextContent('Выбрать файл');
  });

  it('dropping a file puts it into the input and shows its name', () => {
    const ref = createRef<HTMLInputElement>();
    const onChange = vi.fn();
    render(<FileInput ref={ref} accept=".pdf,image/*" onChange={onChange} />);
    stubFilesProperty(ref.current!);
    const file = new File(['%PDF'], 'answer.pdf', { type: 'application/pdf' });

    drop(screen.getByTestId('file-drop-zone'), file);

    expect(ref.current!.files?.[0]).toBe(file);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.getByText('answer.pdf')).toBeInTheDocument();
  });

  it('rejects a file that does not match accept', () => {
    const ref = createRef<HTMLInputElement>();
    render(<FileInput ref={ref} accept=".pdf" />);
    stubFilesProperty(ref.current!);

    drop(screen.getByTestId('file-drop-zone'), new File(['x'], 'a.docx'));

    expect(ref.current!.files).toBeNull();
    expect(screen.getByText('Этот тип файла не подходит')).toBeInTheDocument();
  });

  it('ignores drops while disabled', () => {
    const ref = createRef<HTMLInputElement>();
    render(<FileInput ref={ref} accept=".pdf" disabled />);
    stubFilesProperty(ref.current!);

    drop(screen.getByTestId('file-drop-zone'), new File(['x'], 'a.pdf'));

    expect(ref.current!.files).toBeNull();
  });
});
