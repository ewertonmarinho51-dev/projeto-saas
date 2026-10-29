import { cabecalho, metadados, RODAPE } from "@/components/site";
import { PublicPage, PublicSection } from "@/design-system";

export const metadata = metadados("/privacidade");

/**
 * Só o que o CÓDIGO faz, verificável neste repositório. A política
 * jurídica completa (bases legais, encarregado, prazos) é do órgão
 * contratante e entra quando for aprovada — não se inventa texto legal.
 */
export default function Privacidade() {
  return (
    <PublicPage
      header={cabecalho("/privacidade")}
      footer={RODAPE}
      eyebrow="Privacidade"
      title="Privacidade"
      lead="A política de privacidade completa é definida pelo órgão que contrata o Gov Conect. Enquanto ela não é publicada aqui, estes são os fatos sobre o tratamento técnico dos dados."
    >
      <PublicSection title="Como os dados são tratados" narrow>
        <p>
          <strong>Cookies.</strong> Só o cookie da sessão de login, necessário para manter você conectado. Não há
          cookies de publicidade nem de análise de navegação.
        </p>
        <p>
          <strong>Dados de conta.</strong> E-mail, nome e o vínculo com o órgão, cadastrados pelo administrador do
          seu órgão.
        </p>
        <p>
          <strong>Isolamento.</strong> Os processos de um município não ficam acessíveis a outro. A regra é
          aplicada no banco de dados.
        </p>
        <p>
          <strong>Dúvidas e pedidos.</strong> Procure o administrador do seu órgão.
        </p>
      </PublicSection>
    </PublicPage>
  );
}
