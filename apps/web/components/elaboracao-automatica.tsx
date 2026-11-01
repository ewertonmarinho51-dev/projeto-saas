"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { iniciarElaboracao } from "@/app/app/processos/[id]/elaboracao/acoes";
import { AiProcessing, Alert, Badge, Button, Card, Stepper, type StepItem } from "@/design-system";
import type { DocumentoDaElaboracao, Elaboracao, Job, SituacaoDoDocumento } from "@/lib/api";

const ATIVOS = ["queued", "running"];
const CONSULTA_MS = 3000;

const ROTULO_DA_ETAPA: Record<string, string> = { edital: "Minuta do edital" };

const SITUACAO: Record<SituacaoDoDocumento, { rotulo: string; variante: "neutral" | "warning" | "success" }> = {
  pendente: { rotulo: "A elaborar", variante: "neutral" },
  gerado: { rotulo: "Aguardando revisão", variante: "warning" },
  em_revisao: { rotulo: "Em revisão", variante: "warning" },
  aprovado: { rotulo: "Aprovado", variante: "success" },
  emitido: { rotulo: "Emitido", variante: "success" },
};

const FALHAS: Record<string, string> = {
  ABANDONED: "A elaboração foi interrompida antes de terminar.",
  QUEUE_UNAVAILABLE: "A fila de elaboração não respondeu.",
  DATABASE_UNAVAILABLE: "O banco de dados não respondeu durante a elaboração.",
};

function concluido(d: DocumentoDaElaboracao): boolean {
  return d.situacao === "aprovado" || d.situacao === "emitido";
}

function emCurso(job: Job | null): boolean {
  return job !== null && ATIVOS.includes(job.estado);
}

function etapas(estado: Elaboracao): StepItem[] {
  const passos: StepItem[] = [
    {
      label: "Dados da demanda",
      state: estado.faltantes.length ? "current" : "done",
    },
  ];
  let atual = estado.faltantes.length === 0;
  for (const d of estado.documentos) {
    const feito = concluido(d);
    const falhou = atual && !feito && estado.job?.estado === "failed";
    passos.push({
      label: ROTULO_DA_ETAPA[d.tipo] ?? d.sigla,
      state: feito ? "done" : falhou ? "error" : atual ? "current" : "todo",
    });
    if (!feito) atual = false;
  }
  passos.push({
    label: "Concluído",
    state: estado.proximo.acao === "concluido" ? "done" : "todo",
  });
  return passos;
}

function passosDaGeracao(job: Job, tipo: string, sigla: string) {
  const redacao =
    tipo === "edital" || tipo === "arp" ? "Montando a minuta pelo catálogo de cláusulas" : `Redigindo ${sigla}`;
  const textos = [
    "Lendo dados da demanda",
    "Consultando base de conhecimento do órgão",
    redacao,
    "Revisando o texto",
    "Salvando no processo",
  ];
  return textos.map((label, i) => ({
    label,
    state: (job.estado === "queued" ? "pending" : i < job.feitos ? "done" : i === job.feitos ? "active" : "pending") as
      "pending" | "done" | "active",
  }));
}

function editor(processoId: string, documentoId: string): string {
  return `/app/processos/${processoId}/documentos/${documentoId}/editar`;
}

/**
 * A jornada do processo: etapas, próxima ação e documentos. Tudo vem do estado
 * que a API calcula; a tela só o desenha e, com geração em curso, relê a cada
 * 3 s. Recarregar a página volta ao mesmo ponto, porque o job mora no banco.
 *
 * A abertura no editor é carga de página inteira: o WebAssembly do motor depende
 * da CSP daquela rota, e a navegação interna manteria a CSP desta página.
 */
