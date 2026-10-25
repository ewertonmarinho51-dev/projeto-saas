import { NextResponse } from "next/server";

import { baixarDaApi, ErroDaApi } from "@/lib/api";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const SEM_CACHE = { "Cache-Control": "private, no-store" };

/** Modelo da planilha orçamentária (o mesmo do wizard), pela API. */
export async function GET() {
  let resposta: Response;
  try {
    resposta = await baixarDaApi("/processos/modelo-planilha.xlsx");
  } catch (e) {
    const status = e instanceof ErroDaApi ? e.status : 503;
    return NextResponse.json({ code: e instanceof ErroDaApi ? e.codigo : "UNAVAILABLE" }, { status, headers: SEM_CACHE });
  }
  const tipo = (resposta.headers.get("content-type") ?? "").split(";")[0].trim();
  if (!resposta.ok || tipo !== XLSX) {
    return NextResponse.json({ code: "ERRO" }, { status: resposta.ok ? 502 : resposta.status, headers: SEM_CACHE });
  }
  return new Response(resposta.body, {
    status: 200,
    headers: {
      ...SEM_CACHE,
      "Content-Type": XLSX,
      "Content-Disposition": 'attachment; filename="modelo-planilha-orcamentaria.xlsx"',
      "X-Content-Type-Options": "nosniff",
    },
  });
}
