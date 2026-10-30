import { NextResponse } from "next/server";

import { baixarDaApi, ErroDaApi } from "@/lib/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HASH = /^[0-9a-f]{64}$/;
const TIPOS: Record<string, string> = {
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pdf: "application/pdf",
};
const SEM_CACHE = { "Cache-Control": "private, no-store" };

/**
 * Exportação da revisão PERSISTIDA exata (DOCX ou PDF do motor nativo).
 *
 * Revisão e hash vêm da tela, mas só escolhem o que pedir: a API recusa
 * (409) se não forem mais a cabeça do documento, e o arquivo sai do motor,
 * não do navegador. O corpo passa direto, sem ser lido aqui.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; documentoId: string }> },
) {
  const { id, documentoId } = await params;
  const url = new URL(request.url);
  const formato = url.searchParams.get("formato") ?? "";
  const revisao = url.searchParams.get("revisao") ?? "";
  const hash = url.searchParams.get("hash") ?? "";
  if (!UUID.test(id) || !UUID.test(documentoId) || !TIPOS[formato] || !/^[1-9]\d{0,8}$/.test(revisao) || !HASH.test(hash)) {
    return NextResponse.json({ code: "NOT_FOUND" }, { status: 404, headers: SEM_CACHE });
  }
  let resposta: Response;
  try {
    const consulta = new URLSearchParams({ processo_id: id, formato, revisao, content_hash: hash });
    resposta = await baixarDaApi(`/documentos/${documentoId}/exportacao?${consulta}`);
  } catch (e) {
    const status = e instanceof ErroDaApi ? e.status : 503;
    return NextResponse.json({ code: e instanceof ErroDaApi ? e.codigo : "UNAVAILABLE" }, { status, headers: SEM_CACHE });
  }
  const tipo = (resposta.headers.get("content-type") ?? "").split(";")[0].trim();
  if (!resposta.ok || tipo !== TIPOS[formato]) {
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
