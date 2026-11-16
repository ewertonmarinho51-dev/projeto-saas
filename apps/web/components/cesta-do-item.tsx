"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { concluirItemDaRevisao, gravarMarcacao } from "@/app/app/precos/acoes";
import { Alert, Button, Field, IconButton, Textarea } from "@/design-system";
import type { ItemDePesquisa } from "@/lib/api";

import { FilaDaCesta, type Marcas } from "./fila-da-cesta";
import { proximoAConcluir } from "./precos";

/**
 * A cesta do item em UM clique (13/11/2026; P0 de 14/11/2026).
 *
 * Cada referência tem a marcação DESEJADA (o último clique) e a CONFIRMADA
 * (o que o servidor gravou). A tela sinaliza a gravação pendente e só mostra
 * a seleção confirmada; uma fila única
 * (`FilaDaCesta`) grava em segundo plano, uma referência por vez, cada uma
 * com a revisão que a anterior devolveu (If-Match). Uma recusa mantém a
 * seleção confirmada e exibe o motivo.
 *
 * Quem usa põe `key={id do item}` — NUNCA a revisão. A página que o refresh
 * traz entra pela reconciliação da fila (`receberDoServidor`): instantâneo
 * mais velho que a revisão confirmada é ignorado; o mais novo é adotado. Com
 * a revisão na `key`, o provedor nascia de novo a cada gravação e a cesta
 * "perdia" o clique seguinte (P0, ver `fila-da-cesta.ts`).
 */
type Fila = {
  marcado: (id: string, padrao: boolean) => boolean;
  salvando: (id: string) => boolean;
  alternar: (id: string, atual: boolean) => void;
  /** Resolve quando não há nada por gravar; `falhou` = alguma gravação recusada. */
  aguardar: () => Promise<{ revisao: number; falhou: boolean }>;
  preco: string | null;
  aviso: string | null;
  referenciaDoAviso: string | null;
};

const ContextoDaCesta = createContext<Fila | null>(null);

export function useCestaDoItem(): Fila | null {
  return useContext(ContextoDaCesta);
}

/** Assinatura estável das marcações do servidor (a ordem das chaves não conta). */
function assinatura(marcadas: Marcas): string {
  return Object.keys(marcadas)
    .sort()
    .map((id) => `${id}:${marcadas[id] ? 1 : 0}`)
    .join(",");
}

export function CestaDoItem({
  pesquisa,
  item,
  revisao,
  marcadas,
  children,
}: {
  pesquisa: string;
  item: string;
  revisao: number;
  /** id → está na cesta, como o servidor mandou. */
  marcadas: Marcas;
  children: ReactNode;
}) {
  const router = useRouter();
  // Uma fila por item, viva enquanto a página do item estiver aberta.
  const [maquina] = useState(
    () =>
      new FilaDaCesta(
        revisao,
        marcadas,
        async (referencia, incluir, rev) => {
          const r = await gravarMarcacao(pesquisa, item, referencia, incluir, rev);
          return r.ok ? { ok: true, revisao: r.revisao, preco: r.preco } : r;
        },
        () => router.refresh(),
      ),
  );
  const estado = useSyncExternalStore(maquina.assinar, maquina.estado, maquina.estado);

  // A página que o servidor manda (refresh, outra aba) entra pela revisão.
  const chave = assinatura(marcadas);
  const ultima = useRef<string>(`${revisao}|${chave}`);
  useEffect(() => {
    const atual = `${revisao}|${chave}`;
    if (ultima.current === atual) return;
    ultima.current = atual;
    maquina.receberDoServidor(revisao, marcadas);
    // `marcadas` muda de identidade a cada renderização; a assinatura é o que conta
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maquina, revisao, chave]);

  const fila: Fila = {
    marcado: (id, padrao) => estado.confirmado[id] ?? padrao,
    salvando: (id) => estado.emVoo === id || (id in estado.desejado && estado.desejado[id] !== estado.confirmado[id]),
    alternar: (id, atual) => maquina.alternar(id, atual),
    aguardar: () => maquina.aguardar(),
    preco: estado.preco,
    aviso: estado.aviso,
    referenciaDoAviso: estado.referenciaDoAviso,
  };

  return <ContextoDaCesta.Provider value={fila}>{children}</ContextoDaCesta.Provider>;
}

