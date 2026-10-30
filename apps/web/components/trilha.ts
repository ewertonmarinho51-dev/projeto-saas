import type { BreadcrumbItem } from "@/design-system";

/**
 * Trilha da casca e detecção do modo de trabalho, a partir da rota.
 * Módulo puro (sem React nem servidor): a casca usa, as provas importam.
 */

/** Nome de cada trecho fixo da rota; trecho variável (id) vira o nome genérico do recurso. */
const TRECHOS: Record<string, string> = {
  processos: "Processos",
  formulario: "Dados da demanda",
  demandas: "Consolidar demandas",
  precos: "Preços",
  nova: "Nova pesquisa",
  itens: "Itens",
  admin: "Administração",
  instituicao: "Instituição",
  "base-conhecimento": "Base de Conhecimento",
  usuarios: "Usuários",
  governanca: "Governança",
  conta: "Conta",
  senha: "Senha",
  documentos: "Documentos",
  editar: "Editar documento",
};

const RECURSO: Record<string, string> = { processos: "Processo", precos: "Pesquisa", itens: "Item", documentos: "Documento" };

/** Editor de documento: a casca entra em modo de trabalho (tela inteira, barra lateral recolhida). */
export function emEditor(caminho: string): boolean {
  return /^\/app\/processos\/[^/]+\/documentos\/[^/]+\/editar\/?$/.test(caminho);
}

/** Trilha a partir da rota. Sem link para trecho que não é página (Administração, Conta, Itens). */
export function trilha(caminho: string): BreadcrumbItem[] {
  const partes = caminho.replace(/^\/app\/?/, "").split("/").filter(Boolean);
  if (partes.length === 0) return [{ label: "Início" }];
  const itens: BreadcrumbItem[] = [];
  let href = "/app";
  partes.forEach((parte, i) => {
    href += `/${parte}`;
    const anterior = partes[i - 1];
    const label = TRECHOS[parte] ?? (anterior && RECURSO[anterior]) ?? parte;
    const pagina = !["admin", "conta", "itens", "documentos"].includes(parte) && anterior !== "documentos";
    itens.push(pagina ? { label, href } : { label });
  });
  // "Itens" e "Documentos" ficam de fora: a trilha vai do pai direto ao item.
  return itens.filter((i) => i.label !== "Itens" && i.label !== "Documentos");
}
