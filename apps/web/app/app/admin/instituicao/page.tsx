/* eslint-disable @next/next/no-img-element -- prévia do timbrado: data URL vinda da API, não há o que otimizar */
import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import {
  DadosDaPrefeitura,
  IdentidadesVisuais,
  ModulosDaPrefeitura,
  ModulosDaSecretaria,
  NovaPortaria,
  Secretarias,
  Servidores,
  UmaPortaria,
} from "@/components/admin-instituicao";
import { Alert, Card, PageHead } from "@/design-system";
import {
  chamarApi,
  ErroDaApi,
  type Identidade,
  type IdentidadeVisual,
  type Instituicao,
  type ModuloInstitucional,
  type PortariaInstitucional,
  type PrefeituraInstitucional,
  type SecretariaCadastrada,
  type ServidorInstitucional,
  type Timbrado,
} from "@/lib/api";

export const metadata: Metadata = { title: "Instituição" };

const UUID = /^[0-9a-f-]{36}$/i;
const SECOES: Record<string, string> = {
  Prefeitura: "prefeitura",
  Secretarias: "secretarias",
  "Identidade visual": "identidade",
  Timbrado: "timbrado",
  Módulos: "modulos",
  Servidores: "servidores",
  Portarias: "portarias",
};

const ORIGEM: Record<Timbrado["origem"], { variante: "success" | "info" | "warning"; texto: string }> = {
  secretaria: { variante: "success", texto: "Identidade própria: esta secretaria tem timbrado cadastrado, e é ele que sai nos documentos dela." },
  municipio: { variante: "info", texto: "Herdado do município: esta secretaria não tem timbrado próprio, e os documentos dela saem com o da secretaria marcada como padrão." },
  nenhuma: { variante: "warning", texto: "Nenhuma identidade cadastrada: os documentos sairão SEM timbrado. Defina uma identidade padrão em Identidade visual." },
};

async function dados<T>(caminho: string): Promise<T> {
  return (await chamarApi<T>(caminho)).dados;
}

