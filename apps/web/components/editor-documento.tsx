"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  abrirSessao,
  aprovarRevisao,
  bloquearParaRevisao,
  confirmarFatos,
  encerrarSessao,
  enviarEventos,
  lerHistorico,
  liberarEdicao,
  restaurarRevisao,
  sincronizarFatos,
  type Falha,
} from "@/app/app/processos/[id]/documentos/[documentoId]/editar/acoes";
import {
  Alert,
  Badge,
  Button,
  DataList,
  Dialog,
  DocumentWorkspace,
  EmptyState,
  IconButton,
  Menu,
  Spinner,
  type SaveTone,
} from "@/design-system";
import type { DocumentoDoProcesso, FatosDoProcesso, RevisaoDoHistorico } from "@/lib/api";
import { montarHost, type HostMontado } from "@/lib/wordcraft/host-nativo";
import {
  dadosDoHost,
  faseDaPonte,
  TransporteDoEditor,
  type AberturaDoEditor,
  type EstadoDoEditor,
  type Fase,
} from "@/lib/wordcraft/transporte";

/**
 * WordCraft Workspace (Issue #137): o editor nativo em tela ampla.
 *
 * A tela não sabe salvar: o host nativo produz eventos, o transporte os leva
 * à ponte da API, e o que aparece como "salvo" é o ACK que a API devolveu
 * depois do commit. Abrir painel, entrar em foco e redimensionar a janela não
 * desmontam a área do documento — a instância nativa (seleção, Undo, sessão)
 * continua a mesma. Só uma restauração de revisão troca a instância, porque
 * o documento passou a ser outro.
 *
 * Celular (< 768 px na abertura): leitura segura, por exportação. A edição
 * nativa ainda não foi comprovada usável em toque; a decisão é tomada uma
 * vez, ao abrir, para um redimensionamento não derrubar a sessão.
 */

type Painel = "revisao" | "historico" | null;
type Modo = "edicao" | "leitura";

const STATUS: Record<string, { rotulo: string; variante: "neutral" | "info" | "success" | "brand" }> = {
  rascunho: { rotulo: "Rascunho", variante: "neutral" },
  em_revisao: { rotulo: "Em revisão", variante: "info" },
  aprovado: { rotulo: "Aprovado", variante: "success" },
  emitido: { rotulo: "Emitido", variante: "brand" },
};

const MOTIVO_DO_CONTROLE: Record<string, string> = {
  dirty: "há alterações ainda não salvas",
  pending: "um salvamento ainda está em andamento",
  stale: "a revisão mudou enquanto o pedido chegava",
  unavailable: "o editor não confirmou o bloqueio a tempo",
};

function salvamento(fase: Fase, estado: EstadoDoEditor | null): { tone: SaveTone; label: string } {
  const revisao = estado?.revision ?? 0;
  switch (fase) {
    case "abrindo":
      return { tone: "progress", label: "Abrindo documento…" };
    case "pronto":
      return { tone: "neutral", label: `Revisão ${revisao} aberta` };
    case "editando":
      return { tone: "warning", label: "Alterações não salvas" };
    case "salvando":
      return { tone: "progress", label: "Salvando…" };
    case "salvo":
      return { tone: "success", label: `Salvo · revisão ${revisao}` };
    case "erro":
      return estado && !estado.escrita
        ? { tone: "error", label: "Gravação indisponível" }
        : { tone: "error", label: "Falha ao salvar" };
    case "conflito":
      return { tone: "error", label: "Conflito de revisão" };
    case "bloqueado":
      return { tone: "neutral", label: `Revisão ${revisao} bloqueada para análise` };
    case "encerrado":
      return { tone: "error", label: "Sessão encerrada" };
  }
}

function mensagemDeFalha(f: Falha): string {
  if (f.mensagem) return f.mensagem;
  if (f.codigo === "DOCUMENT_WRITE_UNAVAILABLE") return "A gravação de documentos ainda não está liberada neste ambiente.";
  if (f.codigo === "WORDCRAFT_RUNTIME_UNAVAILABLE") return "O motor do editor não está disponível neste ambiente.";
  if (f.status === 404) return "Documento não encontrado, ou o editor não está liberado para você.";
  if (f.status === 401) return "Sua sessão expirou. Entre novamente.";
  if (f.status === 409) return "O documento mudou nesse meio-tempo. Reabra para ver a revisão atual.";
  return "Não foi possível concluir agora. Tente de novo em instantes.";
}

