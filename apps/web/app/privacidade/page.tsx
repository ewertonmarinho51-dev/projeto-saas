import type { Metadata } from "next";
import Link from "next/link";

import { MarcaComNome } from "@/components/marca";

export const metadata: Metadata = { title: "Privacidade" };

/**
 * Só o que o CÓDIGO faz, verificável neste repositório. A política
 * jurídica completa (bases legais, encarregado, prazos) é do órgão
 * contratante e entra quando for aprovada — não se inventa texto legal.
 */
export default function Privacidade() {
  return (
    <main id="conteudo" className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <MarcaComNome />
      <h1 className="mt-10 text-3xl font-semibold tracking-tight">Privacidade</h1>
      <p className="mt-4 text-secundario">
        A política de privacidade completa é definida pelo órgão que contrata o Gov Conect. Enquanto ela
        não é publicada aqui, estes são os fatos sobre o tratamento técnico dos dados.
      </p>
      <ul className="mt-8 grid gap-5">
        <li>
          <h2 className="font-semibold">Cookies</h2>
          <p className="mt-1 text-secundario">
            Só o cookie da sessão de login, necessário para manter você conectado. Não há cookies de
            publicidade nem de análise de navegação.
          </p>
        </li>
        <li>
          <h2 className="font-semibold">Dados de conta</h2>
          <p className="mt-1 text-secundario">
            E-mail, nome e o vínculo com o órgão, cadastrados pelo administrador do seu órgão.
          </p>
        </li>
        <li>
          <h2 className="font-semibold">Isolamento</h2>
          <p className="mt-1 text-secundario">
            Os processos de um município não ficam acessíveis a outro. A regra é aplicada no banco de
            dados.
          </p>
        </li>
        <li>
          <h2 className="font-semibold">Dúvidas e pedidos</h2>
          <p className="mt-1 text-secundario">Procure o administrador do seu órgão.</p>
        </li>
      </ul>
      <Link href="/" className="mt-10 inline-block text-sm text-acento underline-offset-4 hover:underline">
        Voltar ao início
      </Link>
    </main>
  );
}
