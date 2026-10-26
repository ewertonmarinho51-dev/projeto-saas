"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import { Alert, Button, Card, Dialog, Field, Input, Textarea } from "@/design-system";
import {
  arquivarPesquisa,
  buscarItem,
  concluirPesquisa,
  criarRevisao,
  desfazerRetirada,
  duplicarPesquisa,
  editarItem,
  incluirItem,
  manterPreco,
  retirarItem,
  type EstadoDaGestao,
} from "@/app/app/precos/gestao";
import { useJob } from "@/components/acompanhar-job";
import type { AlertaDePreco, ItemDePesquisa } from "@/lib/api";

const INICIAL: EstadoDaGestao = { erro: null, ok: null };

function Retorno({ estado }: { estado: EstadoDaGestao }) {
  if (estado.erro) return <Alert variant="error" compact>{estado.erro}</Alert>;
  if (estado.ok) return <Alert variant="success" compact>{estado.ok}</Alert>;
  return null;
}

/** Ato de um clique que redireciona no sucesso; no erro, a mensagem fica ao lado. */
function useAto() {
  const [estado, setEstado] = useState<EstadoDaGestao>(INICIAL);
  const [ocupado, executar] = useTransition();
  return { estado, ocupado, rodar: (f: () => Promise<EstadoDaGestao>) => executar(async () => setEstado(await f())) };
}

// ---------------------------------------------------------------------------
// Cotação: duplicar e arquivar
// ---------------------------------------------------------------------------
export function GestaoDaPesquisa({ pesquisa, editavel }: { pesquisa: string; editavel: boolean }) {
  const [confirmar, setConfirmar] = useState(false);
  const ato = useAto();
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" icon="copy" loading={ato.ocupado} onClick={() => ato.rodar(() => duplicarPesquisa(pesquisa))}>
          Duplicar
        </Button>
        {editavel && (
          <Button variant="ghost" icon="archive" onClick={() => setConfirmar(true)}>
            Arquivar
          </Button>
        )}
      </div>
      <Retorno estado={ato.estado} />
      <Dialog
        open={confirmar}
        onClose={() => setConfirmar(false)}
        tone="warning"
        icon="archive"
        title="Arquivar a pesquisa"
        description="Arquivada, a pesquisa sai da lista de trabalho e não recebe mais alteração. Nada é apagado: itens, preços e a trilha continuam guardados."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmar(false)}>
              Cancelar
            </Button>
            <Button
              loading={ato.ocupado}
              onClick={() => {
                setConfirmar(false);
                ato.rodar(() => arquivarPesquisa(pesquisa));
              }}
            >
              Arquivar
            </Button>
          </>
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Item: incluir à mão
// ---------------------------------------------------------------------------
function CamposDoItem({ prefixo, item }: { prefixo: string; item?: ItemDePesquisa }) {
  return (
    <>
      <Field label="Descrição" htmlFor={`${prefixo}-descricao`} required className="md:col-span-4">
        <Textarea
          id={`${prefixo}-descricao`}
          name="descricao"
          rows={2}
          maxLength={2000}
          defaultValue={item?.descricao}
          placeholder="Ex.: Caneta esferográfica azul, ponta média 1,0 mm"
        />
      </Field>
      <Field label="Unidade" htmlFor={`${prefixo}-unidade`} required help="Ex.: UN, CX, RESMA, KG">
        <Input id={`${prefixo}-unidade`} name="unidade" maxLength={40} defaultValue={item?.unidade} />
      </Field>
      <Field label="Quantidade" htmlFor={`${prefixo}-quantidade`} required>
        <Input
          id={`${prefixo}-quantidade`}
          name="quantidade"
          inputMode="decimal"
          maxLength={30}
          defaultValue={item?.quantidade?.exibicao}
        />
      </Field>
      <Field label="Código" htmlFor={`${prefixo}-codigo`} optional help="CATMAT ou CATSER">
        <Input id={`${prefixo}-codigo`} name="codigo" maxLength={40} defaultValue={item?.codigo ?? ""} />
      </Field>
    </>
  );
}

