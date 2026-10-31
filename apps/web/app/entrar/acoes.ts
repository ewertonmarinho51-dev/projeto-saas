"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { destinoSeguro, emailValido, LimiteDeTentativas } from "@/lib/seguranca";
import { criarClienteServidor } from "@/lib/supabase/server";

export type EstadoDoLogin = { erro: string | null; email: string };

// 5 tentativas por IP + e-mail a cada 15 minutos, além do limite do
// próprio Supabase Auth. Processo único (ADR-007); com réplicas, Redis.
const limite = new LimiteDeTentativas(5, 15 * 60_000);

// Uma mensagem só para senha errada e conta inexistente: distinguir os
// dois permitiria descobrir quais e-mails têm conta.
const RECUSA = "E-mail ou senha incorretos.";

async function ipDoCliente(): Promise<string> {
  const h = await headers();
  // Atrás do Caddy, o primeiro endereço do X-Forwarded-For é o cliente.
  return (h.get("x-forwarded-for") ?? "").split(",")[0].trim() || "local";
}

export async function entrar(_anterior: EstadoDoLogin, form: FormData): Promise<EstadoDoLogin> {
  const email = String(form.get("email") ?? "").trim().toLowerCase();
  const senha = String(form.get("senha") ?? "");
  const proximo = destinoSeguro(form.get("proximo"));

  if (!emailValido(email) || senha.length === 0 || senha.length > 256) {
    return { erro: "Informe um e-mail válido e a senha.", email };
  }
  if (!limite.consumir(`${await ipDoCliente()}|${email}`)) {
    return { erro: "Muitas tentativas. Aguarde alguns minutos e tente de novo.", email };
  }

  const supabase = await criarClienteServidor();
  const { error } = await supabase.auth.signInWithPassword({ email, password: senha });
  if (error) {
    return { erro: RECUSA, email };
  }
  redirect(proximo);
}

export async function sair(form?: FormData) {
  const supabase = await criarClienteServidor();
  // Encerra a sessão no Auth (revoga o refresh) e limpa os cookies.
  await supabase.auth.signOut();
  // Trocar de conta no meio de um link profundo: o destino sobrevive à
  // saída, e passa pela mesma validação do login.
  const proximo = destinoSeguro(form?.get("proximo"));
  redirect(proximo === "/app" ? "/entrar?saiu=1" : `/entrar?saiu=1&proximo=${encodeURIComponent(proximo)}`);
}

export type EstadoDaRecuperacao = { enviado: boolean; erro: string | null };

export async function pedirRecuperacao(
  _anterior: EstadoDaRecuperacao,
  form: FormData,
): Promise<EstadoDaRecuperacao> {
  const email = String(form.get("email") ?? "").trim().toLowerCase();
  if (!emailValido(email)) return { enviado: false, erro: "Informe um e-mail válido." };
  if (!limite.consumir(`recuperar|${await ipDoCliente()}|${email}`)) {
    return { enviado: false, erro: "Muitas tentativas. Aguarde alguns minutos." };
  }
  // A origem do link vem da CONFIGURAÇÃO, não do cabeçalho Host: Host é
  // escrito pelo cliente, e um Host forjado faria o e-mail de recuperação
  // apontar para outro site. (O Supabase também confere a lista de URLs
  // permitidas; esta é a nossa metade.)
  const origem = process.env.GOVCONECT_SITE_URL;
  if (!origem) return { enviado: false, erro: "Recuperação indisponível neste ambiente." };
  const supabase = await criarClienteServidor();
  // A resposta é a mesma exista a conta ou não.
  await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${origem}/auth/confirmar?proximo=/app/conta/senha`,
  });
  return { enviado: true, erro: null };
}
