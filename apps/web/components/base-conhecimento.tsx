"use client";

import { useState, useTransition } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  Field,
  FileUpload,
  IconButton,
  Input,
  Select,
  TableContainer,
  type DataTableColumn,
  type UploadFile,
} from "@/design-system";
import {
  atualizarLista,
  excluirReferencia,
  indexarArquivo,
  testarBusca,
} from "@/app/app/admin/base-conhecimento/acoes";
import type { BaseDeConhecimento, ReferenciaDaBase, TrechoRecuperado } from "@/lib/api";

type Situacao =
  | { fase: "fila" }
  | { fase: "indexando" }
  | { fase: "ok"; trechos: number; pendente: boolean }
  | { fase: "erro"; mensagem: string };

const LIMITE = 10 * 1024 * 1024;

function tamanho(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function selo(s: Situacao) {
  if (s.fase === "fila") return <Badge size="sm">na fila</Badge>;
  if (s.fase === "indexando") return <Badge size="sm" variant="info">indexando…</Badge>;
  if (s.fase === "erro") return <Badge size="sm" variant="error">não indexado</Badge>;
  return s.pendente ? (
    <Badge size="sm" variant="warning">{s.trechos} trechos · pendente de vetor</Badge>
  ) : (
    <Badge size="sm" variant="success">{s.trechos} trechos</Badge>
  );
}

// ---------------------------------------------------------------------------
// Envio e indexação
// ---------------------------------------------------------------------------
function Envio({ categorias, extensoes }: Pick<BaseDeConhecimento, "categorias" | "extensoes">) {
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [situacoes, setSituacoes] = useState<Situacao[]>([]);
  const [categoria, setCategoria] = useState(categorias[0]?.codigo ?? "");
  const [titulo, setTitulo] = useState("");
  const [enviando, iniciar] = useTransition();
  const [aviso, setAviso] = useState<string | null>(null);

  const aceitos = extensoes.map((e) => `.${e}`).join(",");
  const umSo = arquivos.length === 1;
  const terminou = situacoes.length > 0 && situacoes.every((s) => s.fase === "ok" || s.fase === "erro");

  const escolher = (lista: File[]) => {
    const validos = lista.filter((f) => extensoes.includes(f.name.split(".").pop()?.toLowerCase() ?? ""));
    setAviso(validos.length < lista.length ? "Alguns arquivos ficaram de fora: só PDF, DOCX, TXT e MD." : null);
    setArquivos(validos);
    setSituacoes(validos.map(() => ({ fase: "fila" })));
  };

  const indexar = () =>
    iniciar(async () => {
      const proximas = arquivos.map<Situacao>(() => ({ fase: "fila" }));
      for (const [i, arquivo] of arquivos.entries()) {
        if (arquivo.size > LIMITE) {
          proximas[i] = { fase: "erro", mensagem: "O arquivo passa do limite de 10 MB." };
          setSituacoes([...proximas]);
          continue;
        }
        proximas[i] = { fase: "indexando" };
        setSituacoes([...proximas]);
        const form = new FormData();
        form.set("arquivo", arquivo);
        form.set("categoria", categoria);
        // Um título só vale para um arquivo só, como no GovDocs.
        form.set("titulo", umSo ? titulo : "");
        const r = await indexarArquivo(form);
        proximas[i] = r.erro ? { fase: "erro", mensagem: r.erro } : { fase: "ok", trechos: r.trechos, pendente: r.pendente };
        setSituacoes([...proximas]);
      }
      await atualizarLista();
    });

  const lista: UploadFile[] = arquivos.map((f, i) => {
    const s = situacoes[i] ?? { fase: "fila" };
    return {
      name: f.name,
      meta: s.fase === "erro" ? s.mensagem : tamanho(f.size),
      icon: "file-text",
      status: selo(s),
    };
  });
  const pendentes = situacoes.filter((s) => s.fase === "ok" && s.pendente).length;

  return (
    <Card
      title="Adicionar referências"
      subtitle="Leis, acórdãos, entendimentos dos Tribunais de Contas, processos anteriores e modelos. A IA recupera os trechos mais relevantes destes arquivos para fundamentar cada documento."
      divided
    >
      <div className="grid gap-4" data-testid="envio-base">
        <FileUpload
          title="Arraste os arquivos aqui ou"
          hint="PDF, DOCX, TXT ou MD — até 10 MB por arquivo"
          accept={aceitos}
          files={lista}
          onFiles={escolher}
          onRemove={
            enviando
              ? undefined
              : (i) => {
                  setArquivos((a) => a.filter((_, j) => j !== i));
                  setSituacoes((s) => s.filter((_, j) => j !== i));
                }
          }
        />
        {aviso && <Alert variant="warning" compact>{aviso}</Alert>}
        <div className="grid gap-4 md:grid-cols-2">
          <Field
            label="Categoria"
            htmlFor="base-categoria"
            help="Normas e acórdãos são citáveis; processos e modelos são padrão de redação."
          >
            <Select
              id="base-categoria"
              value={categoria}
              onChange={(e) => setCategoria(e.target.value)}
              options={categorias.map((c) => ({ value: c.codigo, label: c.rotulo }))}
            />
          </Field>
          <Field
            label="Título"
            htmlFor="base-titulo"
            optional
            help={arquivos.length > 1 ? "Com vários arquivos, cada um usa o próprio nome." : "Se vazio, usa o nome do arquivo."}
          >
            <Input
              id="base-titulo"
              value={titulo}
              disabled={arquivos.length > 1}
              maxLength={300}
              placeholder="Ex.: Acórdão TCU 1234/2024-Plenário"
              onChange={(e) => setTitulo(e.target.value)}
            />
          </Field>
        </div>
        {terminou && pendentes > 0 && (
          <Alert variant="warning" compact>
            {pendentes} arquivo(s) entraram só para a busca textual: o servidor está sem a chave de embeddings. Eles ficam
            pendentes de vetor e não aparecem na busca semântica até serem reindexados.
          </Alert>
        )}
        <Button
          size="lg"
          icon="database"
          className="justify-self-start"
          loading={enviando}
          disabled={!arquivos.length || terminou}
          onClick={indexar}
        >
          Indexar na Base de Conhecimento
        </Button>
        {terminou && (
          <Button variant="ghost" className="justify-self-start" onClick={() => escolher([])}>
            Enviar outros arquivos
          </Button>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Referências indexadas
// ---------------------------------------------------------------------------
function Referencias({ referencias }: { referencias: ReferenciaDaBase[] }) {
  const [alvo, setAlvo] = useState<ReferenciaDaBase | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [excluindo, iniciar] = useTransition();

  const colunas: DataTableColumn<ReferenciaDaBase>[] = [
    {
      key: "titulo",
      label: "Referência",
      render: (r) => (
        <span className="grid">
          <span className="font-[number:var(--weight-medium)]">{r.titulo}</span>
          <span className="gc-mono text-[length:var(--gc-fs-sm)] text-secundario">{r.nome_arquivo}</span>
        </span>
      ),
    },
    { key: "categoria_rotulo", label: "Categoria" },
    { key: "total_chunks", label: "Trechos", align: "right", render: (r) => <span className="gc-num">{r.total_chunks}</span> },
    {
      key: "criado_em",
      label: "Enviado em",
      render: (r) => (r.criado_em ? new Date(r.criado_em).toLocaleDateString("pt-BR") : "—"),
    },
    {
      key: "acoes",
      label: <span className="gc-sr-only">Ações</span>,
      render: (r) => <IconButton icon="trash" label={`Excluir ${r.titulo}`} size="sm" variant="danger" onClick={() => setAlvo(r)} />,
    },
  ];

  const confirmar = () =>
    iniciar(async () => {
      if (!alvo) return;
      const r = await excluirReferencia(alvo.id);
      setErro(r.erro);
      setAlvo(null);
    });

  return (
    <Card title="Referências indexadas" subtitle={`${referencias.length} na base deste município.`} divided flush>
      {erro && (
        <div className="px-5 pt-4">
          <Alert variant="error" compact>{erro}</Alert>
        </div>
      )}
      {referencias.length === 0 ? (
        <EmptyState icon="books" title="Nenhuma referência indexada ainda" description="Envie o primeiro arquivo acima." />
      ) : (
        <TableContainer>
          <div data-testid="lista-referencias">
            <DataTable compact caption="Referências da Base de Conhecimento" minWidth="40rem" columns={colunas} rows={referencias} />
          </div>
        </TableContainer>
      )}
      <Dialog
        open={alvo !== null}
        onClose={() => setAlvo(null)}
        tone="danger"
        icon="trash"
        title="Excluir referência"
        description={alvo ? `"${alvo.titulo}" e os ${alvo.total_chunks} trechos dela saem da base. A IA deixa de citá-la nos próximos documentos.` : ""}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAlvo(null)}>
              Cancelar
            </Button>
            <Button variant="danger" loading={excluindo} onClick={confirmar}>
              Excluir
            </Button>
          </>
        }
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Teste de recuperação
// ---------------------------------------------------------------------------
function TesteDeBusca() {
  const [consulta, setConsulta] = useState("");
  const [trechos, setTrechos] = useState<TrechoRecuperado[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [buscando, iniciar] = useTransition();

  const buscar = () =>
    iniciar(async () => {
      const r = await testarBusca(consulta);
      setErro(r.erro);
      setTrechos(r.erro ? null : r.trechos);
    });

  return (
    <Card title="Testar a recuperação" subtitle="O que a IA veria para uma consulta." divided>
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          buscar();
        }}
      >
        <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
          <Field label="Consulta de teste" htmlFor="base-consulta">
            <Input
              id="base-consulta"
              value={consulta}
              maxLength={500}
              placeholder="Ex.: registro de preços para aquisição de equipamentos de TI"
              onChange={(e) => setConsulta(e.target.value)}
            />
          </Field>
          <Button type="submit" variant="secondary" icon="magnifying-glass" loading={buscando}>
            Buscar
          </Button>
        </div>
        {erro && <Alert variant="error" compact>{erro}</Alert>}
        {trechos && trechos.length === 0 && <p className="text-secundario">Nenhum trecho relevante encontrado.</p>}
        {trechos && trechos.length > 0 && (
          <ol className="grid gap-3" data-testid="trechos-recuperados">
            {trechos.map((t, i) => (
              <li key={i} className="grid gap-1">
                <span className="font-[number:var(--weight-medium)]">
                  {t.titulo}
                  {t.categoria_rotulo && <span className="text-secundario"> ({t.categoria_rotulo})</span>}
                  <span className="gc-num text-secundario"> — relevância {t.similaridade.toFixed(2).replace(".", ",")}</span>
                </span>
                <span className="text-[length:var(--gc-fs-sm)] text-secundario">{t.conteudo}…</span>
              </li>
            ))}
          </ol>
        )}
      </form>
    </Card>
  );
}

export function BaseDeConhecimentoTela({ base }: { base: BaseDeConhecimento }) {
  return (
    <div className="grid gap-6">
      <Envio categorias={base.categorias} extensoes={base.extensoes} />
      <Referencias referencias={base.referencias} />
      <TesteDeBusca />
    </div>
  );
}
