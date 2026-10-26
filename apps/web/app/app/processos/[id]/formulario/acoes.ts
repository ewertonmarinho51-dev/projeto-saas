"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { chamarApi, ErroDaApi, type FormularioGravado, type ItemDaPlanilha, type PlanilhaLida } from "@/lib/api";

const UUID = /^[0-9a-f-]{36}$/i;
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export type EstadoDaGravacao = {
  erro: string | null;
  // DESCARTE_PENDENTE: o que sai se a pessoa confirmar.
  descarte: string | null;
};

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Só quem criou o processo (ou o administrador) pode alterar o formulário.",
  404: "Processo não encontrado.",
  413: "O arquivo passa do limite.",
  415: "Formato de arquivo não suportado.",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown, padrao: string): string {
  if (e instanceof ErroDaApi) {
    // 422 traz a regra do domínio escrita para a pessoa (campo obrigatório,
    // planilha ilegível): essa mensagem vale mostrar como veio.
    if (e.status === 422 && e.mensagem) return e.mensagem;
    if (e.status === 409 && e.codigo === "VERSION_CONFLICT")
      return "Outra pessoa alterou este processo depois que você o abriu. Recarregue para ver a versão atual.";
    return MENSAGENS[e.status] ?? padrao;
  }
  return padrao;
}

/**
 * Grava o formulário. `payload` é o JSON montado pela tela (valores +
 * itens); `iniciar` = "Iniciar elaboração dos documentos"; `confirmar` vem
 * marcado só depois que a pessoa viu a lista de documentos que saem.
 */
export async function gravarFormulario(_: EstadoDaGravacao, form: FormData): Promise<EstadoDaGravacao> {
  const id = String(form.get("id") ?? "");
  if (!UUID.test(id)) return { erro: "Processo inválido.", descarte: null };
  const iniciar = form.get("iniciar") === "1";
  let valores: Record<string, unknown>;
  try {
    valores = JSON.parse(String(form.get("payload") ?? "{}")) as Record<string, unknown>;
  } catch {
    return { erro: "Não foi possível ler o formulário. Recarregue a página.", descarte: null };
  }
  try {
    await chamarApi<FormularioGravado>(`/processos/${id}/formulario`, {
      metodo: "PUT",
      corpo: { valores, iniciar, confirmar_descarte: form.get("confirmar") === "1" },
      cabecalhos: { "If-Match": `"${String(form.get("versao") ?? "")}"` },
      tempoMs: 15000,
    });
  } catch (e) {
    if (e instanceof ErroDaApi && e.codigo === "DESCARTE_PENDENTE") return { erro: null, descarte: e.mensagem };
    return { erro: mensagem(e, "Não foi possível salvar agora. Tente de novo."), descarte: null };
  }
  revalidatePath(`/app/processos/${id}`);
  if (iniciar) redirect(`/app/processos/${id}?iniciado=1`);
  redirect(`/app/processos/${id}/formulario?salvo=1`);
}

export type LeituraDaPlanilha = { erro: string | null; itens: ItemDaPlanilha[] | null; total: string | null };

/** Lê a planilha XLSX e devolve os itens para a pessoa conferir. Não grava. */
export async function lerPlanilha(id: string, form: FormData): Promise<LeituraDaPlanilha> {
  if (!UUID.test(id)) return { erro: "Processo inválido.", itens: null, total: null };
  const arquivo = form.get("planilha");
  if (!(arquivo instanceof File) || arquivo.size === 0) return { erro: "Escolha a planilha (XLSX).", itens: null, total: null };
  if (arquivo.size > 5 * 1024 * 1024) return { erro: "A planilha passa de 5 MB. Divida o arquivo.", itens: null, total: null };
  try {
    const { dados } = await chamarApi<PlanilhaLida>(`/processos/${id}/formulario/planilha`, {
      metodo: "POST",
      corpoBruto: { dados: await arquivo.arrayBuffer(), tipo: XLSX },
      tempoMs: 30000,
    });
    return { erro: null, itens: dados.itens, total: dados.valor_estimado_exibicao };
  } catch (e) {
    return { erro: mensagem(e, "Não foi possível ler a planilha agora."), itens: null, total: null };
  }
}

export type LeituraDoMemorando = { erro: string | null; texto: string | null };

/** Extrai o texto do memorando/ofício (PDF, DOCX, TXT, MD). Não grava. */
export async function lerMemorando(id: string, form: FormData): Promise<LeituraDoMemorando> {
  if (!UUID.test(id)) return { erro: "Processo inválido.", texto: null };
  const arquivo = form.get("memorando");
  if (!(arquivo instanceof File) || arquivo.size === 0) return { erro: "Escolha o arquivo do memorando.", texto: null };
  if (arquivo.size > 15 * 1024 * 1024) return { erro: "O arquivo passa de 15 MB.", texto: null };
  try {
    const { dados } = await chamarApi<{ texto: string }>(
      `/processos/${id}/formulario/memorando?nome=${encodeURIComponent(arquivo.name)}`,
      { metodo: "POST", corpoBruto: { dados: await arquivo.arrayBuffer(), tipo: arquivo.type || "application/octet-stream" }, tempoMs: 30000 },
    );
    return { erro: null, texto: dados.texto };
  } catch (e) {
    return { erro: mensagem(e, "Não foi possível ler o arquivo agora."), texto: null };
  }
}
