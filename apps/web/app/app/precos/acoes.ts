"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { chamarApi, ErroDaApi, type PlanoDeImportacao } from "@/lib/api";

export type EstadoDaCesta = { erro: string | null };

const UUID = /^[0-9a-f-]{36}$/i;

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Você não tem permissão para alterar esta cesta.",
  404: "Referência não encontrada nesta pesquisa.",
  409: "Esta cesta mudou depois que você abriu a página (outra aba ou outra pessoa). Recarregue e refaça.",
  429: "Muitas requisições. Aguarde um instante.",
};

/**
 * Pôr ou tirar UMA referência. A regra (motivo obrigatório só para pôr,
 * reinclusão sinalizada, trilha) é do domínio; a mensagem dele volta como
 * veio quando ele recusa (422).
 */
export async function alterarCesta(_: EstadoDaCesta, form: FormData): Promise<EstadoDaCesta> {
  const pesquisa = String(form.get("pesquisa") ?? "");
  const item = String(form.get("item") ?? "");
  const referencia = String(form.get("referencia") ?? "");
  const revisao = String(form.get("revisao") ?? "");
  if (![pesquisa, item, referencia].every((v) => UUID.test(v)) || !/^\d+$/.test(revisao)) {
    return { erro: "Requisição inválida." };
  }
  const incluir = form.get("incluir") === "1";
  const motivo = String(form.get("motivo") ?? "").trim();
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/itens/${item}/referencias/${referencia}`, {
      metodo: "PATCH",
      corpo: { incluir, ...(motivo ? { motivo } : {}) },
      cabecalhos: { "If-Match": `"${revisao}"` },
    });
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 422) {
      return { erro: e.mensagem || "A regra da cesta recusou esta mudança." };
    }
    return {
      erro: e instanceof ErroDaApi ? (MENSAGENS[e.status] ?? "Não foi possível alterar agora.") : "Não foi possível alterar agora.",
    };
  }
  const caminho = `/app/precos/${pesquisa}/itens/${item}`;
  revalidatePath(caminho);
  redirect(`${caminho}?cesta=${incluir ? "incluida" : `retirada&ref=${referencia}`}`);
}

export type EstadoDaColeta = { erro: string | null };

const ERROS_DA_COLETA: Record<string, string> = {
  QUEUE_UNAVAILABLE: "A coleta está indisponível no momento. Tente de novo em instantes.",
  FORBIDDEN: "Só quem criou a pesquisa (ou o administrador) pode iniciar a coleta.",
};

/** Põe a coleta na fila e volta à pesquisa acompanhando o job. */
export async function iniciarColeta(_: EstadoDaColeta, form: FormData): Promise<EstadoDaColeta> {
  const pesquisa = String(form.get("pesquisa") ?? "");
  const modo = form.get("modo") === "automatico" ? "automatico" : "manual";
  // Uma chave por modo: os dois botões da mesma tela não colidem.
  const chave = `${String(form.get("chave") ?? "")}-${modo}`;
  if (!UUID.test(pesquisa) || !/^[A-Za-z0-9._:-]{8,128}$/.test(chave)) return { erro: "Requisição inválida." };
  let jobId: string;
  try {
    const { dados } = await chamarApi<{ id: string }>(`/precos/pesquisas/${pesquisa}/coleta`, {
      metodo: "POST",
      corpo: { modo },
      cabecalhos: { "Idempotency-Key": chave },
    });
    jobId = dados.id;
  } catch (e) {
    if (e instanceof ErroDaApi) return { erro: ERROS_DA_COLETA[e.codigo] ?? MENSAGENS[e.status] ?? "Não foi possível iniciar a coleta." };
    return { erro: "Não foi possível iniciar a coleta." };
  }
  redirect(`/app/precos/${pesquisa}?job=${jobId}`);
}

export type EstadoDaEmissao = { erro: string | null };

const ERROS_DA_EMISSAO: Record<string, string> = {
  CIENCIA_DESATUALIZADA: "A cesta mudou desde o aviso. Recarregue a página para conferir os alertas atualizados.",
  EMISSION_UNAVAILABLE: "A emissão pela nova interface está desligada. Emita pelo aplicativo de sempre.",
  QUEUE_UNAVAILABLE: "A emissão está indisponível no momento. Tente de novo em instantes.",
  FORBIDDEN: "Só quem criou a pesquisa (ou o administrador) pode confirmar a ciência dos alertas.",
};

/**
 * "Estou ciente" (quando a cesta pede) e o pedido do relatório, num envio
 * só. A ciência vai com a ASSINATURA que a pessoa viu: se a cesta mudou
 * desde o aviso, a API recusa (409) e nada é gerado. O worker confere a
 * ciência de novo na hora de gerar.
 */
export async function emitirRelatorio(_: EstadoDaEmissao, form: FormData): Promise<EstadoDaEmissao> {
  const pesquisa = String(form.get("pesquisa") ?? "");
  // O botão clicado manda "tipo:formato".
  const [tipo = "", formato = ""] = String(form.get("opcao") ?? "").split(":");
  const assinatura = String(form.get("assinatura") ?? "");
  // Uma chave por renderização e por relatório: o mesmo botão clicado duas
  // vezes devolve o mesmo job; outro relatório da mesma tela é outro job.
  const chave = `${String(form.get("chave") ?? "")}-${tipo}-${formato}`;
  if (
    !UUID.test(pesquisa) ||
    !/^[a-z_]{3,30}$/.test(tipo) ||
    !/^(pdf|docx|xlsx|zip)$/.test(formato) ||
    !/^[A-Za-z0-9._:-]{8,128}$/.test(chave) ||
    (assinatura !== "" && !/^[0-9a-f]{64}$/.test(assinatura))
  ) {
    return { erro: "Requisição inválida." };
  }
  let jobId: string;
  try {
    if (assinatura) {
      await chamarApi(`/precos/pesquisas/${pesquisa}/ciencia`, { metodo: "POST", corpo: { assinatura } });
    }
    const { dados } = await chamarApi<{ id: string }>(`/precos/pesquisas/${pesquisa}/relatorios`, {
      metodo: "POST",
      corpo: { tipo, formato },
      cabecalhos: { "Idempotency-Key": chave },
    });
    jobId = dados.id;
  } catch (e) {
    if (e instanceof ErroDaApi) return { erro: ERROS_DA_EMISSAO[e.codigo] ?? MENSAGENS[e.status] ?? "Não foi possível pedir o relatório." };
    return { erro: "Não foi possível pedir o relatório." };
  }
  revalidatePath(`/app/precos/${pesquisa}`);
  redirect(`/app/precos/${pesquisa}?relatorio=${jobId}`);
}

// ---------------------------------------------------------------------------
// P04e: criar pesquisa, importar planilha, concluir e reabrir item.
// ---------------------------------------------------------------------------
export type EstadoDaCriacao = { erro: string | null };

const DATA = /^\d{4}-\d{2}-\d{2}$/;

/** Nova pesquisa; a chave da renderização evita duas com o duplo clique. */
export async function criarPesquisa(_: EstadoDaCriacao, form: FormData): Promise<EstadoDaCriacao> {
  const texto = (nome: string, max: number) => String(form.get(nome) ?? "").trim().slice(0, max);
  const nome = texto("nome", 200);
  const chave = String(form.get("chave") ?? "");
  const dataBase = texto("data_base", 10);
  if (!nome) return { erro: "Dê um nome à pesquisa." };
  if (!/^[A-Za-z0-9._:-]{8,128}$/.test(chave) || (dataBase && !DATA.test(dataBase))) {
    return { erro: "Requisição inválida." };
  }
  let id: string;
  try {
    const { dados } = await chamarApi<{ id: string }>("/precos/pesquisas", {
      metodo: "POST",
      corpo: {
        nome,
        objeto: texto("objeto", 2000),
        responsavel: texto("responsavel", 200),
        local_referencia: texto("local_referencia", 200),
        ...(dataBase ? { data_base: dataBase } : {}),
      },
      cabecalhos: { "Idempotency-Key": chave },
    });
    id = dados.id;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 422) return { erro: e.mensagem || "Confira os campos." };
    return { erro: e instanceof ErroDaApi ? (MENSAGENS[e.status] ?? "Não foi possível criar agora.") : "Não foi possível criar agora." };
  }
  revalidatePath("/app/precos");
  redirect(`/app/precos/${id}?criada=1`);
}

export type EstadoDaImportacao = { erro: string | null; plano: PlanoDeImportacao | null };

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/**
 * Conferir (sem `plano`) ou confirmar (com o `plano` que a pessoa viu). Nos
 * dois casos o arquivo vai inteiro e o SERVIDOR refaz o plano; se a cotação
 * mudou no meio, a confirmação é recusada e o plano novo aparece.
 */
export async function importarPlanilha(_: EstadoDaImportacao, form: FormData): Promise<EstadoDaImportacao> {
  const pesquisa = String(form.get("pesquisa") ?? "");
  const plano = String(form.get("plano") ?? "");
  const arquivo = form.get("planilha");
  if (!UUID.test(pesquisa) || (plano && !/^[0-9a-f]{64}$/.test(plano))) return { erro: "Requisição inválida.", plano: null };
  if (!(arquivo instanceof File) || arquivo.size === 0) return { erro: "Escolha a planilha (XLSX).", plano: null };
  if (arquivo.size > 5 * 1024 * 1024) return { erro: "A planilha passa de 5 MB. Divida o arquivo.", plano: null };
  try {
    const { dados } = await chamarApi<PlanoDeImportacao>(
      `/precos/pesquisas/${pesquisa}/importacao${plano ? "?confirmar=true" : ""}`,
      {
        metodo: "POST",
        corpoBruto: { dados: await arquivo.arrayBuffer(), tipo: XLSX },
        cabecalhos: plano ? { "If-Match": `"${plano}"` } : {},
        tempoMs: 30000,
      },
    );
    if (dados.gravado) {
      revalidatePath(`/app/precos/${pesquisa}`);
      redirect(`/app/precos/${pesquisa}?importada=1`);
    }
    return { erro: null, plano: dados };
  } catch (e) {
    if (e instanceof ErroDaApi) {
      const porCodigo: Record<string, string> = {
        PLANO_DESATUALIZADO: "A cotação mudou desde a conferência. Confira o plano de novo.",
        UNSUPPORTED_MEDIA_TYPE: "O arquivo não é uma planilha XLSX legível.",
        PAYLOAD_TOO_LARGE: "A planilha passa de 5 MB. Divida o arquivo.",
        SPREADSHEET_ERRORS: "A planilha tem erros; corrija e confira de novo.",
        FORBIDDEN: "Só quem criou a pesquisa (ou o administrador) pode importar itens.",
        IMMUTABLE: "Pesquisa aplicada ou arquivada não recebe itens.",
      };
      return { erro: porCodigo[e.codigo] ?? MENSAGENS[e.status] ?? "Não foi possível importar agora.", plano: null };
    }
    throw e; // o redirect do Next passa por aqui e precisa seguir
  }
}

export type EstadoDoItem = { erro: string | null };

const ERROS_DO_ITEM: Record<string, string> = {
  FORBIDDEN: "Só quem criou a pesquisa (ou o administrador) pode concluir ou reabrir itens.",
  VERSION_CONFLICT: "O item mudou desde que você abriu a página. Recarregue e refaça.",
  IMMUTABLE: "Pesquisa aplicada ou arquivada: crie uma revisão nova.",
};

async function atoNoItem(form: FormData, ato: "conclusao" | "reabertura"): Promise<EstadoDoItem> {
  const pesquisa = String(form.get("pesquisa") ?? "");
  const item = String(form.get("item") ?? "");
  const revisao = String(form.get("revisao") ?? "");
  if (![pesquisa, item].every((v) => UUID.test(v)) || !/^\d+$/.test(revisao)) return { erro: "Requisição inválida." };
  const texto = String(form.get("texto") ?? "").trim().slice(0, 2000);
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/itens/${item}/${ato}`, {
      metodo: "POST",
      corpo: ato === "conclusao" ? { justificativa: texto } : { motivo: texto },
      cabecalhos: ato === "conclusao" ? { "If-Match": `"${revisao}"` } : {},
    });
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 422) return { erro: e.mensagem || "A regra do item recusou." };
    if (e instanceof ErroDaApi) return { erro: ERROS_DO_ITEM[e.codigo] ?? MENSAGENS[e.status] ?? "Não foi possível agora." };
    return { erro: "Não foi possível agora." };
  }
  const caminho = `/app/precos/${pesquisa}/itens/${item}`;
  revalidatePath(caminho);
  redirect(`${caminho}?item=${ato === "conclusao" ? "concluido" : "reaberto"}`);
}

