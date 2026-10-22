"use server";

import { redirect } from "next/navigation";

import { criarClienteServidor } from "@/lib/supabase/server";

export type EstadoDaSenha = { erro: string | null };

// Mesmo mínimo do Auth de homologação (12). O Supabase pode exigir mais;
// a mensagem dele não é repassada, para não vazar política interna.
const MINIMO = 12;

export async function trocarSenha(_: EstadoDaSenha, form: FormData): Promise<EstadoDaSenha> {
  const nova = String(form.get("nova") ?? "");
  const confirmacao = String(form.get("confirmacao") ?? "");
  if (nova.length < MINIMO) return { erro: `A senha precisa de pelo menos ${MINIMO} caracteres.` };
  if (nova.length > 256) return { erro: "Senha longa demais." };
  if (nova !== confirmacao) return { erro: "As duas senhas não conferem." };

  const supabase = await criarClienteServidor();
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims) redirect("/entrar");
  const { error } = await supabase.auth.updateUser({ password: nova });
  if (error) return { erro: "Não foi possível trocar a senha. Tente outra." };
  // Encerra todas as sessões, inclusive esta: entra de novo com a nova.
  await supabase.auth.signOut({ scope: "global" });
  redirect("/entrar?senha=1");
}
