"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useTransition } from "react";

import { lerTrechos, perguntarAoGovBot, type Turno } from "@/app/app/govbot/acoes";
import {
  Accordion,
  AiDraftBlock,
  Alert,
  Badge,
  Button,
  ChatComposer,
  ChatMessage,
  Cite,
  ContextBar,
  EmptyState,
  Field,
  PageHead,
  PromptSuggestions,
  Select,
  SourceList,
  Textarea,
  type ContextItem,
  type PromptSuggestion,
} from "@/design-system";
import type { CitacaoDoGovBot, PropostaDoGovBot, RespostaDoGovBot, TrechoDoDocumento } from "@/lib/api";

type EstadoDaProposta = "pendente" | "editando" | "descartada";

type Mensagem =
  | { papel: "user"; texto: string }
  | { papel: "assistant"; texto: string; dados: RespostaDoGovBot; pergunta: string; hora: string };

const DOCUMENTOS = [
  { value: "dfd", label: "DFD" },
  { value: "etp", label: "ETP" },
  { value: "mapa_riscos", label: "Mapa de Riscos" },
  { value: "tr", label: "TR" },
];

const SIGLA = Object.fromEntries(DOCUMENTOS.map((d) => [d.value, d.label]));

const AVISO_BASE: Partial<Record<RespostaDoGovBot["base"], string>> = {
  falha: "A Base de Conhecimento não respondeu. Nenhum fundamento foi afirmado.",
  sem_referencias: "Nada na Base de Conhecimento sustenta esta pergunta.",
};

function aviso(d: RespostaDoGovBot): string {
  if (d.motor_falhou) return "O motor de IA não respondeu agora. Tente de novo em instantes.";
  if (d.proposta) return "Proposta gerada a partir do contexto listado. Nada foi gravado: confira as fontes e ajuste antes de usar.";
  return (
    AVISO_BASE[d.base] ??
    (d.ia
      ? "Confira as fontes antes de usar o conteúdo em documentos oficiais."
      : "Resposta da orientação do sistema, sem consulta ao motor de IA.")
  );
}

const ancora = (n: number) => `fonte-${n}`;

function rotuloDoTrecho(t: TrechoDoDocumento): string {
  const texto = t.texto.length > 70 ? `${t.texto.slice(0, 70)}…` : t.texto;
  return t.clausula ? `Cláusula ${t.clausula} · ${texto}` : texto;
}

function alvoDaProposta(p: PropostaDoGovBot): string {
  const clausula = /\/clausula\/(\d+)/.exec(p.alvo)?.[1];
  return [SIGLA[p.documento] ?? p.documento, clausula ? `Cláusula ${clausula}` : "Preâmbulo"].join(" · ");
}

function Paragrafos({ texto }: { texto: string }) {
  return texto.split(/\n{2,}/).map((p, j) => <p key={j}>{p}</p>);
}