export function NovoItem({ pesquisa }: { pesquisa: string }) {
  const [estado, acao, enviando] = useActionState(incluirItem.bind(null, pesquisa), INICIAL);
  return (
    <form action={acao} className="grid gap-4 md:grid-cols-4" data-testid="novo-item">
      <CamposDoItem prefixo="novo" />
      <div className="grid gap-3 md:col-span-4">
        <Retorno estado={estado} />
        <Button type="submit" variant="secondary" icon="plus" loading={enviando} className="justify-self-start">
          Incluir item
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Item: editar e retirar
// ---------------------------------------------------------------------------
export function EdicaoDoItem({ pesquisa, item }: { pesquisa: string; item: ItemDePesquisa }) {
  const [estado, acao, enviando] = useActionState(editarItem.bind(null, pesquisa, item.id, item.revisao), INICIAL);
  const [retirar, setRetirar] = useState(false);
  const [motivo, setMotivo] = useState("");
  const ato = useAto();
  return (
    <Card
      title="Dados do item"
      subtitle="Mudar a descrição ou a unidade devolve o item à coleta: a cesta valia para o item antigo. Mudar só a quantidade refaz o total."
      divided
    >
      <form action={acao} className="grid gap-4 md:grid-cols-4" data-testid="edicao-item">
        <CamposDoItem prefixo="item" item={item} />
        <div className="grid gap-3 md:col-span-4">
          <Retorno estado={estado} />
          <Retorno estado={ato.estado} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" loading={enviando}>
              Salvar item
            </Button>
            <Button type="button" variant="danger-subtle" icon="trash" onClick={() => setRetirar(true)}>
              Retirar item
            </Button>
          </div>
        </div>
      </form>
      <Dialog
        open={retirar}
        onClose={() => setRetirar(false)}
        tone="danger"
        icon="trash"
        title="Retirar o item da pesquisa"
        description="O item sai da cotação e do cálculo, mas não é apagado: ele e os preços dele continuam na trilha."
        footer={
          <>
            <Button variant="ghost" onClick={() => setRetirar(false)}>
              Cancelar
            </Button>
            <Button
              variant="danger"
              loading={ato.ocupado}
              onClick={() => {
                setRetirar(false);
                ato.rodar(() => retirarItem(pesquisa, item.id, motivo));
              }}
            >
              Retirar
            </Button>
          </>
        }
      >
        <Field label="Motivo" htmlFor="retirar-motivo" optional help="A auditoria já registra quem e quando.">
          <Textarea id="retirar-motivo" rows={2} maxLength={1000} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </Field>
      </Dialog>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Cesta: desfazer a própria retirada e manter o preço atípico
// ---------------------------------------------------------------------------
export function DesfazerRetirada(props: { pesquisa: string; item: string; referencia: string; revisao: number }) {
  const ato = useAto();
  return (
    <div className="grid gap-2">
      <Alert
        variant="success"
        compact
        actions={
          <Button
            variant="ghost"
            size="sm"
            loading={ato.ocupado}
            onClick={() => ato.rodar(() => desfazerRetirada(props.pesquisa, props.item, props.referencia, props.revisao))}
          >
            Desfazer
          </Button>
        }
      >
        Preço retirado da cesta. Estimativa recalculada.
      </Alert>
      <Retorno estado={ato.estado} />
    </div>
  );
}

export function AlertaDoPreco({
  pesquisa,
  item,
  revisao,
  alerta,
  editavel,
}: {
  pesquisa: string;
  item: string;
  revisao: number;
  alerta: AlertaDePreco;
  editavel: boolean;
}) {
  const ato = useAto();
  if (alerta.mantida) {
    return (
      <Alert variant="info" compact>
        Mantido no cálculo por sua decisão. O alerta acompanha o preço até a emissão.
      </Alert>
    );
  }
  return (
    <div className="grid gap-2" data-testid="alerta-preco">
      <Alert
        variant="warning"
        compact
        title="Confira este preço"
        actions={
          editavel ? (
            <Button
              variant="secondary"
              size="sm"
              loading={ato.ocupado}
              onClick={() => ato.rodar(() => manterPreco(pesquisa, item, alerta.referencia_id, revisao))}
            >
              Manter preço
            </Button>
          ) : undefined
        }
      >
        {alerta.faixa_min && alerta.faixa_max
          ? `Os demais preços usados estão entre ${alerta.faixa_min.exibicao} e ${alerta.faixa_max.exibicao}. Pode haver diferença de especificação, embalagem ou condição de fornecimento.`
          : "Este preço destoa da régua da emissão. Confira a especificação e a origem."}{" "}
        Para tirá-lo do cálculo, use “Tirar da cesta”.
      </Alert>
      <Retorno estado={ato.estado} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// M10b: concluir a cotação e criar revisão
// ---------------------------------------------------------------------------
export function FechamentoDaPesquisa({
  pesquisa,
  estado,
  itens,
  faltam,
}: {
  pesquisa: string;
  estado: string;
  itens: number;
  /** Itens ainda não concluídos: com algum, o botão diz por que não. */
  faltam: number;
}) {
  const [revisar, setRevisar] = useState(false);
  const [motivo, setMotivo] = useState("");
  const ato = useAto();
  const podeConcluir = itens > 0 && !["completed", "applied", "archived"].includes(estado);
  return (
    <div className="grid gap-2" data-testid="fechamento-pesquisa">
      <div className="flex flex-wrap items-center gap-2">
        {podeConcluir && (
          <Button
            icon="check-circle"
            disabled={faltam > 0}
            loading={ato.ocupado}
            onClick={() => ato.rodar(() => concluirPesquisa(pesquisa))}
          >
            Concluir cotação
          </Button>
        )}
        {estado !== "archived" && (
          <Button variant="ghost" icon="arrows-clockwise" onClick={() => setRevisar(true)}>
            Nova revisão
          </Button>
        )}
      </div>
      {podeConcluir && faltam > 0 && (
        <p className="text-[length:var(--gc-fs-sm)] text-secundario">
          Para concluir, todos os itens precisam estar concluídos. Faltam {faltam}.
        </p>
      )}
      <Retorno estado={ato.estado} />
      <Dialog
        open={revisar}
        onClose={() => setRevisar(false)}
        icon="arrows-clockwise"
        title="Criar uma revisão"
        description="A revisão é a mesma pesquisa numa versão nova e editável, com os itens e os preços copiados. A versão atual fica guardada como está."
        footer={
          <>
            <Button variant="ghost" onClick={() => setRevisar(false)}>
              Cancelar
            </Button>
            <Button
              loading={ato.ocupado}
              onClick={() => {
                setRevisar(false);
                ato.rodar(() => criarRevisao(pesquisa, motivo));
              }}
            >
              Criar revisão
            </Button>
          </>
        }
      >
        <Field label="Motivo da revisão" htmlFor="revisao-motivo" optional>
          <Textarea id="revisao-motivo" rows={2} maxLength={1000} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </Field>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// M10b: pesquisar preços de UM item (pelo worker)
// ---------------------------------------------------------------------------
export function BuscaDoItem({
  pesquisa,
  item,
  termo,
  uf,
  chave,
}: {
  pesquisa: string;
  item: string;
  termo: string;
  uf: string;
  chave: string;
}) {
  const [estado, acao, enviando] = useActionState(buscarItem.bind(null, pesquisa, item, chave), INICIAL);
  return (
    <Card
      title="Pesquisar preços deste item"
      subtitle="A descrição do item continua sendo a referência de comparação; o termo só amplia a consulta às fontes oficiais."
      divided
    >
      <form action={acao} className="grid gap-4 md:grid-cols-[3fr_1fr_1fr]" data-testid="busca-item">
        <Field label="Termo da busca" htmlFor="busca-termo">
          <Input id="busca-termo" name="termo" defaultValue={termo} maxLength={300} />
        </Field>
        <Field label="Janela (dias)" htmlFor="busca-janela" help="De 30 a 180">
          <Input id="busca-janela" name="janela" type="number" min={30} max={180} step={30} defaultValue={180} />
        </Field>
        <Field label="UF" htmlFor="busca-uf" optional>
          <Input id="busca-uf" name="uf" maxLength={2} defaultValue={uf} />
        </Field>
        <div className="grid gap-3 md:col-span-3">
          <Retorno estado={estado} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" name="modo" value="manual" variant="secondary" icon="magnifying-glass" loading={enviando}>
              Pesquisar preços
            </Button>
            <Button type="submit" name="modo" value="automatico" loading={enviando}>
              Cotação automática deste item
            </Button>
          </div>
          <p className="text-[length:var(--gc-fs-sm)] text-secundario">
            Busca pelo termo literal, em todas as fontes oficiais. A ampliação por sinônimos continua no GovDocs.
          </p>
        </div>
      </form>
    </Card>
  );
}

export function ProgressoDaBusca({ jobId }: { jobId: string }) {
  const router = useRouter();
  const { job, erro } = useJob(jobId, () => router.refresh());
  if (!job) return <Alert variant="info" compact>{erro ?? "Consultando a busca..."}</Alert>;
  if (job.estado === "succeeded")
    return (
      <Alert variant="success" compact title="Busca concluída">
        {job.resultado?.mensagem || "As referências encontradas estão abaixo."}
      </Alert>
    );
  if (job.estado === "failed")
    return (
      <Alert variant="error" compact>
        A busca não terminou. O que já estava no item continua; tente de novo.
      </Alert>
    );
  return <Alert variant="info" compact>{job.estado === "queued" ? "Busca na fila." : "Consultando as fontes oficiais..."}</Alert>;
}
