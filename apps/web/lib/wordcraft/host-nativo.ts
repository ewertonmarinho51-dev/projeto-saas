import { HOST_URL } from "./host";

/**
 * Monta o host nativo (`host.mjs`, servido como estático com hash no nome)
 * num elemento da página, no lugar do componente v2 do Streamlit.
 *
 * O host cria o canvas com altura fixa (720 px, herança do Streamlit). Aqui
 * o canvas passa a ocupar o espaço que a tela der: um ResizeObserver no
 * contêiner mede a área útil e grava largura e altura em px CSS alinhados à
 * grade de pixels do aparelho (devicePixelRatio), para o eframe/WASM
 * redimensionar o buffer sem borrar nem cortar. Zoom do navegador muda o
 * DPR: o ajuste roda de novo. Nada disso recria a instância nativa — a
 * seleção, o Undo e a sessão continuam onde estavam.
 */

type ModuloDoHost = {
  default: (componente: {
    data: Record<string, unknown>;
    parentElement: HTMLElement;
    setStateValue: (chave: string, valor: unknown) => void;
  }) => (() => void) | void;
};

export type HostMontado = {
  atualizar: (dados: Record<string, unknown>) => void;
  desmontar: () => void;
};

/** Px CSS que caem em pixel inteiro do aparelho (sem meio-pixel borrado). */
export function alinharAoDispositivo(px: number, dpr: number): number {
  const escala = dpr > 0 ? dpr : 1;
  return Math.max(0, Math.floor(px * escala) / escala);
}

/**
 * O host escreve as falhas de abertura no próprio status. A tela esconde esse
 * status, porque tem o seu, então sem isto a falha fica muda: "Abrindo…" para
 * sempre. Devolve a mensagem quando o texto é de falha, ou `null`.
 */
export function falhaNoStatus(texto: string | null | undefined): string | null {
  const t = (texto ?? "").trim();
  return /^(Não foi possível abrir o editor|Editor indisponível|O contexto mudou)/.test(t) ? t : null;
}

function vigiarStatus(raiz: HTMLElement, aoFalhar: (mensagem: string) => void): () => void {
  const vigia = new MutationObserver(() => {
    const falha = falhaNoStatus(raiz.querySelector('p[role="status"]')?.textContent);
    if (falha) aoFalhar(falha);
  });
  vigia.observe(raiz, { childList: true, subtree: true, characterData: true });
  return () => vigia.disconnect();
}

function ajustarCanvas(raiz: HTMLElement): () => void {
  let canvas: HTMLCanvasElement | null = null;
  const medir = () => {
    if (!canvas) return;
    const area = canvas.parentElement ?? raiz;
    const dpr = window.devicePixelRatio || 1;
    const largura = alinharAoDispositivo(area.clientWidth, dpr);
    const altura = alinharAoDispositivo(area.clientHeight, dpr);
    canvas.style.display = "block";
    canvas.style.width = `${largura}px`;
    canvas.style.height = `${altura}px`;
  };
  const tamanho = new ResizeObserver(medir);
  tamanho.observe(raiz);
  const filhos = new MutationObserver(() => {
    const achado = raiz.querySelector("canvas");
    if (achado && achado !== canvas) {
      canvas = achado;
      medir();
    }
  });
  filhos.observe(raiz, { childList: true, subtree: true });
  let consulta: MediaQueryList | null = null;
  const aoMudarDpr = () => {
    medir();
    vigiarDpr();
  };
  const vigiarDpr = () => {
    consulta?.removeEventListener("change", aoMudarDpr);
    consulta = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
    consulta.addEventListener("change", aoMudarDpr);
  };
  vigiarDpr();
  return () => {
    tamanho.disconnect();
    filhos.disconnect();
    consulta?.removeEventListener("change", aoMudarDpr);
  };
}

export async function montarHost(
  raiz: HTMLElement,
  dados: Record<string, unknown>,
  setStateValue: (chave: string, valor: unknown) => void,
  aoFalhar: (mensagem: string) => void,
): Promise<HostMontado> {
  // Fora do bundle: o host roda como módulo nativo do navegador, e o import
  // dinâmico que ELE faz do JS/WASM aprovado fica fora do empacotador.
  const modulo = (await import(/* webpackIgnore: true */ /* turbopackIgnore: true */ HOST_URL)) as ModuloDoHost;
  const secao = document.createElement("section");
  secao.className = "gc-wordcraft-editor";
  raiz.append(secao);
  const soltarCanvas = ajustarCanvas(raiz);
  const soltarStatus = vigiarStatus(raiz, aoFalhar);
  const componente = (data: Record<string, unknown>) => ({ data, parentElement: raiz, setStateValue });
  const limpar = modulo.default(componente(dados));
  return {
    atualizar: (novos) => {
      modulo.default(componente(novos));
    },
    desmontar: () => {
      soltarCanvas();
      soltarStatus();
      if (typeof limpar === "function") limpar();
      secao.remove();
    },
  };
}
