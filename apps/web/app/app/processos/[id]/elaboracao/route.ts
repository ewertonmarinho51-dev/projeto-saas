import { NextResponse } from "next/server";

import { chamarApi, ErroDaApi, type Elaboracao } from "@/lib/api";

const UUID = /^[0-9a-f-]{36}$/i;

/**
 * Estado da elaboração para a tela acompanhar a geração. Rota do PRÓPRIO web,
 * como a dos jobs: o token vai para a API pelo servidor, e `no-store` porque
 * o andamento de um processo não vira cache de ninguém.
 */
export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const semCache = { "Cache-Control": "private, no-store" };
  if (!UUID.test(id)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404, headers: semCache });
  try {
    const { dados } = await chamarApi<Elaboracao>(`/processos/${id}/elaboracao`);
    return NextResponse.json(dados, { headers: semCache });
  } catch (e) {
    const status = e instanceof ErroDaApi ? e.status : 503;
    return NextResponse.json(
      { code: e instanceof ErroDaApi ? e.codigo : "UNAVAILABLE" },
      { status, headers: semCache },
    );
  }
}
