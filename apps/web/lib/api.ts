import "server-only";

import { flagLigada } from "@/lib/seguranca";
import { criarClienteServidor } from "@/lib/supabase/server";

/**
 * BFF: o servidor do web chama a API do Gov Conect com o token da sessão.
 *
 * O navegador nunca fala com a API direto — a URL da API é variável de
 * servidor (`GOVCONECT_API_URL`, sem `NEXT_PUBLIC_`), e o token sai do
 * cookie da sessão no servidor. A API verifica o token sozinha (assinatura,
 * vínculo, tenant); este arquivo não decide autorização nenhuma.
 *
 * `cache: "no-store"` em tudo: resposta de um município nunca vira cache
 * compartilhado.
 */

export type Identidade = {
  auth_user_id: string;
  tenant_id: string;
  papel: "admin" | "usuario";
  secretaria_id: string | null;
};

export type Processo = {
  id: string;
  nome: string;
  nome_exibido: string;
  orgao: string;
  objeto: string;
  status: string;
  etapa: string;
  progresso: { feitos: number; total: number };
  criado_em: string;
  atualizado_em: string;
  versao: string;
};

export type Pagina<T> = { itens: T[]; proximo_cursor: string | null };

export class ErroDaApi extends Error {
  constructor(
    readonly status: number,
    readonly codigo: string,
    readonly requestId: string,
    // `message` do envelope da API. Só é mostrada ao usuário quando a API
    // a escreveu para ele (422 de regra do domínio); o resto vira texto fixo.
    readonly mensagem: string = "",
  ) {
    super(codigo);
  }
}

function baseDaApi(): string {
  const base = process.env.GOVCONECT_API_URL;
  if (!base) throw new ErroDaApi(503, "API_NAO_CONFIGURADA", "");
  return base.replace(/\/$/, "");
}

async function tokenDaSessao(): Promise<string> {
  const supabase = await criarClienteServidor();
  // getClaims() primeiro: só repassa token cuja assinatura conferiu aqui.
  const { data: verificado } = await supabase.auth.getClaims();
  if (!verificado?.claims) throw new ErroDaApi(401, "UNAUTHENTICATED", "");
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ErroDaApi(401, "UNAUTHENTICATED", "");
  return token;
}

export async function chamarApi<T>(
  caminho: string,
  init: { metodo?: string; corpo?: unknown; cabecalhos?: Record<string, string> } = {},
): Promise<{ dados: T; cabecalhos: Headers }> {
  const token = await tokenDaSessao();
  let resposta: Response;
  try {
    resposta = await fetch(`${baseDaApi()}/api/v1${caminho}`, {
      method: init.metodo ?? "GET",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        ...(init.corpo !== undefined ? { "Content-Type": "application/json" } : {}),
        ...init.cabecalhos,
      },
      body: init.corpo !== undefined ? JSON.stringify(init.corpo) : undefined,
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    throw new ErroDaApi(503, "API_INDISPONIVEL", "");
  }
  const requestId = resposta.headers.get("x-request-id") ?? "";
  if (!resposta.ok) {
    let codigo = "ERRO";
    let mensagem = "";
    try {
      const corpo = (await resposta.json()) as { code?: string; message?: string };
      codigo = corpo.code ?? codigo;
      mensagem = typeof corpo.message === "string" ? corpo.message.slice(0, 300) : "";
    } catch {
      /* corpo não-JSON: fica o código genérico */
    }
    throw new ErroDaApi(resposta.status, codigo, requestId, mensagem);
  }
  return { dados: (await resposta.json()) as T, cabecalhos: resposta.headers };
}

// ---------------------------------------------------------------------------
// Pesquisa de preços (P04a, leitura). Dinheiro chega como STRING já
// formatada pelo domínio (`exibicao`); o navegador nunca soma nem
// arredonda — não existe `Number()` sobre valor monetário neste app.
// ---------------------------------------------------------------------------
export type Valor = { valor: string; exibicao: string };

export type ResumoPesquisa = {
  id: string;
  nome: string;
  objeto: string;
  estado: string;
  valor_global: Valor | null;
  atualizado_em: string;
};

export type ItemDePesquisa = {
  id: string;
  numero: number;
  codigo: string | null;
  tipo_catalogo: string | null;
  descricao: string;
  unidade: string;
  quantidade: Valor | null;
  estado: string;
  metodo: string | null;
  preco_estimado: Valor | null;
  preco_total: Valor | null;
  justificativa: string;
  lote: string | null;
  uf: string | null;
  revisao: number;
};

export type PesquisaDePrecos = ResumoPesquisa & {
  data_base: string | null;
  responsavel: string;
  local_referencia: string;
  processo_id: string | null;
  versao: number;
  criado_em: string;
  itens: ItemDePesquisa[];
};

export type ReferenciaDePreco = {
  id: string;
  fonte: string;
  fonte_tipo: string;
  natureza_valor: string;
  status: string;
  descricao_original: string;
  unidade_original: string | null;
  valor_unitario_original: Valor | null;
  unidade_normalizada: string | null;
  valor_unitario_normalizado: Valor | null;
  orgao: string | null;
  uf: string | null;
  municipio: string | null;
  fornecedor: string | null;
  data_compra: string | null;
  data_resultado: string | null;
  coletado_em: string;
  motivos: string[];
  link_contratacao: string | null;
  rotulo_contratacao: string;
  link_fonte: string | null;
  identificacao: string;
};

/** O módulo aparece no menu? A API decide de verdade (404 com a flag desligada). */
export function precosHabilitado(): boolean {
  return flagLigada(process.env.PRICE_RESEARCH_ENABLED);
}

export type Job = {
  id: string;
  tipo: string;
  recurso_id: string;
  estado: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  feitos: number;
  total: number;
  progresso: number;
  erro_codigo: string;
  criado_em: string;
  iniciado_em: string | null;
  concluido_em: string | null;
};
