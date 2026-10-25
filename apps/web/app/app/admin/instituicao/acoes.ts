"use server";

import { revalidatePath } from "next/cache";

import { chamarApi, ErroDaApi, type PreviaDoModelo } from "@/lib/api";

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
    if ((e.status === 422 || e.status === 409 || e.status === 413) && e.mensagem) return e.mensagem;
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

// ---------------------------------------------------------------------------
// Prefeitura, Secretarias e Identidade visual (M7b)
// ---------------------------------------------------------------------------
const CAMPOS_DA_PREFEITURA = ["nome_oficial", "cnpj", "sigla", "cidade", "endereco", "telefone", "email", "site"];
const LIMITE_DO_MODELO = 10 * 1024 * 1024;

export async function salvarPrefeitura(_: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  // Vazio vai como "", e a API grava NULL: o sistema não inventa dado.
  const corpo = Object.fromEntries(CAMPOS_DA_PREFEITURA.map((c) => [c, texto(form, c)]));
  return ato(() => chamarApi("/admin/instituicao/prefeitura", { metodo: "PUT", corpo }), "Dados institucionais salvos.");
}

export async function criarSecretaria(_: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  const nome = texto(form, "nome");
  if (!nome) return { erro: "Informe o nome da secretaria.", ok: null };
  return ato(
    () => chamarApi("/admin/instituicao/secretarias", { metodo: "POST", corpo: { nome, sigla: texto(form, "sigla") } }),
    `Secretaria ${nome} criada.`,
  );
}

export async function editarSecretaria(id: string, mudanca: { ativo?: boolean; padrao?: true }): Promise<EstadoDoAto> {
  if (!UUID.test(id)) return { erro: "Secretaria inválida.", ok: null };
  const ok = mudanca.padrao ? "Identidade padrão do município atualizada." : mudanca.ativo ? "Secretaria reativada." : "Secretaria desativada.";
  return ato(() => chamarApi(`/admin/instituicao/secretarias/${id}`, { metodo: "PATCH", corpo: mudanca }), ok);
}

async function modelo(form: FormData): Promise<Record<string, unknown> | string> {
  const arquivo = form.get("modelo");
  if (!(arquivo instanceof File) || arquivo.size === 0) return "Envie o documento-modelo em PDF.";
  if (arquivo.size > LIMITE_DO_MODELO) return "O documento-modelo passa do limite de 10 MB.";
  return {
    nome_arquivo: arquivo.name.slice(0, 200),
    conteudo: Buffer.from(await arquivo.arrayBuffer()).toString("base64"),
    cabecalho_pct: Number(texto(form, "cabecalho_pct")) || 14,
    rodape_pct: Number(texto(form, "rodape_pct")) || 10,
    marca: form.get("marca") === "on",
  };
}

export async function previaDoModelo(form: FormData): Promise<{ erro: string | null; previa: PreviaDoModelo | null }> {
  const corpo = await modelo(form);
  if (typeof corpo === "string") return { erro: corpo, previa: null };
  try {
    const { dados } = await chamarApi<PreviaDoModelo>("/admin/instituicao/identidades/previa", {
      metodo: "POST",
      corpo,
      tempoMs: 30_000,
    });
    return { erro: null, previa: dados };
  } catch (e) {
    return { erro: mensagem(e), previa: null };
  }
}

export async function salvarIdentidadePorImagem(form: FormData): Promise<EstadoDoAto> {
  const orgao = texto(form, "orgao");
  if (!orgao) return { erro: "Informe o nome do órgão.", ok: null };
  const corpo = await modelo(form);
  if (typeof corpo === "string") return { erro: corpo, ok: null };
  return ato(
    () =>
      chamarApi("/admin/instituicao/identidades/imagem", {
        metodo: "POST",
        corpo: { ...corpo, orgao, padrao: form.get("padrao") === "on" },
        tempoMs: 30_000,
      }),
    "Identidade (imagem) salva.",
  );
}

export async function salvarIdentidadePorTexto(_: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  const orgao = texto(form, "orgao");
  if (!orgao) return { erro: "Informe o nome do órgão.", ok: null };
  return ato(
    () =>
      chamarApi("/admin/instituicao/identidades/texto", {
        metodo: "POST",
        corpo: {
          orgao,
          cabecalho: texto(form, "cabecalho"),
          rodape: texto(form, "rodape"),
          marca_dagua: texto(form, "marca_dagua"),
          padrao: form.get("padrao") === "on",
        },
      }),
    "Identidade (texto) salva.",
  );
}

export async function tornarIdentidadePadrao(id: string): Promise<EstadoDoAto> {
  if (!UUID.test(id)) return { erro: "Identidade inválida.", ok: null };
  return ato(() => chamarApi(`/admin/instituicao/identidades/${id}/padrao`, { metodo: "PUT" }), "Identidade padrão atualizada.");
}

export async function excluirIdentidade(id: string): Promise<EstadoDoAto> {
  if (!UUID.test(id)) return { erro: "Identidade inválida.", ok: null };
  return ato(() => chamarApi(`/admin/instituicao/identidades/${id}`, { metodo: "DELETE" }), "Identidade excluída.");
}
