import Image from "next/image";
import Link from "next/link";

import { cx } from "../../lib/cx";

export interface LogoProps {
  /** Lado do símbolo, em px. Mínimo 20. */
  size?: number;
  withName?: boolean;
  name?: string;
  /** Troca o arquivo (caminho público). Padrão: /logo-govconect-96.png até 96 px, /logo-govconect.png acima. */
  src?: string;
  href?: string;
  /** Pré-carrega a imagem (logo acima da dobra). */
  priority?: boolean;
  className?: string;
}

/**
 * Marca oficial do Gov Conect: documento azul com dobra, três linhas e
 * duplo check, com o nome em Geist Semibold ao lado. O PNG é
 * transparente (do logo vetorizado): nunca em placa ou quadrado branco,
 * nunca redesenhado, nunca trocado por monograma "G". Em fundo escuro,
 * direto ou na versão branca (`filter: brightness(0) invert(1)`).
 */
export function Logo({ size = 32, withName = true, name = "Gov Conect", src, href, priority = false, className }: LogoProps) {
  const arquivo = src ?? (size > 96 ? "/logo-govconect.png" : "/logo-govconect-96.png");
  const conteudo = (
    <>
      <Image src={arquivo} alt={withName ? "" : name} width={size} height={size} priority={priority} />
      {withName && <span className="gc-logo__name">{name}</span>}
    </>
  );
  // O nome cresce com o símbolo (metade do lado, mínimo de 15 px): é
  // proporção da marca, não valor solto.
  const estilo = { fontSize: Math.max(15, Math.round(size * 0.5)) };
  if (href) {
    return (
      <Link href={href} className={cx("gc-logo", className)} style={estilo}>
        {conteudo}
      </Link>
    );
  }
  return (
    <span className={cx("gc-logo", className)} style={estilo}>
      {conteudo}
    </span>
  );
}
