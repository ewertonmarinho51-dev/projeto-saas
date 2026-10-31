"use client";

import { DownloadSimple } from "@phosphor-icons/react";
import { useActionState, useRef, useState } from "react";

import { emitirRelatorio, type EstadoDaEmissao } from "@/app/app/precos/acoes";
import { useJob } from "@/components/acompanhar-job";
import { botaoPrimario, botaoSecundario } from "@/components/ui";
import { Alert, ValidationSummary, type ValidationIssue } from "@/design-system";
import type { OpcaoDeRelatorio, PreparoDaEmissao } from "@/lib/api";

const FALHAS: Record<string, string> = {
  CIENCIA_REQUIRED: "Faltou a confirmação dos alertas desta versão da cesta. Recarregue a página e gere de novo.",
  EMISSION_UNAVAILABLE: "A emissão pela nova interface foi desligada. Emita pelo aplicativo de sempre.",
  INVALID_REPORT: "Este relatório não está disponível nesta configuração.",
  ARTIFACT_TOO_LARGE: "O arquivo passou do limite de entrega. Gere a memória analítica (XLSX).",
  DATABASE_UNAVAILABLE: "O banco não respondeu durante a geração. Tente de novo.",
  QUEUE_UNAVAILABLE: "A geração não chegou a começar. Tente de novo em instantes.",
  NOT_FOUND: "A pesquisa não está mais disponível para você.",
};

function tamanho(bytes?: number): string {
  if (!bytes) return "";
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
}

/**
 * Emissão dos relatórios. O que pedir (ciência), o que oferecer (formatos)
 * e se pode emitir (teto) vêm da API; aqui só se mostra e se pergunta.
 *
 * Preço atípico NÃO trava o relatório (pacote Jev, RF-03): o aviso informa
 * antes do clique, e o clique pede uma confirmação simples, registrada com
 * a versão da cesta que a pessoa viu.
 */
export function PainelDeEmissao({
  pesquisa,
  preparo,
  chave,
}: {
  pesquisa: string;
  preparo: PreparoDaEmissao;
  chave: string;
}) {
  const [estado, acao, enviando] = useActionState<EstadoDaEmissao, FormData>(emitirRelatorio, { erro: null });
  const [escolhida, setEscolhida] = useState<OpcaoDeRelatorio | null>(null);
  const dialogo = useRef<HTMLDialogElement>(null);

  if (!preparo.disponivel) return <Alert variant="neutral">{preparo.motivo}</Alert>;
  if (preparo.bloqueio) return <Alert variant="error">{preparo.bloqueio}</Alert>;

  const precisaConfirmar = preparo.requer_ciencia && !preparo.ciencia;
  const semPermissao = precisaConfirmar && !preparo.pode_registrar_ciencia;

  // Preço atípico e pendência avisam; quem impede a emissão é o `bloqueio`, acima.
  const conferencia: ValidationIssue[] = [
    ...(preparo.alertas.length > 0
      ? [{
          severity: "warning" as const,
          title: `${preparo.alertas.length} preço(s) merecem conferência.`,
          detail: "Você pode revisá-los antes ou emitir com a cesta atual. A emissão não é impedida.",
        }]
      : []),
    ...(preparo.pendencias.length > 0
      ? [{
          severity: "warning" as const,
          title: `${preparo.pendencias.length} item(ns) com pendência`,
          detail: "Sairão listados no documento.",
        }]
      : []),
    ...(preparo.ciencia
      ? [{
          severity: "info" as const,
          title: "Confirmação registrada para esta versão da cesta.",
          detail: "Se a cesta mudar, ela é pedida de novo.",
        }]
      : []),
  ];

  return (
    <form action={acao} className="grid gap-4">
      {conferencia.length > 0 && (
        <div data-testid="aviso-emissao">
          <ValidationSummary issues={conferencia} />
        </div>
      )}

      {semPermissao && (
        <p className="text-sm text-secundario">
          Esta cesta pede a confirmação dos alertas, que é do responsável pela pesquisa (ou do administrador).
        </p>
      )}

      <input type="hidden" name="pesquisa" value={pesquisa} />
      {/* Chave da renderização; o servidor junta tipo e formato. Duplo clique no
          mesmo relatório não gera dois. */}
      <input type="hidden" name="chave" value={chave} />
      <input type="hidden" name="assinatura" value={precisaConfirmar ? preparo.assinatura : ""} />

      <div className="flex flex-wrap gap-2" role="group" aria-label="Relatórios disponíveis">
        {preparo.opcoes.map((o) => (
          <button
            key={`${o.tipo}-${o.formato}`}
            type="submit"
            name="opcao"
            value={`${o.tipo}:${o.formato}`}
            className={botaoSecundario}
            disabled={enviando || semPermissao}
            onClick={(e) => {
              if (!precisaConfirmar) return;
              // Com alertas sem ciência, o clique abre o aviso; quem envia é ele.
              e.preventDefault();
              setEscolhida(o);
              dialogo.current?.showModal();
            }}
          >
            {o.rotulo}
          </button>
        ))}
      </div>

        <dialog
          ref={dialogo}
          aria-labelledby="titulo-ciencia"
          className="m-auto w-[min(40rem,calc(100vw-2rem))] rounded-[var(--radius-ui)] border border-linha bg-superficie p-0 text-texto backdrop:bg-black/40"
        >
          <div className="grid max-h-[80dvh] gap-4 overflow-y-auto p-6">
            <h2 id="titulo-ciencia" className="text-lg font-semibold">
              Preços que merecem conferência
            </h2>
            {preparo.alertas.length > 0 && (
              <>
                <p className="text-sm">
                  Há {preparo.alertas.length} preço(s) que merecem conferência. Você pode revisar os valores sinalizados ou
                  continuar com a cesta atual. A emissão não será impedida.
                </p>
                <ul className="grid gap-2 text-sm">
                  {preparo.alertas.slice(0, 40).map((a, i) => (
                    <li key={i} className="grid gap-0.5 sm:grid-cols-[3rem_1fr_auto] sm:gap-3">
                      <span className="font-mono text-secundario">{String(a.numero).padStart(2, "0")}</span>
                      <span>
                        {a.descricao}
                        <span className="block text-xs text-secundario">{a.origem || "Origem não informada"}</span>
                      </span>
                      <span className="tabular-nums font-medium">{a.valor?.exibicao ?? ""}</span>
                    </li>
                  ))}
                </ul>
                {preparo.alertas.length > 40 && (
                  <p className="text-xs text-secundario">E mais {preparo.alertas.length - 40} cotação(ões).</p>
                )}
              </>
            )}
            {preparo.pendencias.length > 0 && (
              <p className="text-sm">
                {preparo.pendencias.length} item(ns) com pendência constarão do documento:{" "}
                <span className="font-mono">
                  {preparo.pendencias
                    .slice(0, 30)
                    .map((p) => String(p.numero).padStart(2, "0"))
                    .join(", ")}
                  {preparo.pendencias.length > 30 ? ", ..." : ""}
                </span>
                .
              </p>
            )}
            <p className="text-xs text-secundario">
              Esta confirmação não aprova os preços: registra que você viu os alertas antes de emitir.
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" className={botaoSecundario} onClick={() => dialogo.current?.close()}>
                Voltar e revisar
              </button>
              <button
                type="submit"
                name="opcao"
                value={escolhida ? `${escolhida.tipo}:${escolhida.formato}` : ""}
                className={botaoPrimario}
                disabled={enviando || !escolhida}
                onClick={() => dialogo.current?.close()}
              >
                {enviando ? "Gerando..." : "Estou ciente, gerar relatório"}
              </button>
            </div>
          </div>
        </dialog>

      {enviando && (
        <p role="status" className="text-sm text-secundario">
          Pedindo o relatório...
        </p>
      )}
      {estado.erro && <Alert variant="error">{estado.erro}</Alert>}
    </form>
  );
}

