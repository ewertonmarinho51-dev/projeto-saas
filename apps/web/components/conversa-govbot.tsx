"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { perguntarAoGovBot, type Turno } from "@/app/app/govbot/acoes";
import {
  Alert,
  Badge,
  Button,
  ChatComposer,
  ChatMessage,
  ContextBar,
  EmptyState,
  PageHead,
  PromptSuggestions,
  SourceList,
  type ContextItem,
  type PromptSuggestion,
} from "@/design-system";
import type { CitacaoDoGovBot, RespostaDoGovBot } from "@/lib/api";

type Mensagem = { papel: "user"; texto: string } | { papel: "assistant"; texto: string; dados: RespostaDoGovBot };

const AVISO_BASE: Partial<Record<RespostaDoGovBot["base"], string>> = {
  falha: "A Base de Conhecimento não respondeu. Nenhum fundamento foi afirmado.",
  sem_referencias: "Nada na Base de Conhecimento sustenta esta pergunta.",
};

function aviso(d: RespostaDoGovBot): string {
  if (d.motor_falhou) return "O motor de IA não respondeu agora. Tente de novo em instantes.";
  return (
    AVISO_BASE[d.base] ??
    (d.ia
      ? "Confira as fontes antes de usar o conteúdo em documentos oficiais."
      : "Resposta da orientação do sistema, sem consulta ao motor de IA.")
  );
}

function fontes(citacoes: CitacaoDoGovBot[], resumo: boolean) {
  return citacoes.map((c, i) => ({
    n: i + 1,
    title: c.titulo,
    meta: [c.categoria, ...c.dispositivos.slice(0, 3)].filter(Boolean).join(" · "),
    excerpt: resumo ? undefined : c.trecho,
  }));
}

/**
 * A conversa com o GovBot. Efêmera como no Streamlit: vive nesta aba e
 * some ao recarregar — o servidor não grava pergunta nem resposta. Toda
 * resposta vem da API, que lê o processo com o token da sessão.
 */
export function ConversaDoGovBot({ processo }: { processo: { id: string; rotulo: string } | null }) {
  const router = useRouter();
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [rascunho, setRascunho] = useState("");
  const [ocupado, iniciar] = useTransition();

  function perguntar(texto: string) {
    const pergunta = texto.trim();
    if (!pergunta || ocupado) return;
    const historico: Turno[] = mensagens.map((m) => ({ papel: m.papel, texto: m.texto }));
    setErro(null);
    setRascunho("");
    setMensagens((atual) => [...atual, { papel: "user", texto: pergunta }]);
    iniciar(async () => {
      const r = await perguntarAoGovBot({ pergunta, processoId: processo?.id ?? null, historico });
      if (r.resposta) {
        const dados = r.resposta;
        setMensagens((atual) => [...atual, { papel: "assistant", texto: dados.resposta, dados }]);
      } else {
        setErro(r.erro);
      }
    });
  }

  const contexto: ContextItem[] = [
    ...(processo
      ? [{ kind: "process" as const, icon: "folder-open" as const, label: processo.rotulo, onRemove: () => router.push("/app/govbot") }]
      : []),
    { kind: "knowledge", icon: "books", label: "Base de Conhecimento do órgão" },
  ];

  const sugestoes: PromptSuggestion[] = [
    ...(processo ? [{ icon: "clipboard-text" as const, label: "O que falta preencher neste processo?", description: "Campos obrigatórios do formulário" }] : []),
    { icon: "scales", label: "Qual o fundamento legal do estudo técnico preliminar?", description: "Com as fontes da Base" },
    { icon: "file-text", label: "Qual a diferença entre DFD e ETP?" },
  ];

  const citadas = new Map<string, CitacaoDoGovBot>();
  for (const m of mensagens) if (m.papel === "assistant") for (const c of m.dados.citacoes) citadas.set(c.source_id, c);

  const painelDeFontes = (
    <>
      <div className="flex items-center justify-between gap-3">
        <h2>Fontes desta conversa</h2>
        <Badge size="sm">{citadas.size}</Badge>
      </div>
      {citadas.size > 0 ? (
        <SourceList items={fontes([...citadas.values()], false)} />
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
          <PageHead
            title="GovBot"
            desc="Pergunte sobre o processo e a legislação. Cada resposta indica as fontes da Base de Conhecimento que a sustentam."
          />
          <ContextBar items={contexto} />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-[var(--page-padding-x)] py-5">
          {mensagens.length === 0 ? (
            <div className="grid gap-4">
              <EmptyState
                icon="sparkle"
                title="Como posso ajudar no planejamento?"
                description="O GovBot explica e consulta a Base de Conhecimento, sempre com as fontes. Por aqui ele não altera o processo."
              />
              <PromptSuggestions items={sugestoes} onPick={(s) => perguntar(s.label)} />
            </div>
          ) : (
            <div className="grid gap-4" aria-live="polite">
              {mensagens.map((m, i) =>
                m.papel === "user" ? (
                  <ChatMessage key={i} role="user" name="Você">
                    <p>{m.texto}</p>
                  </ChatMessage>
                ) : (
                  <ChatMessage
                    key={i}
                    notice={aviso(m.dados)}
                    sources={m.dados.citacoes.length > 0 ? <SourceList compact items={fontes(m.dados.citacoes, true)} /> : undefined}
                    actions={
                      <Button variant="ghost" size="sm" icon="copy" onClick={() => navigator.clipboard?.writeText(m.texto)}>
                        Copiar
                      </Button>
                    }
                  >
                    {m.texto.split(/\n{2,}/).map((p, j) => (
                      <p key={j}>{p}</p>
                    ))}
                  </ChatMessage>
                ),
              )}
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
