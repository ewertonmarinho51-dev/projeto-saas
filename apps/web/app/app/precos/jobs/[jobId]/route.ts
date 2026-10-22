import { NextResponse } from "next/server";

import { chamarApi, ErroDaApi, type Job } from "@/lib/api";

const UUID = /^[0-9a-f-]{36}$/i;

/**
 * Estado de um job para o componente que acompanha a coleta.
 *
 * Rota do PRÓPRIO web (o navegador não fala com a API): a sessão vem do
 * cookie, o token vai para a API pelo servidor, e a API devolve o job só
 * ao dono. `no-store`: progresso de um usuário não vira cache de ninguém.
 */
export async function GET(_: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  const semCache = { "Cache-Control": "private, no-store" };
  if (!UUID.test(jobId)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404, headers: semCache });
  try {
    const { dados } = await chamarApi<Job>(`/jobs/${jobId}`);
    return NextResponse.json(dados, { headers: semCache });
  } catch (e) {
    const status = e instanceof ErroDaApi ? e.status : 503;
    return NextResponse.json({ code: e instanceof ErroDaApi ? e.codigo : "UNAVAILABLE" }, { status, headers: semCache });
  }
}
