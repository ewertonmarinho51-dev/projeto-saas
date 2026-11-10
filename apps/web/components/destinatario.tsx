"use client";

import { useActionState, useState } from "react";

import { definirDestinatario, type EstadoDoDestinatario } from "@/app/app/precos/acoes";
import { Alert, Button, Field, Input, Select } from "@/design-system";
import type { DestinatarioDoRelatorio, OrgaoDoMunicipio } from "@/lib/api";

export const OUTRO_ORGAO = "outro";
export const NAO_INFORMADO = "nenhum";

/** O valor do seletor que corresponde ao destinatário gravado (ou ao padrão da criação). */
function valorInicial(orgaos: OrgaoDoMunicipio[], atual?: DestinatarioDoRelatorio): string {
  if (atual?.tipo === "secretaria" && atual.secretaria_id) return atual.secretaria_id;
  if (atual?.tipo === "externo") return OUTRO_ORGAO;
  if (atual?.tipo === "nenhum") return NAO_INFORMADO;
  return (orgaos.find((o) => o.vinculo) ?? orgaos.find((o) => o.padrao) ?? orgaos[0])?.id ?? OUTRO_ORGAO;
}

/**
 * Para quem vai o relatório — é isso que decide o timbrado (0041). A
 * prefeitura ou uma secretaria dela: sai com o timbrado dela. Outro órgão:
 * sai sem timbrado. Campos `destinatario` e `destinatario_externo` do
 * formulário que o contém.
 */
export function CampoDestinatario({
  orgaos,
  atual,
}: {
  orgaos: OrgaoDoMunicipio[];
  atual?: DestinatarioDoRelatorio;
}) {
  const [escolha, setEscolha] = useState(() => valorInicial(orgaos, atual));
  const desconhecida =
    atual?.tipo === "secretaria" && atual.secretaria_id && !orgaos.some((o) => o.id === atual.secretaria_id)
      ? [{ value: atual.secretaria_id, label: "Secretaria inativa ou não encontrada (sai sem timbrado)" }]
      : [];
  const opcoes = [
    ...desconhecida,
    ...orgaos.map((o) => ({ value: o.id, label: o.nome })),
    ...(atual?.tipo === "nenhum" || orgaos.length === 0
      ? [{ value: NAO_INFORMADO, label: "Não informado: segue o timbrado do seu vínculo" }]
      : []),
    { value: OUTRO_ORGAO, label: "Outro órgão: sai sem timbrado" },
  ];
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <Field
        label="Para qual órgão é o relatório?"
        htmlFor="destinatario"
        help="A prefeitura ou uma secretaria dela: o relatório sai com o timbrado dela."
      >
        <Select id="destinatario" name="destinatario" value={escolha} onChange={(e) => setEscolha(e.target.value)} options={opcoes} />
      </Field>
      {escolha === OUTRO_ORGAO && (
        <Field label="Nome do outro órgão" htmlFor="destinatario_externo" required help="O relatório sai sem timbrado.">
          <Input
            id="destinatario_externo"
            name="destinatario_externo"
            required
            maxLength={200}
            defaultValue={atual?.tipo === "externo" ? atual.nome : ""}
            placeholder="Ex.: Prefeitura Municipal de Ulianópolis"
            autoComplete="off"
          />
        </Field>
      )}
    </div>
  );
}

/**
 * O destinatário de uma pesquisa existente. Para o autor ou o administrador,
 * editável (vale para as próximas emissões); para os demais, só a linha que
 * diz que timbrado sai — eles não conseguiriam salvar a troca.
 */
export function DestinatarioDaPesquisa({
  pesquisa,
  orgaos,
  atual,
  podeAlterar,
}: {
  pesquisa: string;
  orgaos: OrgaoDoMunicipio[];
  atual: DestinatarioDoRelatorio;
  podeAlterar: boolean;
}) {
  if (!podeAlterar) {
    return (
      <p
        className="border-b border-linha pb-3 text-[length:var(--gc-fs-sm)] text-secundario"
        data-testid="destinatario-do-relatorio"
      >
        Destinatário e timbrado: {resumo(orgaos, atual)}
      </p>
    );
  }
  return <FormularioDoDestinatario pesquisa={pesquisa} orgaos={orgaos} atual={atual} />;
}

function FormularioDoDestinatario({
  pesquisa,
  orgaos,
  atual,
}: {
  pesquisa: string;
  orgaos: OrgaoDoMunicipio[];
  atual: DestinatarioDoRelatorio;
}) {
  const [estado, acao, enviando] = useActionState<EstadoDoDestinatario, FormData>(definirDestinatario, {
    erro: null,
    ok: null,
  });
  return (
    <details className="group border-b border-linha pb-3" data-testid="destinatario-do-relatorio">
      <summary className="cursor-pointer text-[length:var(--gc-fs-sm)] font-[number:var(--weight-medium)] text-acento">
        Destinatário e timbrado: {resumo(orgaos, atual)}
      </summary>
      <form action={acao} className="mt-4 grid gap-4">
        <input type="hidden" name="pesquisa" value={pesquisa} />
        <CampoDestinatario orgaos={orgaos} atual={atual} />
        <div aria-live="polite">
          {estado.erro && <Alert variant="error" compact>{estado.erro}</Alert>}
          {estado.ok && <Alert variant="success" compact>{estado.ok}</Alert>}
        </div>
        <div>
          <Button type="submit" variant="secondary" loading={enviando}>
            Salvar destinatário
          </Button>
        </div>
      </form>
    </details>
  );
}

function resumo(orgaos: OrgaoDoMunicipio[], atual: DestinatarioDoRelatorio): string {
  if (atual.tipo === "externo") return `${atual.nome} (sem timbrado)`;
  if (atual.tipo === "nenhum") return "não informado (timbrado do seu vínculo)";
  const orgao = orgaos.find((o) => o.id === atual.secretaria_id);
  return orgao ? orgao.nome : "secretaria não encontrada (sem timbrado)";
}
