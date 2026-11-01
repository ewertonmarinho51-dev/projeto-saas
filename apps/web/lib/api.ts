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
  /** Centro de Governança disponível para quem chama (flag + papel). */
  governanca?: boolean;
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
  init: {
    metodo?: string;
    corpo?: unknown;
    // Corpo binário (planilha XLSX): vai como veio, com o tipo dele.
    corpoBruto?: { dados: ArrayBuffer; tipo: string };
    cabecalhos?: Record<string, string>;
    tempoMs?: number;
  } = {},
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
        ...(init.corpoBruto ? { "Content-Type": init.corpoBruto.tipo } : {}),
        ...init.cabecalhos,
      },
      body: init.corpoBruto ? init.corpoBruto.dados : init.corpo !== undefined ? JSON.stringify(init.corpo) : undefined,
      signal: AbortSignal.timeout(init.tempoMs ?? 8000),
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

/** O card "Confira este preço" da cesta (M10a). */
export type AlertaDePreco = {
  referencia_id: string;
  mantida: boolean;
  faixa_min: Valor | null;
  faixa_max: Valor | null;
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

/** Série de preços resumida pelo servidor (`estatistica.calcular`); tudo já formatado. */
export type ResumoDaSerie = {
  quantidade: number;
  menor: Valor;
  maior: Valor;
  media: Valor;
  mediana: Valor;
  q1: Valor;
  q3: Valor;
  amplitude: Valor;
  desvio_padrao: Valor;
  coeficiente_variacao: Valor;
  dispersao: "homogenea" | "dispersa" | "insuficiente";
  faixa_usual: { minimo: Valor; maximo: Valor } | null;
};

export type GrupoDePrecos = { rotulo: string; na_cesta: number; resumo: ResumoDaSerie };

export type EstatisticasDoItem = {
  cesta: ResumoDaSerie | null;
  coletadas: ResumoDaSerie | null;
  por_fonte: GrupoDePrecos[];
  por_uf: GrupoDePrecos[];
  pontos: {
    referencia_id: string;
    fonte: string;
    uf: string | null;
    status: string;
    valor: Valor;
    na_cesta: boolean;
    /** Critérios ("IQR", "MAD") pelos quais o preço fica longe da cesta. */
    fora_da_faixa: string[];
  }[];
  sem_valor: number;
  limite_dispersao: Valor;
};

/** O módulo aparece no menu? A API decide de verdade (404 com a flag desligada). */
export function precosHabilitado(): boolean {
  return flagLigada(process.env.PRICE_RESEARCH_ENABLED);
}

/** O GovBot aparece no menu? A API decide de verdade (404 com `GOVCONECT_GOVBOT` desligada). */
export function govbotHabilitado(): boolean {
  return flagLigada(process.env.GOVCONECT_GOVBOT);
}

export type CitacaoDoGovBot = {
  source_id: string;
  titulo: string;
  categoria: string;
  trecho: string;
  dispositivos: string[];
};

/** Uma resposta do GovBot (`POST /govbot/perguntas`): só leitura, com o trecho de cada fonte. */
export type RespostaDoGovBot = {
  resposta: string;
  acao: string;
  citacoes: CitacaoDoGovBot[];
  base: "dispensada" | "recuperado" | "suficiente" | "sem_referencias" | "falha";
  ia: boolean;
  motor_falhou: boolean;
  pendencias: string[];
};

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
  // Só exibição (0032): nome/tamanho/hash do arquivo, ou a mensagem da falha.
  resultado: {
    nome?: string;
    tamanho?: number;
    sha256?: string;
    expira_em?: string;
    registrado?: boolean;
    mensagem?: string;
    // Elaboração automática: o documento do job e o que a revisão automática achou.
    documento?: string;
    bloqueios?: number;
    avisos?: number;
  };
};

// ---------------------------------------------------------------------------
// Importação da planilha (P04e). O plano vem do SERVIDOR, com o hash que a
// confirmação devolve; o navegador só mostra.
// ---------------------------------------------------------------------------
export type PlanoDeImportacao = {
  pode_importar: boolean;
  erros: { linha: number; campo: string; valor: string; motivo: string }[];
  linhas_em_branco: number;
  resumo: { novo: number; atualizar: number; igual: number; refaz_busca: number };
  acoes: {
    numero: number;
    tipo: "novo" | "atualizar" | "igual";
    descricao: string;
    unidade: string;
    quantidade: string;
    codigo: string;
    mudancas: string[];
    refaz_busca: boolean;
  }[];
  plano: string;
  gravado: boolean;
};