/** Uma proposta: revisão humana local. Editar e descartar não saem deste navegador. */
function CartaoDaProposta({ proposta, editorHref }: { proposta: PropostaDoGovBot; editorHref?: string }) {
  const [estado, setEstado] = useState<EstadoDaProposta>("pendente");
  const [texto, setTexto] = useState(proposta.texto);
  const campo = useId();
  const editado = texto !== proposta.texto;
  const fontes = proposta.fontes.length === 1 ? "1 fonte" : `${proposta.fontes.length} fontes`;
  return (
    <div className="grid gap-2">
      <AiDraftBlock
        target={alvoDaProposta(proposta)}
        title="Redação proposta"
        meta={[fontes, `${proposta.palavras} palavras`, editado ? "editada por você" : ""].filter(Boolean).join(" · ")}
        status={estado === "descartada" ? "rejected" : "pending"}
        onReject={() => setEstado("descartada")}
        onUndo={() => setEstado("pendente")}
        onEdit={estado === "editando" ? undefined : () => setEstado("editando")}
      >
        {estado === "editando" ? (
          <div className="grid gap-2">
            <Field label="Texto da proposta" htmlFor={campo}>
              <Textarea id={campo} rows={6} value={texto} onChange={(e) => setTexto(e.target.value)} />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setEstado("pendente")}>
                Concluir edição
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setTexto(proposta.texto)} disabled={!editado}>
                Voltar ao texto do GovBot
              </Button>
            </div>
          </div>
        ) : (
          <Paragrafos texto={texto} />
        )}
      </AiDraftBlock>
      {estado !== "descartada" && (
        <>
          {proposta.motivo && <p className="gc-help">Motivo: {proposta.motivo}</p>}
          <Accordion items={[{ title: "Ver o texto atual do documento", content: <Paragrafos texto={proposta.antes} /> }]} />
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" icon="copy" onClick={() => navigator.clipboard?.writeText(texto)}>
              Copiar texto
            </Button>
            {editorHref && (
              <Button variant="ghost" size="sm" icon="arrow-square-out" href={editorHref}>
                Abrir o documento no editor
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * A conversa com o GovBot. Efêmera como no Streamlit: vive nesta aba e
 * some ao recarregar — o servidor não grava pergunta nem resposta. Toda
 * resposta vem da API, que lê o processo com o token da sessão.
 *
 * Com um trecho em foco, o GovBot pode propor redação. A proposta passa
 * pelos guardas do núcleo e volta como sugestão: por aqui nada é gravado.
 */
export function ConversaDoGovBot({
  processo,
  editor = {},
}: {
  processo: { id: string; rotulo: string } | null;
  editor?: Record<string, string>;
}) {
  const router = useRouter();
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [rascunho, setRascunho] = useState("");
  const [ocupado, iniciar] = useTransition();
  const [documento, setDocumento] = useState("");
  const [trechos, setTrechos] = useState<TrechoDoDocumento[] | null>(null);
  const [bloco, setBloco] = useState("");
  const ultimaMensagem = useRef<HTMLDivElement>(null);

  // A resposta nova abre pelo começo: uma proposta longa não pode nascer cortada.
  useEffect(() => {
    ultimaMensagem.current?.scrollIntoView({ block: "start" });
  }, [mensagens.length, ocupado]);

  useEffect(() => {
    if (!processo || !documento) return;
    let vivo = true;
    void lerTrechos(processo.id, documento).then((t) => vivo && setTrechos(t ?? []));
    return () => {
      vivo = false;
    };
  }, [processo, documento]);

  function escolherDocumento(valor: string) {
    setDocumento(valor);
    setBloco("");
    setTrechos(null);
  }

  function perguntar(texto: string) {
    const pergunta = texto.trim();
    if (!pergunta || ocupado) return;
    const historico: Turno[] = mensagens.map((m) => ({ papel: m.papel, texto: m.texto }));
    setErro(null);
    setRascunho("");
    setMensagens((atual) => [...atual, { papel: "user", texto: pergunta }]);
    iniciar(async () => {
      const r = await perguntarAoGovBot({
        pergunta,
        processoId: processo?.id ?? null,
        documento: documento || null,
        bloco: bloco || null,
        historico,
      });
      if (r.resposta) {
        const dados = r.resposta;
        const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        setMensagens((atual) => [...atual, { papel: "assistant", texto: dados.resposta, dados, pergunta, hora }]);
      } else {
        setErro(r.erro);
      }
    });
  }

  const trechoEscolhido = trechos?.find((t) => t.path === bloco);

  const contexto: ContextItem[] = [
    ...(processo
      ? [{ kind: "process" as const, icon: "folder-open" as const, label: processo.rotulo, onRemove: () => router.push("/app/govbot") }]
      : []),
    ...(documento
      ? [
          {
            kind: "document" as const,
            icon: "file-text" as const,
            label: trechoEscolhido ? `${SIGLA[documento]} · trecho escolhido` : (SIGLA[documento] ?? documento),
            onRemove: () => escolherDocumento(""),
          },
        ]
      : []),
    { kind: "knowledge", icon: "books", label: "Base de Conhecimento do órgão" },
  ];

  const sugestoes: PromptSuggestion[] = [
    ...(processo ? [{ icon: "clipboard-text" as const, label: "O que falta preencher neste processo?", description: "Campos obrigatórios do formulário" }] : []),
    ...(trechoEscolhido ? [{ icon: "pencil-simple" as const, label: "Reescreva este trecho com linguagem mais objetiva.", description: "Proposta para revisão, nada é gravado" }] : []),
    { icon: "scales", label: "Qual o fundamento legal do estudo técnico preliminar?", description: "Com as fontes da Base" },
    { icon: "file-text", label: "Qual a diferença entre DFD e ETP?" },
  ];

  // Uma numeração só na conversa: a citação da resposta e o painel dizem o mesmo número.
  const citadas = new Map<string, { n: number; citacao: CitacaoDoGovBot }>();
  for (const m of mensagens) {
    if (m.papel !== "assistant") continue;
    for (const c of m.dados.citacoes) if (!citadas.has(c.source_id)) citadas.set(c.source_id, { n: citadas.size + 1, citacao: c });
  }
  const numero = (c: CitacaoDoGovBot) => citadas.get(c.source_id)?.n ?? 0;
  const fonte = ({ n, citacao: c }: { n: number; citacao: CitacaoDoGovBot }, resumo: boolean) => ({
    n,
    id: resumo ? undefined : ancora(n),
    title: c.titulo,
    meta: [c.categoria, c.localizacao, ...c.dispositivos.slice(0, 3)].filter(Boolean).join(" · "),
    excerpt: resumo ? undefined : c.trecho,
  });

  const ultima = mensagens.reduce((fim, m, i) => (m.papel === "assistant" ? i : fim), -1);
  const perguntas = mensagens.filter((m) => m.papel === "user").length;

  const painelDeFontes = (
    <>
      <div className="flex items-center justify-between gap-3">
        <h2>Fontes desta conversa</h2>
        <Badge size="sm">{citadas.size}</Badge>
      </div>
      {citadas.size > 0 ? (
        <SourceList items={[...citadas.values()].map((c) => fonte(c, false))} />
      ) : (
        <p className="gc-help">Nenhuma fonte citada ainda.</p>
      )}
      <p className="gc-help">As fontes exibidas são só os trechos efetivamente citados nas respostas.</p>
    </>
  );

  return (
    <div className="grid h-[calc(100dvh-var(--topbar-height))] min-h-0 xl:grid-cols-[minmax(0,1fr)_calc(var(--space-16)*5.25)]">
      <section className="flex min-h-0 min-w-0 flex-col" aria-label="Conversa com o GovBot">
        <div className="grid gap-3 border-b border-linha bg-superficie px-[var(--page-padding-x)] py-4">
          {/* Com a conversa em curso, o espaço é das mensagens. */}
          <PageHead
            title="GovBot"
            desc={
              mensagens.length === 0
                ? "Pergunte sobre o processo e a legislação. Cada resposta indica as fontes da Base de Conhecimento que a sustentam."
                : undefined
            }
          />
          <ContextBar items={contexto} />
          {processo && (
            // A chave recolhe a escolha ao perguntar; o trecho segue na barra de contexto.
            <Accordion
              key={perguntas}
              items={[
                {
                  title: "Trabalhar em um trecho do documento",
                  meta: trechoEscolhido ? "1 trecho" : undefined,
                  content: (
                    <div className="grid items-start gap-3 md:grid-cols-[minmax(0,calc(var(--space-16)*3))_minmax(0,1fr)]">
                      <Field label="Documento" htmlFor="govbot-documento">
                        <Select
                          id="govbot-documento"
                          size="sm"
                          placeholder="Escolha"
                          options={DOCUMENTOS}
                          value={documento}
                          onChange={(e) => escolherDocumento(e.target.value)}
                        />
                      </Field>
                      <Field
                        label="Trecho"
                        htmlFor="govbot-trecho"
                        help={
                          documento && trechos?.length === 0
                            ? "Este documento ainda não tem texto."
                            : "Com um trecho em foco, o GovBot pode propor uma redação."
                        }
                      >
                        <Select
                          id="govbot-trecho"
                          size="sm"
                          placeholder={documento ? "Escolha" : "Escolha o documento primeiro"}
                          disabled={!trechos?.length}
                          options={(trechos ?? []).map((t) => ({ value: t.path, label: rotuloDoTrecho(t) }))}
                          value={bloco}
                          onChange={(e) => setBloco(e.target.value)}
                        />
                      </Field>
                    </div>
                  ),
                },
              ]}
            />
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-[var(--page-padding-x)] py-5">
          {mensagens.length === 0 ? (
            <div className="grid gap-4">
              <EmptyState
                icon="sparkle"
                title="Como posso ajudar no planejamento?"
                description="O GovBot explica, consulta a Base de Conhecimento e sugere redação, sempre com as fontes. Por aqui ele não altera o processo."
              />
              <PromptSuggestions items={sugestoes} onPick={(s) => perguntar(s.label)} />
            </div>
          ) : (
            <div className="grid gap-4" aria-live="polite">
              {mensagens.map((m, i) => (
                <div key={i} ref={i === mensagens.length - 1 ? ultimaMensagem : undefined} className="min-w-0">
                {m.papel === "user" ? (
                  <ChatMessage role="user" name="Você">
                    <p>{m.texto}</p>
                  </ChatMessage>
                ) : (
                  <ChatMessage
                    time={m.hora}
                    notice={aviso(m.dados)}
                    sources={
                      m.dados.citacoes.length > 0 ? (
                        <SourceList
                          compact
                          items={m.dados.citacoes.map((c) => fonte({ n: numero(c), citacao: c }, true))}
                        />
                      ) : undefined
                    }
                    actions={
                      <>
                        <Button variant="ghost" size="sm" icon="copy" onClick={() => navigator.clipboard?.writeText(m.texto)}>
                          Copiar
                        </Button>
                        {i === ultima && (
                          <Button variant="ghost" size="sm" icon="arrow-clockwise" disabled={ocupado} onClick={() => perguntar(m.pergunta)}>
                            Gerar novamente
                          </Button>
                        )}
                      </>
                    }
                  >
                    <Paragrafos texto={m.texto} />
                    {m.dados.citacoes.length > 0 && (
                      <p>
                        {m.dados.citacoes.map((c) => (
                          <Cite key={c.source_id} n={numero(c)} href={`#${ancora(numero(c))}`} />
                        ))}
                      </p>
                    )}
                    {m.dados.proposta && (
                      <div className="mt-3">
                        <CartaoDaProposta proposta={m.dados.proposta} editorHref={editor[m.dados.proposta.documento]} />
                      </div>
                    )}
                  </ChatMessage>
                )}
                </div>
              ))}
              {ocupado && <ChatMessage loading />}
            </div>
          )}
          {erro && <Alert variant="error" title={erro} />}
          {/* Sem a coluna, as fontes acompanham a conversa. */}
          {citadas.size > 0 && <div className="mt-5 grid gap-3 xl:hidden">{painelDeFontes}</div>}
        </div>

        <div className="border-t border-linha bg-superficie px-[var(--page-padding-x)] py-3">
          <ChatComposer
            value={rascunho}
            onChange={setRascunho}
            onSend={perguntar}
            busy={ocupado}
            placeholder="Pergunte sobre o processo ou a legislação"
            hint="A conversa fica só nesta aba. Revise antes de usar em documentos oficiais."
          />
        </div>
      </section>

      <aside className="hidden min-h-0 content-start gap-3 overflow-y-auto border-l border-linha bg-superficie p-4 xl:grid" aria-label="Fontes">
        {painelDeFontes}
      </aside>
    </div>
  );
}
