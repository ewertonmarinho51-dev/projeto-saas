"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import { Alert, Button, Card, Field, Input, Select, Textarea } from "@/design-system";
import { criarClausula, derivar, editarRascunho, transicionar, type EstadoDoAto } from "@/app/app/governanca/acoes";
import type { VersaoDeGovernanca } from "@/lib/api";

const INICIAL: EstadoDoAto = { erro: null, ok: null };

// O nome do ATO, não do estado: o botão diz o que a pessoa está fazendo.
const ATO: Record<string, string> = {
  UNDER_REVIEW: "Enviar para revisão",
  DRAFT: "Devolver a rascunho",
  APPROVED_FOR_SIMULATION: "Aprovar para simulação",
  SHADOW: "Pôr em shadow",
  SCHEDULED: "Agendar",
  PUBLISHED: "Publicar",
  REVOKED: "Revogar",
};

const COMPORTAMENTOS = [
  { value: "FIXED_LOCKED", label: "Fixa (imutável)" },
  { value: "FIXED_PARAMETERIZED", label: "Fixa com parâmetros" },
  { value: "CONDITIONAL_LOCKED", label: "Condicional" },
  { value: "HYBRID", label: "Híbrida" },
  { value: "AI_GENERATED", label: "Gerada por IA" },
];

function Retorno({ estado }: { estado: EstadoDoAto }) {
  if (estado.erro) return <Alert variant="error" compact>{estado.erro}</Alert>;
  if (estado.ok) return <Alert variant="success" compact>{estado.ok}</Alert>;
  return null;
}

function useAto() {
  const [estado, setEstado] = useState<EstadoDoAto>(INICIAL);
  const [ocupado, executar] = useTransition();
  const router = useRouter();
  return {
    estado,
    ocupado,
    rodar: (f: () => Promise<EstadoDoAto>) =>
      executar(async () => {
        const r = await f();
        setEstado(r);
        if (!r.erro) router.refresh();
      }),
  };
}

/** Transições, derivar e editar o rascunho de UMA versão. Quem pode, o banco decide. */
export function AcoesDaVersao({ tipo, versao }: { tipo: string; versao: VersaoDeGovernanca }) {
  const ato = useAto();
  const editavel = tipo === "clausula" && ["DRAFT", "UNDER_REVIEW"].includes(versao.status);
  const blocos = Array.isArray(versao.payload.blocos) ? (versao.payload.blocos as string[]).join("\n\n") : "";
  const [texto, setTexto] = useState(blocos);
  return (
    <div className="grid gap-3" data-testid="acoes-versao">
      {editavel && (
        <div className="grid gap-2">
          <Field label="Texto do rascunho" htmlFor={`texto-${versao.id}`} help="Um parágrafo por linha em branco.">
            <Textarea id={`texto-${versao.id}`} rows={4} value={texto} onChange={(e) => setTexto(e.target.value)} />
          </Field>
          <Button
            variant="secondary"
            size="sm"
            className="justify-self-start"
            loading={ato.ocupado}
            disabled={texto === blocos}
            onClick={() => ato.rodar(() => editarRascunho(versao.id, versao.atualizado_em, versao.payload, texto))}
          >
            Salvar rascunho
          </Button>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {versao.proximos.map((destino) => (
          <Button
            key={destino}
            size="sm"
            variant={destino === "PUBLISHED" ? "primary" : destino === "REVOKED" ? "danger-subtle" : "ghost"}
            loading={ato.ocupado}
            onClick={() => ato.rodar(() => transicionar(versao.id, versao.atualizado_em, destino))}
          >
            {ATO[destino] ?? destino}
          </Button>
        ))}
        {versao.status === "PUBLISHED" && (
          <Button size="sm" variant="ghost" icon="copy" loading={ato.ocupado} onClick={() => ato.rodar(() => derivar(versao.id))}>
            Derivar nova versão
          </Button>
        )}
      </div>
      <Retorno estado={ato.estado} />
    </div>
  );
}

export function NovaClausula() {
  const [estado, acao, enviando] = useActionState(criarClausula, INICIAL);
  return (
    <Card title="Nova cláusula" subtitle="Nasce como rascunho. Revisar e publicar seguem o papel de cada um." divided>
      <form action={acao} className="grid gap-4 md:grid-cols-2" data-testid="nova-clausula">
        <Field label="Chave estável" htmlFor="cl-chave" required help="Minúsculas, pontos e hífens. Ex.: clausula.tr.garantia">
          <Input id="cl-chave" name="chave" maxLength={200} />
        </Field>
        <Field label="Título" htmlFor="cl-titulo" required>
          <Input id="cl-titulo" name="titulo" maxLength={300} />
        </Field>
        <Field label="Comportamento" htmlFor="cl-comp">
          <Select id="cl-comp" name="comportamento" options={COMPORTAMENTOS} defaultValue="FIXED_LOCKED" />
        </Field>
        <Field label="Tipo documental" htmlFor="cl-doc">
          <Select id="cl-doc" name="tipo_documental" options={["dfd", "etp", "tr", "edital"]} defaultValue="tr" />
        </Field>
        <Field label="Texto" htmlFor="cl-texto" required className="md:col-span-2" help="Use {{parametro}} para os campos parametrizados.">
          <Textarea id="cl-texto" name="texto" rows={5} />
        </Field>
        <Field label="Parâmetros permitidos" htmlFor="cl-param" optional help="Separados por vírgula">
          <Input id="cl-param" name="parametros" />
        </Field>
        <Field label="Base legal" htmlFor="cl-base" optional help="Separadas por ponto e vírgula">
          <Input id="cl-base" name="base_legal" />
        </Field>
        <div className="grid gap-3 md:col-span-2">
          <Retorno estado={estado} />
          <Button type="submit" loading={enviando} className="justify-self-start">
            Criar rascunho
          </Button>
        </div>
      </form>
    </Card>
  );
}
