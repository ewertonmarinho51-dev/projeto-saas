"use client";

import { useMemo, useRef, useState, useTransition } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  EmptyState,
  Field,
  Input,
  Select,
  TableContainer,
  type DataTableColumn,
} from "@/design-system";
import {
  aplicarDemanda,
  consolidar,
  planilhaConsolidada,
} from "@/app/app/processos/[id]/demandas/acoes";
import type { Consolidacao } from "@/lib/api";

const VARIANTE: Record<string, "success" | "warning" | "error"> = { lido: "success", imagem: "warning", ilegivel: "error" };

/**
 * Consolidar Demandas: a sequência de conferências do Streamlit — o que
 * foi lido, de qual secretaria, os conflitos de unidade, a tabela e a
 * prova da soma — antes de aplicar à planilha do processo. Nada soma em
 * silêncio, nada é aplicado com conflito pendente.
 */
export function ConsolidarDemandas({ processo, versao }: { processo: string; versao: string }) {
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [rotulos, setRotulos] = useState<Record<string, string>>({});
  // As secretarias com que a tabela NA TELA foi consolidada. Aplicar e
  // baixar usam estas, nunca as que a pessoa digitou depois: o servidor
  // aplicaria uma consolidação que ninguém conferiu.
  const [conferidos, setConferidos] = useState<Record<string, string>>({});
  const [aceitos, setAceitos] = useState<string[]>([]);
  const [resultado, setResultado] = useState<Consolidacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [descarte, setDescarte] = useState<string | null>(null);
  const [confirmado, setConfirmado] = useState(false);
  const [origem, setOrigem] = useState("");
  const [ocupado, executar] = useTransition();
  const entrada = useRef<HTMLInputElement>(null);

  const montar = (lista: File[] = arquivos, nomes: Record<string, string> = rotulos) => {
    const dados = new FormData();
    lista.forEach((a) => dados.append("arquivos", a));
    dados.set("rotulos", JSON.stringify(nomes));
    dados.set("aceitos", JSON.stringify(aceitos));
    return dados;
  };

  const conferir = (lista: File[] = arquivos, nomes: Record<string, string> = rotulos) =>
    executar(async () => {
      setDescarte(null);
      const r = await consolidar(processo, montar(lista, nomes));
      setErro(r.erro);
      setResultado(r.resultado);
      setConferidos(nomes);
    });

  const pendentes = useMemo(
    () => (resultado?.conflitos ?? []).filter((c) => !aceitos.includes(c.codigo)).map((c) => c.codigo),
    [resultado, aceitos],
  );
  // Secretaria corrigida e ainda não conferida: a tabela da tela não é mais
  // o que sairia. Aplicar e baixar ficam travados até conferir de novo.
  const desatualizado = JSON.stringify(rotulos) !== JSON.stringify(conferidos);
  const podeAplicar = Boolean(resultado?.fecha && resultado.linhas.length && pendentes.length === 0 && !desatualizado);
  const linhaDeOrigem = resultado?.linhas.find((l) => `${l.codigo}|${l.unidade}` === origem);

  type Linha = Consolidacao["linhas"][number] & { id: string };
  const colunas: DataTableColumn<Linha>[] = [
    { key: "codigo", label: "Código", render: (l) => <span className="gc-mono">{l.codigo}</span> },
    { key: "descricao", label: "Descrição" },
    { key: "unidade", label: "Unidade" },
    ...(resultado?.secretarias ?? []).map((s) => ({
      key: `sec:${s}`,
      label: s,
      align: "right" as const,
      render: (l: Linha) => <span className="gc-num">{l.por_secretaria[s] ?? "—"}</span>,
    })),
    {
      key: "total",
      label: "Total",
      align: "right",
      render: (l) => <strong className="gc-num">{l.total}</strong>,
    },
  ];

  const baixar = () =>
    executar(async () => {
      const r = await planilhaConsolidada(processo, montar(arquivos, conferidos));
      if (r.erro || !r.base64) {
        setErro(r.erro ?? "Não foi possível gerar a planilha.");
        return;
      }
      const bytes = Uint8Array.from(atob(r.base64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(
        new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "demanda-consolidada.xlsx";
      link.click();
      URL.revokeObjectURL(url);
    });

  const aplicar = () =>
    executar(async () => {
      const r = await aplicarDemanda(processo, versao, confirmado, montar(arquivos, conferidos));
      // Sucesso redireciona; aqui só voltam erro e descarte pendente.
      setErro(r.erro);
      setDescarte(r.descarte);
    });

  return (
    <div className="grid gap-6" data-testid="consolidar-demandas">
      <Card
        title="Documentos de Formalização de Demanda"
        subtitle="PDFs das secretarias. Pode mandar vários de uma vez; um arquivo pode conter mais de um documento."
        divided
      >
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={entrada}
            type="file"
            accept=".pdf,application/pdf"
            multiple
            hidden
            aria-label="Documentos de Formalização de Demanda (PDF)"
            onChange={(e) => {
              const lista = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (!lista.length) return;
              setArquivos(lista);
              setRotulos({});
              setAceitos([]);
              setOrigem("");
              conferir(lista, {});
            }}
          />
          <Button icon="upload-simple" loading={ocupado} onClick={() => entrada.current?.click()}>
            {arquivos.length ? "Trocar arquivos" : "Escolher PDFs"}
          </Button>
          {arquivos.length > 0 && (
            <span className="text-[length:var(--gc-fs-sm)] text-secundario">{arquivos.length} arquivo(s) escolhido(s)</span>
          )}
        </div>
      </Card>

      {!resultado && !erro && (
        <EmptyState
          icon="tray"
          title="Nenhum documento ainda"
          description="Envie os PDFs que as secretarias mandaram. O sistema lê o órgão de dentro de cada documento — não é preciso renomear arquivo."
        />
      )}

      {erro && <Alert variant="error" title="Não foi possível concluir">{erro}</Alert>}

      {resultado && (
        <>
          <section aria-labelledby="titulo-arquivos" className="grid gap-3">
            <h2 id="titulo-arquivos">Arquivos recebidos</h2>
            {resultado.erros.map((e) => (
              <Alert key={e.nome} variant="error" compact>
                <strong>{e.nome}</strong> — {e.mensagem}
              </Alert>
            ))}
            {resultado.arquivos.map((a) => (
              <Card key={a.nome} title={a.nome} actions={<Badge variant={VARIANTE[a.status] ?? "neutral"}>{a.status_texto}</Badge>}>
                {a.status === "imagem" ? (
                  <p className="text-secundario">
                    Este PDF é uma digitalização: não tem texto para ler. Peça à secretaria o arquivo em PDF de texto, ou lance
                    os itens à mão na planilha do processo. <strong>Ele não entra na soma</strong> — e não conta como
                    secretaria que não pediu nada.
                  </p>
                ) : a.status !== "lido" ? (
                  <p className="text-secundario">
                    O arquivo abriu, mas não tem quadro de itens no formato esperado. Confira se é mesmo um Documento de
                    Formalização de Demanda.
                  </p>
                ) : (
                  <div className="grid gap-3">
                    <p className="text-secundario">
                      {a.documentos.length} documento(s) — nº {a.documentos.join(", ")} — com <strong>{a.itens}</strong> itens.
                      {a.documentos.length > 1 && " As quantidades dos documentos deste arquivo são somadas."}
                    </p>
                    {a.precisa_confirmar && (
                      <Alert variant="warning" compact>
                        Não foi possível identificar o órgão dentro deste documento. Informe de qual secretaria ele é.
                      </Alert>
                    )}
                    <Field
                      label="Secretaria"
                      htmlFor={`rotulo-${a.nome}`}
                      help="Sai do órgão declarado no documento. Corrija se estiver errado e confira de novo."
                    >
                      <Input
                        id={`rotulo-${a.nome}`}
                        placeholder="Ex.: SEMEC"
                        value={rotulos[a.nome] ?? a.secretaria}
                        onChange={(e) => setRotulos((r) => ({ ...r, [a.nome]: e.target.value }))}
                      />
                    </Field>
                  </div>
                )}
              </Card>
            ))}
            {desatualizado && (
              <Alert
                variant="warning"
                title="Secretaria corrigida: confira de novo"
                actions={
                  <Button variant="secondary" size="sm" icon="arrows-clockwise" loading={ocupado} onClick={() => conferir()}>
                    Conferir de novo
                  </Button>
                }
              >
                A tabela abaixo ainda é a da conferência anterior. Corrigir a secretaria pode mudar as somas — por exemplo, dois
                documentos com o mesmo número passam a contar como um. Aplicar e baixar ficam travados até conferir.
              </Alert>
            )}
          </section>

          {resultado.conflitos.length > 0 && (
            <section aria-labelledby="titulo-conflitos" className="grid gap-3">
              <h2 id="titulo-conflitos">Conflitos que precisam da sua decisão</h2>
              <Alert variant="warning">
                O mesmo código chegou com unidades diferentes. O sistema <strong>não soma</strong> nesses casos: converter
                caixa em unidade exigiria um fator que o documento não traz.
              </Alert>
              {resultado.conflitos.map((c) => (
                <Card key={c.codigo} sunken>
                  <Checkbox
                    label={`Item ${c.codigo}: manter as unidades separadas (${c.unidades.join(", ")}), cada uma na sua linha`}
                    description={`Chegou de ${c.secretarias.join(", ")}. A decisão fica registrada no processo.`}
                    checked={aceitos.includes(c.codigo)}
                    onChange={(e) =>
                      setAceitos((a) => (e.target.checked ? [...a, c.codigo] : a.filter((x) => x !== c.codigo)))
                    }
                  />
                </Card>
              ))}
            </section>
          )}

          {resultado.linhas.length > 0 && (
            <section aria-labelledby="titulo-tabela" className="grid gap-3">
              <h2 id="titulo-tabela">Tabela consolidada</h2>
              <TableContainer>
                <div data-testid="tabela-consolidada">
                  <DataTable
                    compact
                    caption="Itens consolidados por secretaria"
                    minWidth="48rem"
                    columns={colunas}
                    rows={resultado.linhas.map((l) => ({ ...l, id: `${l.codigo}|${l.unidade}` }))}
                  />
                </div>
              </TableContainer>
              <Field label="Ver a origem de um item" htmlFor="origem-item">
                <Select
                  id="origem-item"
                  placeholder="Escolha um item"
                  value={origem}
                  onChange={(e) => setOrigem(e.target.value)}
                  options={resultado.linhas.map((l) => ({
                    value: `${l.codigo}|${l.unidade}`,
                    label: `${l.codigo} — ${l.descricao.slice(0, 56)} (${l.unidade})`,
                  }))}
                />
              </Field>
              {linhaDeOrigem && (
                <pre className="gc-mono overflow-x-auto whitespace-pre-wrap rounded-[var(--gc-radius-md)] bg-[var(--surface-sunken)] p-4 text-[length:var(--gc-fs-sm)]">
                  {linhaDeOrigem.explicacao}
                </pre>
              )}
            </section>
          )}

          {resultado.linhas.length > 0 &&
            (resultado.fecha ? (
              <Alert variant="success" title="A conta fecha">
                {resultado.linhas.length} itens, {resultado.ocorrencias} parcelas somadas de {resultado.secretarias.length}{" "}
                secretaria(s). Cada total foi reconferido a partir das parcelas.
              </Alert>
            ) : (
              <Alert variant="error" title="A conta não fecha">
                Nada pode ser aplicado ao processo. {resultado.divergencia}
              </Alert>
            ))}
          {resultado.duplicatas.length > 0 && (
            <p className="text-[length:var(--gc-fs-sm)] text-secundario">
              Arquivos ignorados por serem reenvio do mesmo documento: {resultado.duplicatas.join(", ")}
            </p>
          )}

          {descarte && (
            <Alert variant="warning" title="Confirme o descarte">
              <div className="grid gap-3">
                <p>{descarte}</p>
                <Checkbox
                  checked={confirmado}
                  onChange={(e) => setConfirmado(e.target.checked)}
                  label="Entendi que esses documentos serão descartados e precisarão ser gerados novamente."
                />
              </div>
            </Alert>
          )}

          {resultado.linhas.length > 0 && (
            <div className="flex flex-wrap justify-end gap-3">
              <Button variant="secondary" size="lg" icon="microsoft-excel-logo" loading={ocupado} disabled={desatualizado} onClick={baixar}>
                Baixar tabela consolidada (XLSX)
              </Button>
              <Button size="lg" loading={ocupado} disabled={!podeAplicar || (Boolean(descarte) && !confirmado)} onClick={aplicar}>
                Aplicar ao processo
              </Button>
            </div>
          )}
          {resultado.linhas.length > 0 && pendentes.length > 0 && (
            <p className="text-right text-[length:var(--gc-fs-sm)] text-secundario">
              Decida os conflitos de unidade ({pendentes.join(", ")}) antes de aplicar.
            </p>
          )}
        </>
      )}
    </div>
  );
}