/** Acompanha a geração e oferece o arquivo quando ele fica pronto. */
export function ProgressoDoRelatorio({ jobId }: { jobId: string }) {
  const { job, erro } = useJob(jobId);
  if (!job) {
    return (
      <p role="status" className="text-sm text-secundario">
        {erro ?? "Consultando o relatório..."}
      </p>
    );
  }
  if (job.estado === "succeeded" && job.resultado.nome) {
    return (
      <div role="status" aria-live="polite" className="grid gap-2 rounded-[var(--radius-ui)] bg-ok-fundo px-4 py-3 text-sm text-ok" data-testid="progresso-relatorio">
        <span>Relatório pronto. O arquivo fica disponível por 30 minutos.</span>
        <a href={`/app/precos/jobs/${job.id}/arquivo`} download className={`${botaoPrimario} justify-self-start`}>
          <DownloadSimple size={18} weight="bold" aria-hidden />
          Baixar {job.resultado.nome}
        </a>
        <span className="font-mono text-xs text-secundario">
          {tamanho(job.resultado.tamanho)}
          {job.resultado.sha256 ? ` | SHA-256 ${job.resultado.sha256.slice(0, 16)}` : ""}
        </span>
      </div>
    );
  }
  const falhou = job.estado === "failed" || job.estado === "cancelled";
  const texto = falhou
    ? (job.resultado.mensagem || FALHAS[job.erro_codigo] || "O relatório não pôde ser gerado. Tente de novo.")
    : job.estado === "queued"
      ? "Relatório na fila."
      : "Gerando o relatório...";
  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-[var(--radius-ui)] px-4 py-3 text-sm ${falhou ? "bg-erro-fundo text-erro" : "bg-acento-claro text-texto"}`}
      data-testid="progresso-relatorio"
    >
      {texto}
      {erro && <span className="block text-xs text-secundario">{erro}</span>}
    </div>
  );
}