function linkDeExportacao(processoId: string, documentoId: string, formato: "docx" | "pdf", revisao: number, hash: string) {
  const q = new URLSearchParams({ formato, revisao: String(revisao), hash });
  return `/app/processos/${processoId}/documentos/${documentoId}/exportar?${q}`;
}

export function EditorDeDocumento({
  processo,
  documento,
}: {
  processo: { id: string; nome: string };
  documento: DocumentoDoProcesso;
}) {
  const router = useRouter();
  const area = useRef<HTMLDivElement>(null);
  const host = useRef<HostMontado | null>(null);
  const transporte = useRef<TransporteDoEditor | null>(null);

  const [modo, setModo] = useState<Modo | null>(null);
  const [abertura, setAbertura] = useState<AberturaDoEditor | null>(null);
  const [estado, setEstado] = useState<EstadoDoEditor | null>(null);
  const [fase, setFase] = useState<Fase>("abrindo");
  const [falhaDeAbertura, setFalhaDeAbertura] = useState<string | null>(null);
  const [falhaDoHost, setFalhaDoHost] = useState<string | null>(null);
  const [painel, setPainel] = useState<Painel>(null);
  const [foco, setFoco] = useState(false);
  const [aviso, setAviso] = useState<{ variante: "success" | "error" | "warning"; texto: string } | null>(null);
  const [aprovado, setAprovado] = useState(false);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [historico, setHistorico] = useState<RevisaoDoHistorico[] | null>(null);
  const [sair, setSair] = useState(false);
  const [fatos, setFatos] = useState<FatosDoProcesso | null>(null);
  const [fatosFalharam, setFatosFalharam] = useState(false);

  // Uma vez, ao abrir: a largura decide edição ou leitura (o breakpoint é o
  // token `--bp-md`). Edição abre a sessão — ponte nova no servidor. Em
  // desenvolvimento o StrictMode monta duas vezes: a abertura descartada é
  // encerrada na API.
  useEffect(() => {
    let vivo = true;
    const bp = getComputedStyle(document.documentElement).getPropertyValue("--bp-md").trim();
    const largo = bp ? window.matchMedia(`(min-width: ${bp})`).matches : true;
    const pedido = largo ? abrirSessao(processo.id, documento.id) : Promise.resolve(null);
    void pedido.then((r) => {
      if (!vivo) {
        if (r?.ok) void encerrarSessao(documento.id, r.abertura.instance_id);
        return;
      }
      if (r === null) {
        setModo("leitura");
        return;
      }
      setModo("edicao");
      if (r.ok) {
        setAbertura(r.abertura);
        setEstado(r.abertura);
        setFase(faseDaPonte(r.abertura.estado));
      } else {
        setFalhaDeAbertura(mensagemDeFalha(r));
      }
    });
    return () => {
      vivo = false;
    };
  }, [processo.id, documento.id]);

  // Monta o host nativo para ESTA abertura. Painel, foco e tamanho de janela
  // não entram nas dependências: nada disso pode recriar a instância.
  useEffect(() => {
    const raiz = area.current;
    if (!abertura || !raiz) return;
    let vivo = true;
    const t = new TransporteDoEditor(
      (lote) => enviarEventos(abertura.document_id, abertura.instance_id, lote),
      (novo) => {
        setEstado(novo);
        setFase(faseDaPonte(novo.estado));
        host.current?.atualizar(dadosDoHost(abertura, novo));
      },
      (f) => setFase(f),
      (f) => setFase((atual) => (atual === "bloqueado" ? atual : f)),
    );
    transporte.current = t;
    setFalhaDoHost(null);
    montarHost(raiz, dadosDoHost(abertura, abertura), t.setStateValue, (m) => vivo && setFalhaDoHost(m))
      .then((h) => {
        if (vivo) host.current = h;
        else h.desmontar();
      })
      .catch(() => vivo && setFalhaDoHost("O módulo do editor não carregou."));
    return () => {
      vivo = false;
      t.parar();
      host.current?.desmontar();
      host.current = null;
      transporte.current = null;
      void encerrarSessao(abertura.document_id, abertura.instance_id);
    };
  }, [abertura]);

  // Rede de segurança: o motor pesa 40 MB, mas abrir não pode ficar mudo.
  useEffect(() => {
    if (!abertura || fase !== "abrindo") return;
    const limite = setTimeout(() => setFalhaDoHost("O motor do editor não respondeu a tempo."), 120000);
    return () => clearTimeout(limite);
  }, [abertura, fase]);

  // Esc sai do foco. Teclas dentro do editor param no host e não chegam aqui.
  useEffect(() => {
    if (!foco) return;
    const aoTeclar = (e: KeyboardEvent) => e.key === "Escape" && setFoco(false);
    document.addEventListener("keydown", aoTeclar);
    return () => document.removeEventListener("keydown", aoTeclar);
  }, [foco]);

  const aplicarEstado = useCallback(
    (novo: EstadoDoEditor) => {
      setEstado(novo);
      setFase(faseDaPonte(novo.estado));
      if (abertura) host.current?.atualizar(dadosDoHost(abertura, novo));
    },
    [abertura],
  );

  const carregarHistorico = useCallback(async () => {
    setHistorico(null);
    const r = await lerHistorico(processo.id, documento.id);
    if (r.ok) setHistorico(r.revisoes);
    else setAviso({ variante: "error", texto: mensagemDeFalha(r) });
  }, [processo.id, documento.id]);

  const carregarFatos = useCallback(async () => {
    setFatos(null);
    setFatosFalharam(false);
    const r = await sincronizarFatos(processo.id);
    if (r.ok) {
      setFatos(r.fatos);
    } else {
      setFatosFalharam(true);
      setAviso({ variante: "error", texto: mensagemDeFalha(r) });
    }
  }, [processo.id]);

  const alternarPainel = (qual: Exclude<Painel, null>) => {
    const proximo = painel === qual ? null : qual;
    setPainel(proximo);
    if (proximo === "historico") void carregarHistorico();
    if (proximo === "revisao" && escrita) void carregarFatos();
  };

  const confirmar = async () => {
    if (!fatos) return;
    setOcupado("fatos");
    const r = await confirmarFatos(processo.id, fatos.pendentes.map((f) => f.id));
    setOcupado(null);
    if (r.ok) setFatos(r.fatos);
    else {
      setAviso({ variante: "error", texto: mensagemDeFalha(r) });
      void carregarFatos();
    }
  };

  const bloquear = async () => {
    if (!abertura) return;
    setOcupado("bloqueio");
    const r = await bloquearParaRevisao(abertura.document_id, abertura.instance_id);
    setOcupado(null);
    if (r.ok) aplicarEstado(r.estado);
    else setAviso({ variante: "warning", texto: mensagemDeFalha(r) });
  };

  const liberar = async () => {
    if (!abertura) return;
    setOcupado("liberacao");
    const r = await liberarEdicao(abertura.document_id, abertura.instance_id);
    setOcupado(null);
    if (r.ok) aplicarEstado(r.estado);
    else setAviso({ variante: "error", texto: mensagemDeFalha(r) });
  };

  const aprovar = async () => {
    if (!abertura) return;
    setOcupado("aprovacao");
    const r = await aprovarRevisao(abertura.document_id, abertura.instance_id);
    setOcupado(null);
    if (r.ok) {
      setEstado((e) => (e ? { ...e, status: r.status } : e));
      setAprovado(true);
      setAviso({ variante: "success", texto: `Revisão ${r.revisao} aprovada.` });
      router.refresh();
    } else {
      // A recusa mais comum é campo em falta, e o motivo do dono documental não diz qual.
      const dica =
        r.codigo === "DOCUMENT_REJECTED" ? " Confira se ainda há campos [PREENCHER] no texto, preencha e salve antes de aprovar." : "";
      setAviso({ variante: "error", texto: mensagemDeFalha(r) + dica });
    }
  };

  const restaurar = async (revisao: number) => {
    if (!abertura) return;
    setOcupado(`restaurar-${revisao}`);
    const r = await restaurarRevisao(abertura.document_id, abertura.instance_id, revisao);
    setOcupado(null);
    if (r.ok) {
      setAviso({ variante: "success", texto: `Revisão ${revisao} restaurada como revisão ${r.abertura.revision}.` });
      setFase(faseDaPonte(r.abertura.estado));
      setEstado(r.abertura);
      setAbertura(r.abertura);
      void carregarHistorico();
    } else {
      setAviso({ variante: "error", texto: mensagemDeFalha(r) });
    }
  };

  const voltarHref = `/app/processos/${processo.id}`;
  const comRascunho = ["editando", "salvando", "erro", "conflito"].includes(fase);
  const limpo = fase === "pronto" || fase === "salvo";
  const status = STATUS[estado?.status ?? documento.status ?? ""] ?? null;
  const escrita = estado?.escrita ?? false;
  const revisaoSalva = estado?.revision ?? documento.revisao ?? null;
  const hashSalvo = estado?.content_hash ?? documento.content_hash ?? null;

  const exportar =
    revisaoSalva && hashSalvo ? (
      <Menu
        align="end"
        trigger={({ open, toggle }) => (
          <Button size="sm" variant="secondary" icon="download-simple" iconRight="caret-down" aria-expanded={open} onClick={toggle}>
            Exportar
          </Button>
        )}
        items={[
          { group: `Revisão ${revisaoSalva} salva` },
          {
            label: "Word (DOCX)",
            icon: "file-text",
            onSelect: () => window.location.assign(linkDeExportacao(processo.id, documento.id, "docx", revisaoSalva, hashSalvo)),
          },
          {
            label: "PDF",
            icon: "file-pdf",
            onSelect: () => window.location.assign(linkDeExportacao(processo.id, documento.id, "pdf", revisaoSalva, hashSalvo)),
          },
        ]}
      />
    ) : null;

  const voltar = comRascunho ? (
    <Button size="sm" variant="ghost" icon="arrow-left" onClick={() => setSair(true)}>
      Voltar ao processo
    </Button>
  ) : (
    <Button size="sm" variant="ghost" icon="arrow-left" href={voltarHref}>
      Voltar ao processo
    </Button>
  );

  const notice = (() => {
    if (aviso) {
      return (
        <Alert
          variant={aviso.variante}
          compact
          onClose={() => setAviso(null)}
          actions={
            aprovado && aviso.variante === "success" ? (
              <Button size="sm" iconRight="arrow-right" href={voltarHref}>
                Gerar próximo documento
              </Button>
            ) : undefined
          }
        >
          {aviso.texto}
        </Alert>
      );
    }
    if (fase === "conflito") {
      return (
        <Alert
          variant="error"
          compact
          title="Outra sessão salvou este documento antes."
          actions={
            <Button size="sm" variant="secondary" icon="arrows-clockwise" onClick={() => window.location.reload()}>
              Reabrir documento
            </Button>
          }
        >
          Seu rascunho continua no editor e não foi gravado. Copie o que precisar e reabra para ver a revisão atual.
        </Alert>
      );
    }
    if (fase === "encerrado") {
      return (
        <Alert
          variant="warning"
          compact
          title="A sessão do editor terminou."
          actions={
            <Button size="sm" variant="secondary" icon="arrows-clockwise" onClick={() => window.location.reload()}>
              Reabrir documento
            </Button>
          }
        >
          Por inatividade ou atualização do servidor. O que não aparece como salvo não foi gravado.
        </Alert>
      );
    }
    if (estado && !escrita) {
      return (
        <Alert variant="warning" compact title="Somente leitura neste ambiente.">
          A gravação de documentos ainda não foi liberada. Você pode ler e exportar a revisão salva; o que digitar aqui não será gravado.
        </Alert>
      );
    }
    if (estado?.falha_controle) {
      return (
        <Alert variant="warning" compact>
          O editor recusou o bloqueio: {MOTIVO_DO_CONTROLE[estado.falha_controle] ?? "motivo não informado"}. Salve e tente de novo.
        </Alert>
      );
    }
    return null;
  })();

  const painelRevisao = (
    <>
      <DataList
        items={[
          { label: "Situação", value: status?.rotulo ?? "—" },
          { label: "Revisão salva", value: revisaoSalva ?? "—", numeric: true },
          { label: "SHA-256", value: <span className="gc-mono">{hashSalvo ? `${hashSalvo.slice(0, 16)}…` : "—"}</span> },
        ]}
      />
      {!escrita ? (
        <p className="text-sm text-[var(--text-secondary)]">A aprovação exige a gravação de documentos liberada neste ambiente.</p>
      ) : fase === "bloqueado" ? (
        <div className="grid gap-2">
          <p className="text-sm text-[var(--text-secondary)]">
            A revisão {revisaoSalva} está bloqueada no editor, exatamente como foi salva. Aprovar registra o ato sobre ela.
          </p>
          <Button icon="seal-check" loading={ocupado === "aprovacao"} disabled={Boolean(ocupado)} onClick={aprovar}>
            Aprovar revisão {revisaoSalva}
          </Button>
          <Button variant="secondary" icon="pencil-simple" loading={ocupado === "liberacao"} disabled={Boolean(ocupado)} onClick={liberar}>
            Voltar a editar
          </Button>
        </div>
      ) : fatosFalharam ? (
        <Button variant="secondary" icon="arrows-clockwise" onClick={() => void carregarFatos()}>
          Conferir os fatos de novo
        </Button>
      ) : fatos === null ? (
        <Spinner label="Conferindo os fatos do processo" />
      ) : !fatos.pronto ? (
        <div className="grid gap-2" data-testid="fatos-pendentes">
          {fatos.total === 0 && <Alert variant="warning" compact>O Formulário Matriz não produziu fatos. Revise os dados da demanda.</Alert>}
          {fatos.invalidos > 0 && <Alert variant="warning" compact>Há fatos em disputa. Resolva-os antes de aprovar.</Alert>}
          {fatos.pendentes.length > 0 && (
            <>
              <p className="text-sm text-[var(--text-secondary)]">
                Confira os {fatos.pendentes.length} fato(s) extraídos do formulário. A aprovação exige todos confirmados por uma pessoa.
              </p>
              <DataList
                stacked
                items={fatos.pendentes.map((f) => ({
                  label: f.inferido ? `${f.path} (inferido)` : f.path,
                  value: typeof f.valor === "string" ? f.valor : JSON.stringify(f.valor),
                }))}
              />
              <Button icon="check" loading={ocupado === "fatos"} disabled={Boolean(ocupado)} onClick={confirmar}>
                Confirmar {fatos.pendentes.length} fato(s)
              </Button>
            </>
          )}
        </div>
      ) : (
        <div className="grid gap-2">
          <p className="text-sm text-[var(--text-secondary)]">
            Fatos confirmados: {fatos.confirmados}. Para aprovar, bloqueie a revisão salva: o editor congela o documento e o servidor confere que é a mesma revisão.
          </p>
          <Button variant="secondary" icon="lock-simple" loading={ocupado === "bloqueio"} disabled={!limpo || Boolean(ocupado)} onClick={bloquear}>
            Bloquear revisão para análise
          </Button>
          {!limpo && <p className="text-xs text-[var(--text-tertiary)]">Aguarde o salvamento da última alteração.</p>}
        </div>
      )}
    </>
  );

  const painelHistorico =
    historico === null ? (
      <Spinner label="Carregando histórico" />
    ) : (
      <ol className="grid gap-2">
        {historico.map((r) => (
          <li key={r.revisao} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2">
              <span className="gc-num">Revisão {r.revisao}</span>
              {r.atual && (
                <Badge size="sm" variant="brand">
                  Atual
                </Badge>
              )}
            </span>
            {r.restauravel && escrita && (
              <Button
                size="sm"
                variant="ghost"
                icon="arrow-clockwise"
                loading={ocupado === `restaurar-${r.revisao}`}
                disabled={!limpo || Boolean(ocupado)}
                onClick={() => restaurar(r.revisao)}
              >
                Restaurar
              </Button>
            )}
          </li>
        ))}
      </ol>
    );

  const meta = (
    <>
      {status && (
        <Badge size="sm" variant={status.variante}>
          {status.rotulo}
        </Badge>
      )}
      {revisaoSalva && (
        <Badge size="sm" variant="neutral">
          Revisão {revisaoSalva}
        </Badge>
      )}
    </>
  );

  if (modo === "leitura") {
    return (
      <DocumentWorkspace back={voltar} kicker={documento.sigla} title={documento.rotulo} meta={meta} actions={exportar}>
        <div className="grid h-full place-items-center p-6">
          <EmptyState
            icon="file-text"
            title="Edição disponível em telas a partir de 768 px"
            description="No celular, leia o documento pela exportação da revisão salva. Para editar, abra em um computador ou tablet."
          />
        </div>
      </DocumentWorkspace>
    );
  }

  return (
    <>
      <DocumentWorkspace
        back={voltar}
        kicker={documento.sigla}
        title={<span data-testid="titulo-documento">{documento.rotulo}</span>}
        meta={meta}
        save={falhaDeAbertura || falhaDoHost ? undefined : salvamento(fase, estado)}
        notice={notice}
        focus={foco}
        panel={painel === "revisao" ? painelRevisao : painel === "historico" ? painelHistorico : null}
        panelTitle={painel === "revisao" ? "Revisão e aprovação" : "Histórico de revisões"}
        onClosePanel={() => setPainel(null)}
        actions={
          abertura ? (
            <>
              <Button size="sm" variant={painel === "historico" ? "subtle" : "ghost"} icon="clock" aria-pressed={painel === "historico"} onClick={() => alternarPainel("historico")}>
                Histórico
              </Button>
              <Button size="sm" variant={painel === "revisao" ? "subtle" : "ghost"} icon="seal-check" aria-pressed={painel === "revisao"} onClick={() => alternarPainel("revisao")}>
                Revisão
              </Button>
              {exportar}
              <IconButton
                size="sm"
                icon={foco ? "eye" : "eye-slash"}
                label={foco ? "Sair do modo foco (Esc)" : "Modo foco"}
                aria-pressed={foco}
                onClick={() => setFoco((f) => !f)}
              />
            </>
          ) : (
            exportar
          )
        }
      >
        {falhaDeAbertura ? (
          <div className="grid h-full place-items-center p-6">
            <EmptyState
              icon="warning-circle"
              title="Não foi possível abrir o documento"
              description={falhaDeAbertura}
              actions={
                <Button variant="secondary" href={voltarHref} icon="arrow-left">
                  Voltar ao processo
                </Button>
              }
            />
          </div>
        ) : falhaDoHost ? (
          <div className="grid h-full place-items-center p-6">
            <EmptyState
              icon="warning-circle"
              title="O editor não carregou"
              description={`${falhaDoHost} Nenhuma gravação foi feita. Recarregue a página; se persistir, avise o suporte.`}
              actions={
                <Button variant="secondary" icon="arrows-clockwise" onClick={() => window.location.reload()}>
                  Recarregar
                </Button>
              }
            />
          </div>
        ) : (
          <div ref={area} className="absolute inset-0" data-testid="area-do-editor" aria-label={`Editor: ${documento.rotulo}`} />
        )}
      </DocumentWorkspace>

      <Dialog
        open={sair}
        onClose={() => setSair(false)}
        tone="warning"
        icon="warning"
        title="Sair sem salvar?"
        description="Há alterações que o servidor ainda não confirmou. Se sair agora, elas se perdem."
        footer={
          <>
            <Button variant="secondary" onClick={() => setSair(false)}>
              Continuar editando
            </Button>
            <Button variant="danger" href={voltarHref}>
              Sair mesmo assim
            </Button>
          </>
        }
      />
    </>
  );
}