/** O controle da cesta de UMA referência: seta fora, check dentro. */
export function ControleDaCesta({ referencia, naCesta }: { referencia: string; naCesta: boolean }) {
  const fila = useCestaDoItem();
  if (!fila) return null;
  const dentro = fila.marcado(referencia, naCesta);
  const salvando = fila.salvando(referencia);
  return (
    <IconButton
      icon={salvando ? "clock" : dentro ? "check-circle" : "arrow-right"}
      label={salvando ? "Gravando alteração na cesta" : dentro ? "Retirar da cesta" : "Incluir na cesta"}
      variant={dentro ? "primary" : "secondary"}
      aria-pressed={dentro}
      aria-busy={salvando || undefined}
      data-testid="controle-cesta"
      data-na-cesta={dentro ? "1" : "0"}
      onClick={() => fila.alternar(referencia, naCesta)}
    />
  );
}

/** Aviso curto de gravação recusada, perto da lista. */
export function AvisoDaCesta() {
  const fila = useCestaDoItem();
  if (!fila?.aviso) return null;
  return (
    <Alert variant="warning" role="alert" compact>
      <span data-testid="aviso-cesta">{fila.aviso}</span>
    </Alert>
  );
}

/**
 * O preço que o servidor confirmou por último (ou o da página). A página o
 * mostra duas vezes (resumo e cartão da cesta); só a do resumo leva o
 * `data-testid`, para a prova achar um elemento só.
 */
export function PrecoConfirmado({ inicial, principal = true }: { inicial: string; principal?: boolean }) {
  const fila = useCestaDoItem();
  return <span data-testid={principal ? "preco-do-item" : undefined}>{fila?.preco ?? inicial}</span>;
}

/** Quantas referências têm inclusão confirmada. */
export function ContagemNaCesta({ marcadas }: { marcadas: Marcas }) {
  const fila = useCestaDoItem();
  const n = Object.entries(marcadas).filter(([id, v]) => (fila ? fila.marcado(id, v) : v)).length;
  return <span data-testid="contagem-cesta">{n}</span>;
}

/**
 * "Concluir item e avançar": espera a fila gravar, conclui com a revisão
 * confirmada (o domínio grava a cesta e o valor pelo método vigente) e só
 * então abre o próximo item a concluir — ou o resumo, se era o último.
 * Falha ou impedimento: fica no item, com o motivo ao lado do botão.
 */
export function ConcluirEAvancar({
  pesquisa,
  item,
  itens,
}: {
  pesquisa: string;
  item: string;
  itens: Pick<ItemDePesquisa, "id" | "numero" | "estado">[];
}) {
  const router = useRouter();
  const fila = useCestaDoItem();
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [justificativa, setJustificativa] = useState("");

  async function concluir() {
    setEnviando(true);
    setErro(null);
    try {
      const salvo = fila ? await fila.aguardar() : null;
      if (!salvo) {
        setErro("Recarregue a página e tente de novo.");
        return;
      }
      if (salvo.falhou) {
        setErro("Alguma marcação não foi gravada. Confira a cesta e tente de novo.");
        return;
      }
      const r = await concluirItemDaRevisao(pesquisa, item, salvo.revisao, justificativa);
      if (!r.ok) {
        setErro(r.erro);
        return;
      }
      const proximo = proximoAConcluir(itens, item);
      router.push(proximo ? `/app/precos/${pesquisa}/itens/${proximo}` : `/app/precos/${pesquisa}?item=concluido`);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="grid gap-3" data-testid="concluir-e-avancar">
      <Field
        label="Justificativa"
        htmlFor={`justificativa-${item}`}
        optional
        help="Só é exigida quando o item tem pendência de análise crítica."
      >
        <Textarea
          id={`justificativa-${item}`}
          rows={2}
          maxLength={2000}
          value={justificativa}
          onChange={(e) => setJustificativa(e.target.value)}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={concluir} loading={enviando} icon="check-circle">
          Concluir item e avançar
        </Button>
        {erro && (
          <span role="alert" className="text-[length:var(--gc-fs-sm)] text-erro" data-testid="erro-concluir">
            {erro}
          </span>
        )}
      </div>
    </div>
  );
}