export async function concluirItem(_: EstadoDoItem, form: FormData) {
  return atoNoItem(form, "conclusao");
}

export async function reabrirItem(_: EstadoDoItem, form: FormData) {
  return atoNoItem(form, "reabertura");
}

export type EstadoDaAplicacao = { erro: string | null };

const ERROS_DA_APLICACAO: Record<string, string> = {
  VERSION_CONFLICT: "O processo mudou desde a prévia (alguém salvou no meio). Recarregue e confira de novo.",
  CONFIRMAR_DESCARTE: "Confirme que os documentos listados serão descartados.",
  FORBIDDEN: "Só quem é responsável pela pesquisa e pelo processo (ou o administrador) pode aplicar.",
  NADA_A_APLICAR: "Nenhum item da planilha do processo casou com a pesquisa.",
};

/** Aplica com a versão do processo que a pessoa viu na prévia (compare-and-set). */
export async function aplicarAoProcesso(_: EstadoDaAplicacao, form: FormData): Promise<EstadoDaAplicacao> {
  const pesquisa = String(form.get("pesquisa") ?? "");
  const versao = String(form.get("versao") ?? "");
  if (!UUID.test(pesquisa) || !/^[0-9T:.+\- ]{10,40}$/.test(versao)) return { erro: "Requisição inválida." };
  let processo: string;
  try {
    const { dados } = await chamarApi<{ processo_id: string }>(`/precos/pesquisas/${pesquisa}/aplicacao`, {
      metodo: "POST",
      corpo: { confirmo_descarte: form.get("confirmo") === "1" },
      cabecalhos: { "If-Match": `"${versao}"` },
      tempoMs: 30000,
    });
    processo = dados.processo_id;
  } catch (e) {
    if (e instanceof ErroDaApi && e.codigo === "APLICACAO_IMPEDIDA") return { erro: e.mensagem || "A aplicação está impedida." };
    if (e instanceof ErroDaApi) return { erro: ERROS_DA_APLICACAO[e.codigo] ?? MENSAGENS[e.status] ?? "Não foi possível aplicar agora." };
    return { erro: "Não foi possível aplicar agora." };
  }
  revalidatePath(`/app/precos/${pesquisa}`);
  revalidatePath(`/app/processos/${processo}`);
  redirect(`/app/precos/${pesquisa}?aplicada=1`);
}