export function ElaboracaoAutomatica({ processoId, inicial }: { processoId: string; inicial: Elaboracao }) {
  const router = useRouter();
  const [estado, setEstado] = useState(inicial);
  const [erro, setErro] = useState<string | null>(null);
  const [semResposta, setSemResposta] = useState(false);
  const [iniciando, iniciar] = useTransition();
  const ativo = emCurso(estado.job);

  useEffect(() => {
    if (!ativo) return;
    let vivo = true;
    let espera: ReturnType<typeof setTimeout>;
    async function consultar() {
      try {
        const r = await fetch(`/app/processos/${processoId}/elaboracao`, {
          cache: "no-store",
        });
        if (!r.ok) throw new Error(String(r.status));
        const novo = (await r.json()) as Elaboracao;
        if (!vivo) return;
        setEstado(novo);
        setSemResposta(false);
        if (!emCurso(novo.job)) {
          router.refresh();
          return;
        }
      } catch {
        if (vivo) setSemResposta(true);
      }
      if (vivo) espera = setTimeout(consultar, CONSULTA_MS);
    }
    espera = setTimeout(consultar, CONSULTA_MS);
    return () => {
      vivo = false;
      clearTimeout(espera);
    };
  }, [ativo, processoId, router]);

  function comecar() {
    setErro(null);
    iniciar(async () => {
      const r = await iniciarElaboracao(processoId, estado.proximo.tipo);
      if (r.ok) setEstado(r.estado);
      else setErro(r.erro);
    });
  }

  const { job, proximo } = estado;
  const atual = estado.documentos.find((d) => d.tipo === proximo.tipo);
  const sigla = proximo.sigla ?? atual?.sigla ?? "documento";
  const primeiro = estado.documentos.every((d) => d.situacao === "pendente");
  const documentoDoJob = estado.documentos.find((d) => d.tipo === job?.resultado.documento);

  return (
    <>
      <Card>
        <Stepper steps={etapas(estado)} ariaLabel="Etapas da fase preparatória" />
      </Card>

      <Card title="Próxima ação" data-testid="proxima-acao">
        <div className="grid gap-4" aria-live="polite">
          {erro && <Alert variant="error" title={erro} />}

          {job && emCurso(job) ? (
            <AiProcessing
              title={job.estado === "queued" ? "Aguardando a vez na fila" : `Gerando ${documentoDoJob?.sigla ?? sigla}`}
              steps={passosDaGeracao(job, documentoDoJob?.tipo ?? "", documentoDoJob?.sigla ?? sigla)}
              progress={job.progresso}
              footer={
                <p className="text-sm text-[var(--text-secondary)]">
                  {semResposta
                    ? "Sem resposta do servidor; tentando de novo."
                    : "Pode sair desta tela: a elaboração continua, e o resultado fica no processo."}
                </p>
              }
            />
          ) : proximo.acao === "formulario" ? (
            <>
              <Alert variant="info" compact>
                {estado.faltantes.length === 1
                  ? `Falta 1 campo obrigatório: ${estado.faltantes[0]}.`
                  : `Faltam ${estado.faltantes.length} campos obrigatórios: ${estado.faltantes.join(", ")}.`}
              </Alert>
              <div>
                <Button size="lg" iconRight="arrow-right" href={`/app/processos/${processoId}/formulario`}>
                  Preencher dados da demanda
                </Button>
              </div>
            </>
          ) : proximo.acao === "elaborar" ? (
            <>
              {job?.estado === "failed" ? (
                <Alert variant="error" title={`Não foi possível elaborar o ${sigla}`}>
                  {job.resultado.mensagem || FALHAS[job.erro_codigo] || "A elaboração não terminou."} O que já estava no
                  processo foi preservado.
                </Alert>
              ) : (
                <p>
                  {primeiro
                    ? `Os dados da demanda estão completos. A IA redige o ${sigla} com esses dados e as regras do órgão, e você revisa antes de aprovar.`
                    : `O documento anterior foi aprovado. O ${sigla} herda o que já foi decidido, e você revisa antes de aprovar.`}
                </p>
              )}
              <div>
                <Button
                  size="lg"
                  icon={job?.estado === "failed" ? "arrows-clockwise" : "sparkle"}
                  loading={iniciando}
                  disabled={iniciando}
                  onClick={comecar}
                >
                  {job?.estado === "failed"
                    ? "Tentar novamente"
                    : primeiro
                      ? "Iniciar elaboração automática"
                      : `Elaborar ${sigla}`}
                </Button>
              </div>
            </>
          ) : proximo.acao === "revisar" && atual ? (
            <>
              <p>
                {atual.situacao === "gerado"
                  ? `${sigla} pronto para revisão. Confira o texto no WordCraft e aprove para seguir ao próximo documento.`
                  : `${sigla} em revisão (revisão ${atual.revisao}). Aprove no WordCraft para seguir ao próximo documento.`}
              </p>
              {atual.revisao != null || estado.escrita ? (
                <div>
                  <Button size="lg" icon="pencil-simple" reloadDocument href={editor(processoId, atual.id)}>
                    Revisar no WordCraft
                  </Button>
                </div>
              ) : (
                <Alert variant="warning" compact>
                  A gravação de documentos ainda não está liberada neste ambiente.
                </Alert>
              )}
            </>
          ) : (
            <Alert variant="success" title="Todos os documentos foram aprovados." />
          )}
        </div>
      </Card>

      <Card title="Documentos" subtitle="A sequência da fase preparatória deste processo." divided>
        <ul className="grid gap-3" data-testid="documentos-do-processo">
          {estado.documentos.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-3">
              <span className="grid gap-0.5">
                <span className="font-medium">{d.rotulo}</span>
                <span className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                  <Badge size="sm" variant={SITUACAO[d.situacao].variante}>
                    {SITUACAO[d.situacao].rotulo}
                  </Badge>
                  {d.revisao != null && `Revisão ${d.revisao}`}
                </span>
              </span>
              {/* Sem revisão nativa, abrir importa o texto gerado: é gravação. */}
              {d.situacao !== "pendente" && (d.revisao != null || estado.escrita) && (
                <Button
                  size="sm"
                  variant="secondary"
                  icon="pencil-simple"
                  reloadDocument
                  href={editor(processoId, d.id)}
                >
                  Abrir no editor
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
