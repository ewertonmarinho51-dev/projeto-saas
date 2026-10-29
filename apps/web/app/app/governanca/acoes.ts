"use server";

import { revalidatePath } from "next/cache";

import { chamarApi, ErroDaApi } from "@/lib/api";

export type EstadoDoAto = { erro: string | null; ok: string | null };

const UUID = /^[0-9a-f-]{36}$/i;
const CAMINHO = "/app/governanca";

function mensagem(e: unknown): string {
  if (e instanceof ErroDaApi) {
    // A recusa do banco (papel, máquina de estados, trava) já vem escrita para gente.
    if ([403, 409, 422].includes(e.status) && e.mensagem) return e.mensagem;
    if (e.status === 404) return "Não encontrado — ou o Centro foi desligado.";
    if (e.status === 401) return "Sua sessão expirou. Entre novamente.";
  }
  return "Não foi possível concluir agora. Tente de novo.";
}

async function ato(executar: () => Promise<unknown>, ok: string): Promise<EstadoDoAto> {
  try {
    await executar();
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath(CAMINHO);
  return { erro: null, ok };
}

const paragrafos = (texto: string) =>
  texto
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);

const lista = (texto: string, separador: RegExp) =>
  texto
    .split(separador)
    .map((p) => p.trim())
    .filter(Boolean);

export async function criarClausula(_: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  const chave = String(form.get("chave") ?? "").trim();
  const titulo = String(form.get("titulo") ?? "").trim();
  if (!titulo) return { erro: "Informe o título da cláusula.", ok: null };
  return ato(
    () =>
      chamarApi("/governanca/artefatos", {
        metodo: "POST",
        corpo: {
          tipo: "clausula",
          chave,
          payload: {
            titulo,
            comportamento: String(form.get("comportamento") ?? ""),
            tipo_documental: String(form.get("tipo_documental") ?? ""),
            blocos: paragrafos(String(form.get("texto") ?? "")),
            parametros_permitidos: lista(String(form.get("parametros") ?? ""), /,/),
            base_legal: lista(String(form.get("base_legal") ?? ""), /;/),
          },
        },
      }),
    `Rascunho ${chave} criado.`,
  );
}

export async function editarRascunho(
  versao: string,
  atualizadoEm: string,
  payload: Record<string, unknown>,
  texto: string,
): Promise<EstadoDoAto> {
  if (!UUID.test(versao)) return { erro: "Versão inválida.", ok: null };
  return ato(
    () =>
      chamarApi(`/governanca/versoes/${versao}`, {
        metodo: "PUT",
        corpo: { payload: { ...payload, blocos: paragrafos(texto) } },
        cabecalhos: { "If-Match": `"${atualizadoEm}"` },
      }),
    "Rascunho salvo.",
  );
}

// Com a versão que a pessoa leu: aprova/publica aquele texto, não um editado no meio.
export async function transicionar(versao: string, atualizadoEm: string, status: string): Promise<EstadoDoAto> {
  if (!UUID.test(versao)) return { erro: "Versão inválida.", ok: null };
  return ato(
    () =>
      chamarApi(`/governanca/versoes/${versao}/transicao`, {
        metodo: "POST",
        corpo: { status },
        cabecalhos: { "If-Match": `"${atualizadoEm}"` },
      }),
    "Situação atualizada.",
  );
}

export async function derivar(versao: string): Promise<EstadoDoAto> {
  if (!UUID.test(versao)) return { erro: "Versão inválida.", ok: null };
  return ato(
    () => chamarApi(`/governanca/versoes/${versao}/derivacao`, { metodo: "POST" }),
    "Nova versão em rascunho criada a partir da publicada.",
  );
}
