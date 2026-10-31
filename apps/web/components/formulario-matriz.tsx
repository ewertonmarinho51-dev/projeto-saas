"use client";

import { useActionState, useMemo, useRef, useState, useTransition, type ReactNode } from "react";

import {
  Alert,
  Button,
  buttonClasses,
  Card,
  Checkbox,
  DataTable,
  Field,
  Icon,
  IconButton,
  Input,
  ProgressBar,
  Select,
  Textarea,
  type DataTableColumn,
} from "@/design-system";
import {
  gravarFormulario,
  lerMemorando,
  lerPlanilha,
  type EstadoDaGravacao,
} from "@/app/app/processos/[id]/formulario/acoes";
import type { CampoDoFormulario, Formulario, ItemDaPlanilha } from "@/lib/api";

/** Colunas fixas da planilha, na ordem do wizard (`planilha.CAMPOS_ITEM` + fonte). */
const COLUNAS: { chave: string; rotulo: string; numero?: boolean; largo?: boolean }[] = [
  { chave: "codigo", rotulo: "Código" },
  { chave: "descricao", rotulo: "Descrição", largo: true },
  { chave: "unidade", rotulo: "Unidade" },
  { chave: "quantidade", rotulo: "Quantidade", numero: true },
  { chave: "valor_unitario", rotulo: "Valor unitário (R$)", numero: true },
  { chave: "fonte", rotulo: "Fonte / link" },
];
const DERIVADAS = new Set(["valor_total"]);
const FIXAS = new Set(COLUNAS.map((c) => c.chave));

type Linha = Record<string, string>;

/**
 * Número vindo da API (float) para o campo de texto, no formato brasileiro.
 * É só exibição: a conta (total por item e valor global) é do servidor,
 * que recalcula a planilha a cada gravação.
 */
function paraCampo(valor: string | number | undefined): string {
  if (valor === undefined || valor === null) return "";
  if (typeof valor === "number") return valor.toLocaleString("pt-BR", { useGrouping: false, maximumFractionDigits: 6 });
  return String(valor);
}

function paraLinhas(itens: ItemDaPlanilha[]): Linha[] {
  return itens.map((item) =>
    Object.fromEntries(Object.entries(item).filter(([k]) => !DERIVADAS.has(k)).map(([k, v]) => [k, paraCampo(v)])),
  );
}

function linhaVazia(extras: string[]): Linha {
  return Object.fromEntries([...COLUNAS.map((c) => c.chave), ...extras].map((k) => [k, ""]));
}

function preenchida(linha: Linha): boolean {
  return Boolean((linha.descricao ?? "").trim());
}

const SECOES: { titulo: string; subtitulo?: string; campos: string[]; duasColunas?: boolean }[] = [
  { titulo: "Informações gerais", subtitulo: "Identificação da contratação", campos: ["orgao", "responsavel", "prazo", "modelo_execucao"], duasColunas: true },
  { titulo: "Objeto e justificativa", campos: ["objeto", "justificativa"] },
  { titulo: "Contexto da contratação", subtitulo: "Origem, alinhamento, requisitos e riscos da demanda", campos: ["memorando", "alinhamento", "requisitos", "riscos"] },
];

