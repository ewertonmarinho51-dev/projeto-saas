import Image from "next/image";
import Link from "next/link";

/**
 * Logo oficial, sem redesenho: o PNG da marca com o fundo branco
 * original (o miolo branco do documento é parte do desenho). Sobre fundo
 * escuro ele fica numa placa branca, que é como a marca foi feita.
 */
export function Logo({ tamanho = 32, prioridade = false }: { tamanho?: number; prioridade?: boolean }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center overflow-hidden rounded-[6px] bg-white ring-1 ring-linha"
      style={{ width: tamanho, height: tamanho }}
    >
      <Image
        src={tamanho > 96 ? "/logo-govconect.png" : "/logo-govconect-96.png"}
        alt=""
        width={tamanho}
        height={tamanho}
        priority={prioridade}
      />
    </span>
  );
}

export function MarcaComNome({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2.5 font-semibold tracking-tight">
      <Logo tamanho={32} />
      <span>Gov Conect</span>
    </Link>
  );
}
