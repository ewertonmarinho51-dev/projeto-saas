"use server";

import { revalidatePath } from "next/cache";

import { chamarApi, ErroDaApi } from "@/lib/api";

export type EstadoDoAto = { erro: string | null; ok: string | null };

const UUID = /^[0-9a-f-]{36}$/i;
const CAMINHO = "/app/admin/usuarios";

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Só o administrador do município gerencia usuários.",
  404: "Usuário não encontrado neste município.",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown): string {
  if (e instanceof ErroDaApi) {
    if ([409, 422, 503].includes(e.status) && e.mensagem) return e.mensagem;
    return MENSAGENS[e.status] ?? "Não foi possível concluir agora. Tente de novo.";
  }
  return "Não foi possível concluir agora. Tente de novo.";
}

const texto = (form: FormData, nome: string) => String(form.get(nome) ?? "").trim();

export async function convidarUsuario(_: EstadoDoAto, form: FormData): Promise<EstadoDoAto> {
  const nome = texto(form, "nome");
  const email = texto(form, "email").toLowerCase();
  if (nome.length < 2) return { erro: "Informe o nome completo.", ok: null };
  if (!email.includes("@")) return { erro: "Informe o e-mail institucional.", ok: null };
  const secretaria = texto(form, "secretaria_id");
  try {
    await chamarApi("/admin/usuarios", {
      metodo: "POST",
      corpo: {
        nome,
        email,
        papel: texto(form, "papel") === "admin" ? "admin" : "usuario",
        secretaria_id: UUID.test(secretaria) ? secretaria : null,
      },
    });
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath(CAMINHO);
  return {
    erro: null,
    ok: `Conta de ${email} criada. Para entrar, a pessoa define a senha em "Esqueci minha senha", na tela de entrada.`,
  };
}

export async function alterarUsuario(
  id: string,
  mudanca: { papel?: "usuario" | "admin"; secretaria_id?: string | null; ativo?: boolean },
): Promise<EstadoDoAto> {
  if (!UUID.test(id)) return { erro: "Usuário inválido.", ok: null };
  if (mudanca.secretaria_id && !UUID.test(mudanca.secretaria_id)) return { erro: "Secretaria inválida.", ok: null };
  try {
    await chamarApi(`/admin/usuarios/${id}`, { metodo: "PATCH", corpo: mudanca });
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath(CAMINHO);
  const ok =
    mudanca.ativo === false
      ? "Usuário desativado: o acesso é cortado na próxima ação dele."
      : mudanca.ativo === true
        ? "Usuário reativado."
        : "Alteração salva. Ela vale a partir do próximo acesso da pessoa (até 1 hora).";
  return { erro: null, ok };
}
