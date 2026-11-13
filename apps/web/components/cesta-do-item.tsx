"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useRef, useState, type ReactNode } from "react";

import { concluirItemDaRevisao, gravarMarcacao } from "@/app/app/precos/acoes";
import { Alert, Button, Field, IconButton, Textarea } from "@/design-system";
import type { ItemDePesquisa } from "@/lib/api";

import { proximoAConcluir } from "./precos";

/**
 * A cesta do item em UM clique (13/11/2026).
 *
 * Cada referência tem a marcação DESEJADA (o último clique) e a CONFIRMADA
 * (o que o servidor gravou). A tela mostra a desejada na hora; uma fila única
 * grava em segundo plano, uma referência por vez, cada uma com a revisão que a
 * anterior devolveu (If-Match) — cliques em várias linhas não colidem, e
 * cliques repetidos na mesma linha valem pelo último. Se a gravação falha, só
 * a linha afetada volta ao que estava, com um aviso curto.
 *
 * Quem usa põe `key={revisao do item}`: quando o servidor manda uma página
 * nova (refresh depois da fila), o provedor nasce de novo com a verdade dele.
 */
type Fila = {
  marcado: (id: string, padrao: boolean) => boolean;
  salvando: (id: string) => boolean;
  alternar: (id: string, atual: boolean) => void;
  /** Resolve quando não há nada por gravar; `falhou` = alguma gravação recusada. */
  aguardar: () => Promise<{ revisao: number; falhou: boolean }>;
  preco: string | null;
  aviso: string | null;
};

const ContextoDaCesta = createContext<Fila | null>(null);

export function useCestaDoItem(): Fila | null {
  return useContext(ContextoDaCesta);
}

type Marcas = Record<string, boolean>;

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
  // o que a TELA mostra (estado) …
  const [desejadoV, setDesejadoV] = useState<Marcas>(marcadas);
  const [confirmadoV, setConfirmadoV] = useState<Marcas>(marcadas);
  const [emVooV, setEmVooV] = useState<string | null>(null);
  const [preco, setPreco] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  // … e o que a fila assíncrona lê e escreve (refs, nunca lidas no desenho)
  const desejado = useRef<Marcas>({ ...marcadas });
  const confirmado = useRef<Marcas>({ ...marcadas });
  const revisaoAtual = useRef(revisao);
  const rodando = useRef(false);
  const falhou = useRef(false);
  const esperando = useRef<((r: { revisao: number; falhou: boolean }) => void)[]>([]);

  function publicar() {
    setDesejadoV({ ...desejado.current });
    setConfirmadoV({ ...confirmado.current });
  }

  function pendentes(): [string, boolean][] {
    return Object.entries(desejado.current).filter(([id, v]) => confirmado.current[id] !== v);
  }

  async function processar() {
    if (rodando.current) return;
    rodando.current = true;
    falhou.current = false;
    let gravou = false;
    try {
      for (;;) {
        const proxima = pendentes()[0];
        if (!proxima) break;
        const [id, incluir] = proxima;
        setEmVooV(id);
        const r = await gravarMarcacao(pesquisa, item, id, incluir, revisaoAtual.current);
        if (r.ok) {
          confirmado.current[id] = incluir;
          revisaoAtual.current = r.revisao;
          setPreco(r.preco);
          gravou = true;
        } else {
          // só esta linha volta; as outras marcações seguem na fila
          falhou.current = true;
          desejado.current[id] = confirmado.current[id] ?? false;
          setAviso(r.erro);
          if (r.conflito) {
            // outra aba mexeu: descarta a fila e relê do servidor
            desejado.current = { ...confirmado.current };
          }
        }
        publicar();
        if (!r.ok && r.conflito) break;
      }
    } finally {
      rodando.current = false;
      setEmVooV(null);
      const resultado = { revisao: revisaoAtual.current, falhou: falhou.current };
      esperando.current.splice(0).forEach((f) => f(resultado));
      if (gravou || falhou.current) router.refresh();
    }
  }

  const fila: Fila = {
    marcado: (id, padrao) => desejadoV[id] ?? padrao,
    salvando: (id) => emVooV === id || (id in desejadoV && desejadoV[id] !== confirmadoV[id]),
    alternar: (id, atual) => {
      if (!(id in confirmado.current)) confirmado.current[id] = atual;
      desejado.current[id] = !(desejado.current[id] ?? atual);
      setAviso(null);
      publicar();
      void processar();
    },
    aguardar: () => {
      if (!rodando.current && pendentes().length === 0) {
        return Promise.resolve({ revisao: revisaoAtual.current, falhou: false });
      }
      const promessa = new Promise<{ revisao: number; falhou: boolean }>((resolver) =>
        esperando.current.push(resolver),
      );
      void processar();
      return promessa;
    },
    preco,
    aviso,
  };

  return <ContextoDaCesta.Provider value={fila}>{children}</ContextoDaCesta.Provider>;
}

/** O controle da cesta de UMA referência: seta fora, check dentro. */
export function ControleDaCesta({ referencia, naCesta }: { referencia: string; naCesta: boolean }) {
  const fila = useCestaDoItem();
  if (!fila) return null;
  const dentro = fila.marcado(referencia, naCesta);
  return (
    <IconButton
      icon={dentro ? "check-circle" : "arrow-right"}
      label={dentro ? "Retirar da cesta" : "Incluir na cesta"}
      variant={dentro ? "primary" : "secondary"}
      aria-pressed={dentro}
      aria-busy={fila.salvando(referencia) || undefined}
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
    <Alert variant="warning" compact>
      <span role="status" data-testid="aviso-cesta">
        {fila.aviso}
      </span>
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

/** Quantas estão na cesta pela marcação que a tela mostra (atualiza no clique). */
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
