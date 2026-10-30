"use server";

import { chamarApi, ErroDaApi, type RevisaoDoHistorico } from "@/lib/api";
import type { AberturaDoEditor, EstadoDoEditor, Lote, Resposta } from "@/lib/wordcraft/transporte";

/**
 * Ações do editor nativo. Cada uma só repassa à API, com o token da sessão
 * (BFF); identidade, tenant, revisão e permissão são decididos lá. Ids
 * conferidos aqui só para não montar caminho com lixo.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
// O commit valida o documento no motor e reconstrói o índice: pode demorar.
const LONGO = 60000;

export type Falha = { ok: false; status: number; codigo: string; mensagem: string };

function falha(e: unknown): Falha {
  if (e instanceof ErroDaApi) {
    // Mensagem só quando a API a escreveu para a pessoa (recusa do dono documental).
    return { ok: false, status: e.status, codigo: e.codigo, mensagem: e.status === 422 || e.status === 409 ? e.mensagem : "" };
  }
  return { ok: false, status: 503, codigo: "API_INDISPONIVEL", mensagem: "" };
}

function conferir(...ids: string[]): Falha | null {
  return ids.every((i) => UUID.test(i)) ? null : { ok: false, status: 404, codigo: "NOT_FOUND", mensagem: "" };
}

export async function abrirSessao(
  processoId: string,
  documentoId: string,
): Promise<{ ok: true; abertura: AberturaDoEditor } | Falha> {
  const invalido = conferir(processoId, documentoId);
  if (invalido) return invalido;
  try {
    const { dados } = await chamarApi<AberturaDoEditor>(`/documentos/${documentoId}/sessoes`, {
      metodo: "POST",
      corpo: { processo_id: processoId },
      tempoMs: LONGO,
    });
    return { ok: true, abertura: dados };
  } catch (e) {
    return falha(e);
  }
}

export async function enviarEventos(documentoId: string, instanceId: string, lote: Lote): Promise<Resposta> {
  const invalido = conferir(documentoId, instanceId);
  if (invalido) return invalido;
  try {
    const { dados } = await chamarApi<EstadoDoEditor>(`/documentos/${documentoId}/sessoes/${instanceId}/eventos`, {
      metodo: "POST",
      corpo: { events: lote.events },
      tempoMs: LONGO,
    });
    return { ok: true, estado: dados };
  } catch (e) {
    return falha(e);
  }
}

async function controle(
  documentoId: string,
  instanceId: string,
  acao: "bloqueio" | "liberacao",
): Promise<{ ok: true; estado: EstadoDoEditor } | Falha> {
  const invalido = conferir(documentoId, instanceId);
  if (invalido) return invalido;
  try {
    const { dados } = await chamarApi<EstadoDoEditor>(`/documentos/${documentoId}/sessoes/${instanceId}/${acao}`, {
      metodo: "POST",
    });
    return { ok: true, estado: dados };
  } catch (e) {
    return falha(e);
  }
}

export async function bloquearParaRevisao(documentoId: string, instanceId: string) {
  return controle(documentoId, instanceId, "bloqueio");
}

export async function liberarEdicao(documentoId: string, instanceId: string) {
  return controle(documentoId, instanceId, "liberacao");
}

export async function aprovarRevisao(
  documentoId: string,
  instanceId: string,
): Promise<{ ok: true; revisao: number; status: string } | Falha> {
  const invalido = conferir(documentoId, instanceId);
  if (invalido) return invalido;
  try {
    const { dados } = await chamarApi<{ revision: number; status: string }>(
      `/documentos/${documentoId}/sessoes/${instanceId}/aprovacao`,
      { metodo: "POST", tempoMs: LONGO },
    );
    return { ok: true, revisao: dados.revision, status: dados.status };
  } catch (e) {
    return falha(e);
  }
}

export async function lerHistorico(
  processoId: string,
  documentoId: string,
): Promise<{ ok: true; revisoes: RevisaoDoHistorico[] } | Falha> {
  const invalido = conferir(processoId, documentoId);
  if (invalido) return invalido;
  try {
    const { dados } = await chamarApi<{ revisoes: RevisaoDoHistorico[] }>(
      `/documentos/${documentoId}/historico?processo_id=${processoId}`,
      { tempoMs: LONGO },
    );
    return { ok: true, revisoes: dados.revisoes };
  } catch (e) {
    return falha(e);
  }
}

export async function restaurarRevisao(
  documentoId: string,
  instanceId: string,
  revisaoOrigem: number,
): Promise<{ ok: true; abertura: AberturaDoEditor } | Falha> {
  const invalido = conferir(documentoId, instanceId);
  if (invalido) return invalido;
  if (!Number.isSafeInteger(revisaoOrigem) || revisaoOrigem < 1) {
    return { ok: false, status: 422, codigo: "VALIDATION_ERROR", mensagem: "" };
  }
  try {
    const { dados } = await chamarApi<AberturaDoEditor>(`/documentos/${documentoId}/restauracao`, {
      metodo: "POST",
      corpo: { instance_id: instanceId, revisao_origem: revisaoOrigem },
      tempoMs: LONGO,
    });
    return { ok: true, abertura: dados };
  } catch (e) {
    return falha(e);
  }
}

export async function encerrarSessao(documentoId: string, instanceId: string): Promise<void> {
  if (conferir(documentoId, instanceId)) return;
  try {
    await chamarApi(`/documentos/${documentoId}/sessoes/${instanceId}`, { metodo: "DELETE" });
  } catch {
    /* a sessão expira sozinha na API */
  }
}