export default async function PaginaDaInstituicao({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const busca = await searchParams;
  const eu = await dados<Identidade>("/me");
  if (eu.papel !== "admin") notFound();

  let visao: Instituicao;
  try {
    visao = await dados<Instituicao>("/admin/instituicao");
  } catch (e) {
    if (e instanceof ErroDaApi && (e.status === 404 || e.status === 403)) notFound();
    throw e;
  }

  const disponiveis = visao.secoes.map((s) => SECOES[s]).filter(Boolean);
  const secao = typeof busca.secao === "string" && disponiveis.includes(busca.secao) ? busca.secao : disponiveis[0];
  const secretaria =
    typeof busca.secretaria === "string" && UUID.test(busca.secretaria) ? busca.secretaria : visao.secretarias[0]?.id;
  if (!secao) redirect("/app");

  const link = (s: string, sec = secretaria) => `/app/admin/instituicao?secao=${s}${sec ? `&secretaria=${sec}` : ""}`;

  let corpo: React.ReactNode = null;
  if (secao === "prefeitura") {
    corpo = <DadosDaPrefeitura prefeitura={await dados<PrefeituraInstitucional>("/admin/instituicao/prefeitura")} />;
  } else if (secao === "secretarias") {
    corpo = <Secretarias secretarias={await dados<SecretariaCadastrada[]>("/admin/instituicao/secretarias")} />;
  } else if (secao === "identidade") {
    corpo = <IdentidadesVisuais identidades={await dados<IdentidadeVisual[]>("/admin/instituicao/identidades")} />;
  } else if (secao === "servidores") {
    corpo = <Servidores servidores={await dados<ServidorInstitucional[]>("/admin/instituicao/servidores")} />;
  } else if (!secretaria) {
    corpo = (
      <Alert variant="info">
        Nenhuma secretaria cadastrada. Timbrado, módulos por secretaria e portarias são por secretaria: cadastre-as na
        seção Secretarias.
      </Alert>
    );
  } else if (secao === "timbrado") {
    const t = await dados<Timbrado>(`/admin/instituicao/timbrado?secretaria_id=${secretaria}`);
    corpo = (
      <div className="grid gap-4">
        <Alert variant={ORIGEM[t.origem].variante}>{ORIGEM[t.origem].texto}</Alert>
        {t.origem !== "nenhuma" && (
          <Card title="Prévia" subtitle="O mesmo resolvedor que a exportação usa." divided>
            {t.cabecalho_img || t.rodape_img || t.marca_img ? (
              <div className="grid gap-4">
                {t.cabecalho_img ? <img src={t.cabecalho_img} alt="Cabeçalho do timbrado" className="w-full" /> : <p className="text-secundario">Sem imagem de cabeçalho.</p>}
                {t.marca_img && <img src={t.marca_img} alt="Marca d'água" className="w-56" />}
                {t.rodape_img ? <img src={t.rodape_img} alt="Rodapé do timbrado" className="w-full" /> : <p className="text-secundario">Sem imagem de rodapé.</p>}
              </div>
            ) : (
              <pre className="gc-mono whitespace-pre-wrap text-[length:var(--gc-fs-sm)]">
                {`Cabeçalho: ${t.cabecalho_texto || "(vazio)"}\nRodapé:    ${t.rodape_texto || "(vazio)"}\nMarca:     ${t.marca_texto || "(nenhuma)"}`}
              </pre>
            )}
          </Card>
        )}
      </div>
    );
  } else if (secao === "modulos") {
    const [daPrefeitura, daSecretaria] = await Promise.all([
      dados<{ modulos: ModuloInstitucional[] }>("/admin/instituicao/modulos"),
      dados<{ modulos: ModuloInstitucional[] }>(`/admin/instituicao/modulos?secretaria_id=${secretaria}`),
    ]);
    corpo = (
      <div className="grid gap-6">
        <ModulosDaPrefeitura modulos={daPrefeitura.modulos} />
        <ModulosDaSecretaria key={secretaria} secretaria={secretaria} modulos={daSecretaria.modulos} />
      </div>
    );
  } else {
    const [acervo, servidores] = await Promise.all([
      dados<{ portarias: PortariaInstitucional[]; avisos: string[] }>(`/admin/instituicao/portarias?secretaria_id=${secretaria}`),
      dados<ServidorInstitucional[]>("/admin/instituicao/servidores").catch(() => [] as ServidorInstitucional[]),
    ]);
    corpo = (
      <div className="grid gap-6">
        <NovaPortaria key={secretaria} secretaria={secretaria} tipos={visao.tipos_de_portaria} />
        {acervo.avisos.map((a) => (
          <Alert key={a} variant="error" compact>
            {a}
          </Alert>
        ))}
        <p className="text-[length:var(--gc-fs-sm)] text-secundario">
          Portaria não se apaga: revoga-se. O histórico é o que permite a um documento de 2025 continuar citando a portaria de 2025.
        </p>
        {acervo.portarias.length === 0 ? (
          <p className="text-secundario">Nenhuma portaria registrada nesta secretaria.</p>
        ) : (
          acervo.portarias.map((p) => (
            <UmaPortaria key={p.id} portaria={p} situacoes={visao.situacoes_declaradas} funcoes={visao.funcoes_de_membro} servidores={servidores} />
          ))
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <PageHead
        title="Instituição"
        desc="Cadastro institucional: é daqui que o sistema tira, sozinho, o timbrado, a equipe de planejamento e quem pode assinar cada documento."
      />
      <nav aria-label="Seções da Instituição" className="gc-tabs">
        {visao.secoes.map((rotulo) => (
          <Link
            key={rotulo}
            href={link(SECOES[rotulo])}
            className="gc-tab"
            aria-current={SECOES[rotulo] === secao ? "page" : undefined}
          >
            {rotulo}
          </Link>
        ))}
      </nav>
      {["timbrado", "modulos", "portarias"].includes(secao) && visao.secretarias.length > 1 && (
        <nav aria-label="Secretaria" className="flex flex-wrap gap-2">
          {visao.secretarias.map((s) => (
            <Link
              key={s.id}
              href={link(secao, s.id)}
              className={s.id === secretaria ? "gc-btn gc-btn--subtle gc-btn--sm" : "gc-btn gc-btn--ghost gc-btn--sm"}
              aria-current={s.id === secretaria ? "true" : undefined}
            >
              {s.nome}
            </Link>
          ))}
        </nav>
      )}
      {corpo}
    </div>
  );
}