export function FormularioMatriz({ processo, formulario, aviso }: { processo: string; formulario: Formulario; aviso: string | null }) {
  const campos = useMemo(() => Object.fromEntries(formulario.campos.map((c) => [c.chave, c])), [formulario.campos]);
  const [valores, setValores] = useState<Record<string, string>>(formulario.valores);
  const [linhas, setLinhas] = useState<Linha[]>(() => {
    const iniciais = paraLinhas(formulario.itens);
    return iniciais.length ? iniciais : [linhaVazia([]), linhaVazia([]), linhaVazia([])];
  });
  const extras = useMemo(
    () => [...new Set(linhas.flatMap((l) => Object.keys(l)).filter((k) => !FIXAS.has(k) && !DERIVADAS.has(k)))],
    [linhas],
  );
  const [estado, executar, enviando] = useActionState<EstadoDaGravacao, FormData>(gravarFormulario, { erro: null, descarte: null });
  const [confirmado, setConfirmado] = useState(false);
  const [lendo, iniciarLeitura] = useTransition();
  const [leitura, setLeitura] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const entradaPlanilha = useRef<HTMLInputElement>(null);
  const entradaMemorando = useRef<HTMLInputElement>(null);

  const obrigatorios = formulario.campos.filter((c) => c.obrigatorio);
  const faltam = obrigatorios.filter((c) => (c.chave === "itens" ? !linhas.some(preenchida) : !(valores[c.chave] ?? "").trim()));
  const feitos = obrigatorios.length - faltam.length;

  const payload = JSON.stringify({
    ...Object.fromEntries(formulario.campos.filter((c) => c.tipo !== "planilha").map((c) => [c.chave, valores[c.chave] ?? ""])),
    // Linha em branco não vai: o servidor também a ignoraria no cálculo.
    itens: linhas.filter((l) => Object.values(l).some((v) => v.trim())),
  });

  const mudar = (chave: string, valor: string) => setValores((v) => ({ ...v, [chave]: valor }));
  const mudarCelula = (i: number, chave: string, valor: string) =>
    setLinhas((ls) => ls.map((l, j) => (j === i ? { ...l, [chave]: valor } : l)));

  const importarPlanilha = (arquivo: File) =>
    iniciarLeitura(async () => {
      const dados = new FormData();
      dados.set("planilha", arquivo);
      const r = await lerPlanilha(processo, dados);
      if (r.erro || !r.itens) {
        setLeitura({ tipo: "erro", texto: r.erro ?? "Não foi possível ler a planilha." });
        return;
      }
      setLinhas(paraLinhas(r.itens));
      setLeitura({
        tipo: "ok",
        texto: `${r.itens.length} item(ns) importado(s) da planilha (total ${r.total}). Confira e salve para gravar.`,
      });
    });

  const importarMemorando = (arquivo: File) =>
    iniciarLeitura(async () => {
      const dados = new FormData();
      dados.set("memorando", arquivo);
      const r = await lerMemorando(processo, dados);
      if (r.erro || r.texto === null) {
        setLeitura({ tipo: "erro", texto: r.erro ?? "Não foi possível ler o arquivo." });
        return;
      }
      mudar("memorando", r.texto);
      setLeitura({ tipo: "ok", texto: `Memorando importado (${r.texto.length} caracteres). Revise o texto no campo.` });
    });

  const renderCampo = (campo: CampoDoFormulario): ReactNode => {
    const id = `campo-${campo.chave}`;
    const ajuda = campo.exemplo ? `${campo.ajuda} Ex.: ${campo.exemplo}` : campo.ajuda;
    let controle: ReactNode;
    if (campo.tipo === "selecao") {
      controle = (
        <Select
          id={id}
          options={campo.opcoes}
          placeholder="Selecione uma opção"
          value={valores[campo.chave] ?? ""}
          onChange={(e) => mudar(campo.chave, e.target.value)}
        />
      );
    } else if (campo.tipo === "area") {
      controle = (
        <Textarea
          id={id}
          rows={campo.chave === "memorando" ? 7 : 4}
          placeholder={campo.placeholder}
          value={valores[campo.chave] ?? ""}
          onChange={(e) => mudar(campo.chave, e.target.value)}
        />
      );
    } else {
      controle = (
        <Input id={id} placeholder={campo.placeholder} value={valores[campo.chave] ?? ""} onChange={(e) => mudar(campo.chave, e.target.value)} />
      );
    }
    return (
      <Field key={campo.chave} label={campo.rotulo} htmlFor={id} required={campo.obrigatorio} optional={!campo.obrigatorio} help={ajuda}>
        {controle}
      </Field>
    );
  };

  const campoItens = campos.itens;

  // A planilha editável pelo DataTable do design system: cada célula é um
  // Input; a linha carrega o índice como chave.
  type LinhaDaTabela = Linha & { id: string };
  const colunasDaPlanilha: DataTableColumn<LinhaDaTabela>[] = [
    ...[...COLUNAS, ...extras.map((e) => ({ chave: e, rotulo: e, numero: false, largo: false }))].map((c) => ({
      key: c.chave,
      label: c.rotulo,
      width: c.largo ? "20rem" : undefined,
      render: (linha: LinhaDaTabela) => (
        <Input
          size="sm"
          aria-label={`${c.rotulo}, item ${Number(linha.id) + 1}`}
          inputMode={"numero" in c && c.numero ? "decimal" : undefined}
          value={linha[c.chave] ?? ""}
          onChange={(e) => mudarCelula(Number(linha.id), c.chave, e.target.value)}
        />
      ),
    })),
    {
      key: "remover",
      label: <span className="gc-sr-only">Remover</span>,
      render: (linha: LinhaDaTabela) => (
        <IconButton
          icon="trash"
          label={`Remover item ${Number(linha.id) + 1}`}
          size="sm"
          variant="danger"
          onClick={() => setLinhas((ls) => ls.filter((_, j) => j !== Number(linha.id)))}
        />
      ),
    },
  ];

  return (
    <form action={executar} className="grid gap-6" data-testid="formulario-matriz">
      <input type="hidden" name="id" value={processo} />
      <input type="hidden" name="versao" value={formulario.versao} />
      <input type="hidden" name="payload" value={payload} />

      {aviso && <Alert variant="success">{aviso}</Alert>}

      <ProgressBar
        label="Campos obrigatórios"
        value={feitos}
        max={obrigatorios.length || 1}
        showValue={false}
        hint={
          faltam.length
            ? `${feitos} de ${obrigatorios.length} preenchidos. Ainda falta: ${faltam.map((c) => c.rotulo).join(", ")}.`
            : `${feitos} de ${obrigatorios.length} preenchidos. Pode iniciar a elaboração.`
        }
        tone={faltam.length ? "accent" : "success"}
      />

      {formulario.a_descartar.length > 0 && (
        <Alert variant="warning" title="Este processo já tem documentos">
          Alterar os dados desatualiza a cadeia documental: {formulario.a_descartar.join(", ")} serão descartados para nova
          geração. Salvar sem mudar nada não descarta.
        </Alert>
      )}

      {leitura && (
        <Alert variant={leitura.tipo === "ok" ? "info" : "error"} onClose={() => setLeitura(null)}>
          {leitura.texto}
        </Alert>
      )}

      {SECOES.map((secao) => (
        <Card key={secao.titulo} title={secao.titulo} subtitle={secao.subtitulo} divided>
          <div className={secao.duasColunas ? "grid gap-5 md:grid-cols-2" : "grid gap-5"}>
            {secao.campos.map((chave) => campos[chave] && renderCampo(campos[chave]))}
            {secao.campos.includes("memorando") && (
              <div className="flex flex-wrap items-center gap-3">
                <input
                  ref={entradaMemorando}
                  type="file"
                  hidden
                  accept=".pdf,.docx,.txt,.md"
                  aria-label="Arquivo do memorando ou ofício"
                  onChange={(e) => {
                    const arquivo = e.target.files?.[0];
                    if (arquivo) importarMemorando(arquivo);
                    e.target.value = "";
                  }}
                />
                <Button variant="secondary" size="sm" icon="paperclip" loading={lendo} onClick={() => entradaMemorando.current?.click()}>
                  Anexar memorando ou ofício
                </Button>
                <span className="text-[length:var(--gc-fs-xs)] text-secundario">PDF, DOCX, TXT ou MD: o texto extraído vai para o campo acima.</span>
              </div>
            )}
          </div>
        </Card>
      ))}

      {campoItens && (
        <Card
          title={`${campoItens.rotulo}${campoItens.obrigatorio ? " *" : ""}`}
          subtitle={campoItens.ajuda}
          divided
          flush
          actions={
            <>
              {/* Download, não navegação: a barra de progresso não deve prometer outra página. */}
              <a href="/app/processos/modelo-planilha" download className={buttonClasses({ variant: "ghost", size: "sm" })}>
                <Icon name="download-simple" />
                Modelo (.xlsx)
              </a>
              <input
                ref={entradaPlanilha}
                type="file"
                hidden
                accept=".xlsx"
                aria-label="Planilha de itens (XLSX)"
                onChange={(e) => {
                  const arquivo = e.target.files?.[0];
                  if (arquivo) importarPlanilha(arquivo);
                  e.target.value = "";
                }}
              />
              <Button variant="secondary" size="sm" icon="upload-simple" loading={lendo} onClick={() => entradaPlanilha.current?.click()}>
                Importar planilha
              </Button>
            </>
          }
          footer={
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Button variant="ghost" size="sm" icon="plus" onClick={() => setLinhas((ls) => [...ls, linhaVazia(extras)])}>
                Adicionar item
              </Button>
              <span className="text-[length:var(--gc-fs-sm)] text-secundario" data-testid="valor-estimado">
                Valor global (estimativa): <strong className="gc-num text-texto">{formulario.valor_estimado_exibicao}</strong> —
                recalculado ao salvar.
              </span>
            </div>
          }
        >
          <div data-testid="planilha-itens">
            <DataTable
              compact
              caption="Planilha orçamentária: um item por linha"
              minWidth="56rem"
              columns={colunasDaPlanilha}
              rows={linhas.map((linha, i) => ({ ...linha, id: String(i) }))}
            />
          </div>
        </Card>
      )}

      {estado.descarte && (
        <Alert variant="warning" title="Confirme o descarte">
          <div className="grid gap-3">
            <p>{estado.descarte}</p>
            <Checkbox
              name="confirmar"
              value="1"
              checked={confirmado}
              onChange={(e) => setConfirmado(e.target.checked)}
              label="Entendi que esses documentos serão descartados e precisarão ser gerados novamente."
            />
          </div>
        </Alert>
      )}

      {estado.erro && (
        <Alert variant="error" title="Não foi possível salvar">
          {estado.erro}
        </Alert>
      )}

      <div className="flex flex-wrap justify-end gap-3">
        <Button type="submit" name="iniciar" value="0" variant="secondary" size="lg" disabled={enviando || (Boolean(estado.descarte) && !confirmado)}>
          Salvar rascunho
        </Button>
        <Button type="submit" name="iniciar" value="1" size="lg" loading={enviando} disabled={Boolean(estado.descarte) && !confirmado}>
          Iniciar elaboração dos documentos
        </Button>
      </div>
    </form>
  );
}
