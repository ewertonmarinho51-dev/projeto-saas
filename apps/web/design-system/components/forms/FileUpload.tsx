"use client";

import { useRef, useState, type ReactNode } from "react";

import { Icon, type IconName } from "../core/Icon";

export interface UploadFile {
  name: string;
  meta?: string;
  icon?: IconName;
  /** 0–100; abaixo de 100 mostra a barra de progresso. */
  progress?: number;
  status?: ReactNode;
}

export interface FileUploadProps {
  title?: string;
  action?: string;
  hint?: string;
  accept?: string;
  multiple?: boolean;
  files?: UploadFile[];
  onFiles?: (arquivos: File[]) => void;
  onRemove?: (indice: number) => void;
}

/** Área de arrastar ou clicar, com a lista dos arquivos (progresso, status, remover). Opera pelo teclado. */
export function FileUpload({
  title = "Arraste arquivos aqui ou",
  action = "selecione no computador",
  hint = "PDF, DOCX, XLSX — até 200 MB por arquivo",
  accept,
  multiple = true,
  files = [],
  onFiles,
  onRemove,
}: FileUploadProps) {
  const [arrastando, setArrastando] = useState(false);
  const entrada = useRef<HTMLInputElement>(null);
  const escolher = (lista: FileList | null) => onFiles?.(Array.from(lista ?? []));
  return (
    <div className="gc-field">
      <div
        className="gc-upload"
        role="button"
        tabIndex={0}
        data-dragging={arrastando || undefined}
        onClick={() => entrada.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            entrada.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setArrastando(true);
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastando(false);
          escolher(e.dataTransfer.files);
        }}
      >
        <span className="gc-upload__icon">
          <Icon name="upload-simple" />
        </span>
        <span className="gc-upload__title">
          {title} <b>{action}</b>
        </span>
        <span className="gc-upload__hint">{hint}</span>
        <input ref={entrada} type="file" hidden accept={accept} multiple={multiple} onChange={(e) => escolher(e.target.files)} />
      </div>
      {files.length > 0 && (
        <div className="gc-filelist">
          {files.map((f, i) => (
            <div className="gc-file" key={i}>
              <span className="gc-file__icon">
                <Icon name={f.icon ?? "file-text"} />
              </span>
              <span className="gc-file__body">
                <span className="gc-file__name">{f.name}</span>
                {f.progress != null && f.progress < 100 ? (
                  <span className="gc-progress gc-progress--sm">
                    <span className="gc-progress__track">
                      <span className="gc-progress__fill" style={{ width: `${f.progress}%` }} />
                    </span>
                  </span>
                ) : (
                  <span className="gc-file__meta">{f.meta}</span>
                )}
              </span>
              {f.status}
              {onRemove && (
                <button
                  type="button"
                  className="gc-iconbtn gc-iconbtn--sm gc-iconbtn--danger"
                  aria-label={`Remover ${f.name}`}
                  onClick={() => onRemove(i)}
                >
                  <Icon name="x" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
