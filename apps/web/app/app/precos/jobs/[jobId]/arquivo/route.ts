import { NextResponse } from "next/server";

import { baixarDaApi, ErroDaApi } from "@/lib/api";

const UUID = /^[0-9a-f-]{36}$/i;

// Os mesmos tipos que a API serve (lista fechada em `artefatos.py`).
const TIPOS = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/zip",
]);

const SEM_CACHE = { "Cache-Control": "private, no-store" };

/**
 * Download do relatório gerado.
 *
 * O navegador não fala com a API: a sessão vem do cookie, o token vai pelo
 * servidor, e a API entrega o arquivo só ao dono do job (RLS da 0031). O
 * corpo passa direto, sem ser lido aqui. Tipo fora da lista vira erro, não
 * download: nada que o navegador possa interpretar como página sai daqui.
 */
export async function GET(_: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  if (!UUID.test(jobId)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404, headers: SEM_CACHE });
  let resposta: Response;
  try {
    resposta = await baixarDaApi(`/jobs/${jobId}/artefato`);
  } catch (e) {
    const status = e instanceof ErroDaApi ? e.status : 503;
    return NextResponse.json({ code: e instanceof ErroDaApi ? e.codigo : "UNAVAILABLE" }, { status, headers: SEM_CACHE });
  }
  const tipo = (resposta.headers.get("content-type") ?? "").split(";")[0].trim();
  if (!resposta.ok || !TIPOS.has(tipo)) {
    let codigo = "ERRO";
    try {
      codigo = ((await resposta.json()) as { code?: string }).code ?? codigo;
    } catch {
      /* corpo não-JSON */
    }
    return NextResponse.json({ code: codigo }, { status: resposta.ok ? 502 : resposta.status, headers: SEM_CACHE });
  }
  return new Response(resposta.body, {
    status: 200,
    headers: {
      ...SEM_CACHE,
      "Content-Type": tipo,
      "Content-Disposition": resposta.headers.get("content-disposition") ?? "attachment",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