// ---------------------------------------------------------------------------
// Emissão (P04d). A API decide tudo: ciência, formatos, bloqueio.
// ---------------------------------------------------------------------------
export type OpcaoDeRelatorio = { tipo: string; formato: string; rotulo: string };

export type PreparoDaEmissao = {
  disponivel: boolean;
  motivo: string;
  identificador: string;
  bloqueio: string;
  requer_ciencia: boolean;
  assinatura: string;
  alertas: { numero: number; descricao: string; valor: Valor | null; origem: string; mensagem: string }[];
  pendencias: { numero: number; descricao: string; deficiencias: string[] }[];
  ciencia: { registrada_em: string; assinatura: string } | null;
  pode_registrar_ciencia: boolean;
  opcoes: OpcaoDeRelatorio[];
  total_referencias: number;
};

/**
 * Arquivo gerado, como veio da API (o corpo não é JSON). Quem chama repassa
 * o corpo ao navegador; os cabeçalhos de tipo e nome são os da API, que os
 * tira de uma lista fechada.
 */
export async function baixarDaApi(caminho: string): Promise<Response> {
  const token = await tokenDaSessao();
  try {
    return await fetch(`${baseDaApi()}/api/v1${caminho}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(30000),
    });
  } catch {
    throw new ErroDaApi(503, "API_INDISPONIVEL", "");
  }
}

/**
 * Arquivo gerado a partir de um corpo JSON (POST). Mesma regra do
 * `baixarDaApi`: erro vira `ErroDaApi`; quem chama decide o que mostrar.
 */
export async function baixarDaApiComCorpo(caminho: string, corpo: unknown): Promise<ArrayBuffer> {
  const token = await tokenDaSessao();
  let resposta: Response;
  try {
    resposta = await fetch(`${baseDaApi()}/api/v1${caminho}`, {
      method: "POST",
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
      signal: AbortSignal.timeout(60000),
    });
  } catch {
    throw new ErroDaApi(503, "API_INDISPONIVEL", "");
  }
  if (!resposta.ok) {
    let codigo = "ERRO";
    let mensagem = "";
    try {
      const erro = (await resposta.json()) as { code?: string; message?: string };
      codigo = erro.code ?? codigo;
      mensagem = typeof erro.message === "string" ? erro.message.slice(0, 300) : "";
    } catch {
      /* corpo não-JSON */
    }
    throw new ErroDaApi(resposta.status, codigo, resposta.headers.get("x-request-id") ?? "", mensagem);
  }
  return resposta.arrayBuffer();
}

// ---------------------------------------------------------------------------
// Aplicar ao processo (P04f). Prévia primeiro, sempre (§26).
// ---------------------------------------------------------------------------
export type PreviaDaAplicacao = {
  impedimento: string;
  processo_id: string | null;
  versao_processo: string;
  valor_atual: Valor | null;
  valor_novo: Valor | null;
  mudancas: {
    posicao: number;
    descricao: string;
    unitario_atual: Valor | null;
    unitario_novo: Valor | null;
    quantidade: string | null;
    avisos: string[];
  }[];
  recusas: string[];
  documentos_a_descartar: { chave: string; nome: string }[];
};

// ---------------------------------------------------------------------------
// Formulário Matriz (M1). Os campos, rótulos e regras vêm da API, que usa
// os de `config.CAMPOS_FORMULARIO` do wizard; a planilha é recalculada no
// servidor a cada gravação.
// ---------------------------------------------------------------------------
export type CampoDoFormulario = {
  chave: string;
  tipo: "texto" | "area" | "selecao" | "planilha";
  rotulo: string;
  ajuda: string;
  exemplo: string;
  placeholder: string;
  obrigatorio: boolean;
  opcoes: string[];
};

export type ItemDaPlanilha = Record<string, string | number>;

export type Formulario = {
  campos: CampoDoFormulario[];
  valores: Record<string, string>;
  itens: ItemDaPlanilha[];
  valor_estimado: number;
  valor_estimado_exibicao: string;
  faltantes: string[];
  a_descartar: string[];
  etapa: number;
  versao: string;
};

export type FormularioGravado = Formulario & { descartados: string[]; mudou: boolean };

export type PlanilhaLida = { itens: ItemDaPlanilha[]; valor_estimado: number; valor_estimado_exibicao: string };

// ---------------------------------------------------------------------------
// Consolidar Demandas (M4). Quantidades chegam como TEXTO já formatado
// pelo domínio (Decimal): o navegador não soma.
// ---------------------------------------------------------------------------
export type Modulos = { consolidar_demandas: boolean };

export type Consolidacao = {
  arquivos: {
    nome: string;
    status: string;
    status_texto: string;
    secretaria: string;
    precisa_confirmar: boolean;
    documentos: string[];
    itens: number;
  }[];
  erros: { nome: string; mensagem: string }[];
  secretarias: string[];
  linhas: {
    codigo: string;
    descricao: string;
    unidade: string;
    por_secretaria: Record<string, string>;
    total: string;
    explicacao: string;
  }[];
  conflitos: { codigo: string; unidades: string[]; secretarias: string[]; aceito: boolean }[];
  fecha: boolean;
  divergencia: string;
  ocorrencias: number;
  duplicatas: string[];
  nao_lidos: string[];
};

export type AplicacaoDaDemanda = {
  itens: number;
  secretarias: number;
  ocorrencias: number;
  nao_lidos: string[];
  descartados: string[];
  versao: string;
};

// ---------------------------------------------------------------------------
// Administração — cadastro institucional (M7a). Só admin; o RLS da 0025
// é quem garante.
// ---------------------------------------------------------------------------
export type Opcao = { codigo: string; rotulo: string };

export type Instituicao = {
  secoes: string[];
  secretarias: { id: string; nome: string }[];
  tipos_de_portaria: Opcao[];
  funcoes_de_membro: Opcao[];
  situacoes_declaradas: string[];
};

export type ServidorInstitucional = {
  id: string;
  nome: string;
  cargo: string | null;
  matricula: string | null;
  email: string | null;
  ativo: boolean;
};

export type PortariaInstitucional = {
  id: string;
  tipo: string;
  tipo_rotulo: string;
  numero: string;
  ano: number;
  situacao: string;
  situacao_declarada: string;
  citacao: string;
  data_publicacao: string | null;
  data_inicio_vigencia: string | null;
  data_fim_vigencia: string | null;
  membros: { nome: string; funcao: string; funcao_rotulo: string; servidor_ativo: boolean }[];
};

export type ModuloInstitucional = {
  modulo: string;
  rotulo: string;
  disponivel_no_sistema: boolean;
  na_prefeitura: boolean;
  na_secretaria: string | null;
  explicacao: string;
};

export type Timbrado = {
  origem: "secretaria" | "municipio" | "nenhuma";
  cabecalho_img: string | null;
  rodape_img: string | null;
  marca_img: string | null;
  cabecalho_texto: string;
  rodape_texto: string;
  marca_texto: string;
};

// ---------------------------------------------------------------------------
// Prefeitura, Secretarias e Identidade visual (M7b, admin)
// ---------------------------------------------------------------------------
export type CampoDaPrefeitura = { chave: string; rotulo: string; exemplo: string; valor: string };
export type PrefeituraInstitucional = { nome: string; campos: CampoDaPrefeitura[] };

export type SecretariaCadastrada = {
  id: string;
  nome: string;
  sigla: string;
  ativo: boolean;
  padrao: boolean;
  identidade_propria: boolean;
};

export type IdentidadeVisual = {
  id: string;
  orgao: string;
  padrao: boolean;
  por_imagem: boolean;
  cabecalho: string;
  rodape: string;
  marca_dagua: string;
  cabecalho_img: string | null;
};

export type PreviaDoModelo = { pagina: string; cabecalho: string; rodape: string; marca: string | null };

// ---------------------------------------------------------------------------
// Centro de Governança, leitura (M8a)
// ---------------------------------------------------------------------------
export type CentroDeGovernanca = {
  papel: string;
  /** Trava de ambiente da escrita na interface nova (GOVCONECT_GOVERNANCA_ESCRITA). */
  escrita: boolean;
  abas: { tipo: string; rotulo: string; ativa: boolean }[];
  resumo: { clausulas: number; publicadas: number; em_elaboracao: number };
};

export type VersaoDeGovernanca = {
  id: string;
  versao: number;
  status: string;
  status_rotulo: string;
  hash: string;
  payload: Record<string, unknown>;
  atualizado_em: string;
  proximos: string[];
};

export type ArtefatoDeGovernanca = {
  id: string;
  chave: string;
  escopo: "plataforma" | "municipio";
  ultima: VersaoDeGovernanca | null;
  vigente: VersaoDeGovernanca | null;
  versoes: number;
  descricao: string;
};

// ---------------------------------------------------------------------------
// Usuários e papéis (M7c, admin)
// ---------------------------------------------------------------------------
export type UsuarioDoMunicipio = {
  id: string;
  nome: string;
  login: string;
  papel: string;
  ativo: boolean;
  secretaria_id: string | null;
  acesso_por_email: boolean;
  eu: boolean;
};

export type GestaoDeUsuarios = {
  usuarios: UsuarioDoMunicipio[];
  secretarias: { id: string; nome: string }[];
  gestao_de_acesso: boolean;
};

// ---------------------------------------------------------------------------
// Base de Conhecimento (M6, admin)
// ---------------------------------------------------------------------------
export type ReferenciaDaBase = {
  id: string;
  titulo: string;
  categoria: string;
  categoria_rotulo: string;
  nome_arquivo: string;
  total_chunks: number;
  criado_em: string;
};

export type BaseDeConhecimento = {
  categorias: { codigo: string; rotulo: string }[];
  extensoes: string[];
  referencias: ReferenciaDaBase[];
};

export type ReferenciaIndexada = { id: string; nome_arquivo: string; trechos: number; pendente_de_vetor: boolean };

export type TrechoRecuperado = { titulo: string; categoria_rotulo: string; similaridade: number; conteudo: string };

// ---------------------------------------------------------------------------
// WordCraft Workspace (Issue #137). O editor nativo abre por estas rotas; a
// ponte de cada canvas vive na API, e nada aqui confirma gravação.
// ---------------------------------------------------------------------------
export type DocumentoDoProcesso = {
  id: string;
  tipo: string;
  sigla: string;
  rotulo: string;
  nativo: boolean;
  legado: boolean;
  revisao: number | null;
  content_hash: string | null;
  status: string | null;
};

export type DocumentosDoProcesso = { processo_id: string; escrita: boolean; documentos: DocumentoDoProcesso[] };

export type RevisaoDoHistorico = {
  revisao: number;
  content_hash: string;
  atual: boolean;
  status: string;
  modo: string;
  restauravel: boolean;
};

export type FatoPendente = {
  id: string;
  path: string;
  valor: unknown;
  campo: string;
  confianca: number;
  inferido: boolean;
};

/** O que a aprovação exige: todo fato vigente do processo confirmado por uma pessoa. */
export type FatosDoProcesso = {
  total: number;
  confirmados: number;
  pendentes: FatoPendente[];
  invalidos: number;
  pronto: boolean;
};

export type SituacaoDoDocumento = "pendente" | "gerado" | "em_revisao" | "aprovado" | "emitido";

export type DocumentoDaElaboracao = {
  id: string;
  tipo: string;
  sigla: string;
  rotulo: string;
  situacao: SituacaoDoDocumento;
  revisao: number | null;
};

/** Em que pé está cada documento e o que fazer agora. Decidido na API, a cada leitura. */
export type Elaboracao = {
  processo_id: string;
  escrita: boolean;
  faltantes: string[];
  documentos: DocumentoDaElaboracao[];
  proximo: { acao: "formulario" | "elaborar" | "revisar" | "concluido"; tipo: string | null; sigla: string | null };
  job: Job | null;
  // O que impede aprovar o texto gerado. Só até a primeira edição salva.
  bloqueios: number;
  pendencias: string[];
};

/** Sem o editor ligado para quem chama, não há onde revisar: `null`, e a tela segue sem a elaboração. */
export async function elaboracaoDoProcesso(processoId: string): Promise<Elaboracao | null> {
  try {
    return (await chamarApi<Elaboracao>(`/processos/${processoId}/elaboracao`)).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404 && e.codigo === "MODULE_UNAVAILABLE") return null;
    throw e;
  }
}

/** Documentos que o editor abre, ou `null` quando o editor não está ligado para quem chama. */
export async function documentosDoProcesso(processoId: string): Promise<DocumentosDoProcesso | null> {
  try {
    return (await chamarApi<DocumentosDoProcesso>(`/processos/${processoId}/documentos`)).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404 && e.codigo === "MODULE_UNAVAILABLE") return null;
    throw e;
  }
}
