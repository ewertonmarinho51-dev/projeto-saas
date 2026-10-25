"use server";

import { revalidatePath } from "next/cache";

import { chamarApi, ErroDaApi } from "@/lib/api";

export type EstadoDoAto = { erro: string | null; ok: string | null };

const UUID = /^[0-9a-f-]{36}$/i;
const CAMINHO = "/app/admin/instituicao";

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Só o administrador do município faz esta alteração.",
  404: "Não encontrado, ou a seção está desligada.",
  409: "Módulo indisponível nesta versão do sistema.",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown): string {
  if (e instanceof ErroDaApi) {
    if (e.status === 422 && e.mensagem) return e.mensagem;
    return MENSAGENS[e.status] ?? "Não foi possível salvar agora. Tente de novo.";
  }
  return "Não foi possível salvar agora. Tente de novo.";
}

const texto = (form: FormData, nome: string) => String(form.get(nome) ?? "").trim();

async function ato(executar: () => Promise<unknown>, ok: string): Promise<EstadoDoAto> {
  try {
    await executar();
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath(CAMINHO);
  return { erro: null, ok };
}

export async function cadastrarServidor(_: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  const nome = texto(form, "nome");
  if (!nome) return { erro: "Informe o nome do servidor.", ok: null };
  return ato(
    () =>
      chamarApi("/admin/instituicao/servidores", {
        metodo: "POST",
        corpo: { nome, cargo: texto(form, "cargo") || null, matricula: texto(form, "matricula") || null, email: texto(form, "email") || null },
      }),
    `${nome} cadastrado.`,
  );
}

export async function alternarServidor(id: string, ativo: boolean): Promise<EstadoDoAto> {
  if (!UUID.test(id)) return { erro: "Servidor inválido.", ok: null };
  return ato(() => chamarApi(`/admin/instituicao/servidores/${id}`, { metodo: "PATCH", corpo: { ativo } }), ativo ? "Servidor reativado." : "Servidor desativado.");
}

export async function registrarPortaria(_: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  const numero = texto(form, "numero");
  if (!numero) return { erro: "Informe o número da portaria.", ok: null };
  const secretaria = texto(form, "secretaria_id");
  if (!UUID.test(secretaria)) return { erro: "Escolha a secretaria.", ok: null };
  const ano = Number.parseInt(texto(form, "ano"), 10);
  return ato(
    () =>
      chamarApi("/admin/instituicao/portarias", {
        metodo: "POST",
        corpo: {
          secretaria_id: secretaria,
          tipo: texto(form, "tipo"),
          numero,
          ano,
          data_publicacao: texto(form, "data_publicacao") || null,
          data_inicio_vigencia: texto(form, "data_inicio_vigencia"),
          data_fim_vigencia: texto(form, "data_fim_vigencia") || null,
        },
      }),
    `Portaria ${numero}/${ano} registrada como RASCUNHO. Ative-a quando estiver publicada.`,
  );
}

export async function mudarSituacaoDaPortaria(id: string, status: string): Promise<EstadoDoAto> {
  if (!UUID.test(id)) return { erro: "Portaria inválida.", ok: null };
  return ato(() => chamarApi(`/admin/instituicao/portarias/${id}`, { metodo: "PATCH", corpo: { status } }), "Situação atualizada.");
}

export async function adicionarMembro(portaria: string, _: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  if (!UUID.test(portaria)) return { erro: "Portaria inválida.", ok: null };
  const servidor = texto(form, "servidor_id");
  if (!UUID.test(servidor)) return { erro: "Escolha o servidor.", ok: null };
  return ato(
    () =>
      chamarApi(`/admin/instituicao/portarias/${portaria}/membros`, {
        metodo: "POST",
        corpo: { servidor_id: servidor, funcao: texto(form, "funcao") },
      }),
    "Membro designado.",
  );
}

export async function moduloNaPrefeitura(modulo: string, habilitado: boolean): Promise<EstadoDoAto> {
  return ato(
    () => chamarApi(`/admin/instituicao/modulos/prefeitura/${encodeURIComponent(modulo)}`, { metodo: "PUT", corpo: { habilitado } }),
    "Módulo atualizado na Prefeitura.",
  );
}

export async function moduloNaSecretaria(secretaria: string, modulo: string, estado: string): Promise<EstadoDoAto> {
  if (!UUID.test(secretaria)) return { erro: "Secretaria inválida.", ok: null };
  return ato(
    () =>
      chamarApi(`/admin/instituicao/modulos/secretarias/${secretaria}/${encodeURIComponent(modulo)}`, {
        metodo: "PUT",
        corpo: { estado },
      }),
    "Módulo atualizado na secretaria.",
  );
}
