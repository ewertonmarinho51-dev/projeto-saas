import Link from "next/link";

import { cabecalho, metadados, RODAPE } from "@/components/site";
import { Alert, buttonClasses, PublicFeature, PublicGrid, PublicPage, PublicSection } from "@/design-system";

export const metadata = metadados("/contato");

/**
 * O canal comercial vem do ambiente (`GOVCONECT_CONTATO_EMAIL`): endereço
 * inventado no código seria um contato que ninguém lê. Sem ele, a página
 * diz que o canal ainda não foi publicado — e não mostra formulário que
 * não vai a lugar nenhum.
 */
function emailComercial(): string | null {
  const e = process.env.GOVCONECT_CONTATO_EMAIL?.trim();
  return e && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) ? e : null;
}

export default function Contato() {
  const email = emailComercial();
  return (
    <PublicPage
      header={cabecalho("/contato")}
      footer={RODAPE}
      eyebrow="Contato"
      title="Fale com a equipe do Gov Conect"
      lead="Para conhecer a plataforma, agendar uma demonstração ou tratar da contratação pelo seu órgão."
      actions={
        email ? (
          <a className={buttonClasses({ size: "lg" })} href={`mailto:${email}`}>
            Escrever para {email}
          </a>
        ) : undefined
      }
    >
      <PublicSection eyebrow="Canais" title="Como podemos ajudar" narrow>
        {email ? (
          <p>
            Escreva para <a href={`mailto:${email}`}>{email}</a> com o nome do órgão, o município e o que você
            procura. Respondemos pelo mesmo endereço.
          </p>
        ) : (
          <Alert variant="info" title="Canal comercial em publicação">
            O endereço de contato comercial ainda não foi publicado nesta página. Se você já usa o Gov Conect, fale
            com o administrador do seu órgão.
          </Alert>
        )}
      </PublicSection>

      <PublicSection muted eyebrow="Já usa a plataforma?" title="Suporte para quem já tem acesso">
        <PublicGrid columns={2}>
          <PublicFeature icon="users-three" title="Conta e senha">
            Contas são criadas e reativadas pelo administrador do seu órgão. Esqueceu a senha? Use a recuperação na
            tela de entrada.
          </PublicFeature>
          <PublicFeature icon="sign-in" title="Acessar o sistema" href="/entrar" linkLabel="Ir para a entrada">
            Entre com o e-mail institucional cadastrado pelo seu órgão.
          </PublicFeature>
        </PublicGrid>
        <p>
          <Link href="/privacidade">Como tratamos os dados</Link>
        </p>
      </PublicSection>
    </PublicPage>
  );
}
