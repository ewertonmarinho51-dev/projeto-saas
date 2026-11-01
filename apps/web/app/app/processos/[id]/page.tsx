import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ElaboracaoAutomatica } from "@/components/elaboracao-automatica";
import { FormularioDeProcesso } from "@/components/form-processo";
import { situacaoDoProcesso } from "@/components/situacao";
import { Alert, Button, Card, DataList, PageHead, ProgressBar, StatusBadge } from "@/design-system";
import { chamarApi, elaboracaoDoProcesso, ErroDaApi, govbotHabilitado, type Elaboracao, type Modulos, type Processo } from "@/lib/api";

import { editarProcesso } from "../acoes";

export const metadata: Metadata = { title: "Processo" };

const DATA = new Intl.DateTimeFormat("pt-BR", { dateStyle: "long", timeStyle: "short", timeZone: "America/Sao_Paulo" });

export default async function DetalheDoProcesso({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const avisos = await searchParams;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();

  let p: Processo;
  let modulos: Modulos = { consolidar_demandas: false };
  let elaboracao: Elaboracao | null = null;
  try {
    [p, modulos, elaboracao] = await Promise.all([
      chamarApi<Processo>(`/processos/${id}`).then((r) => r.dados),
      // Módulos opcionais: falha aqui não derruba a página, só some o atalho.
      chamarApi<Modulos>("/modulos").then((r) => r.dados).catch(() => modulos),
      // Elaboração e revisão (WordCraft Workspace): só com o canário ligado para quem chama.
      elaboracaoDoProcesso(id).catch(() => null),
    ]);
  } catch (e) {
    // 404 também para processo de outro município: não confirma que existe.
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }

  const aviso = avisos.criado
    ? "Processo criado."
    : avisos.salvo
      ? "Alterações salvas."
      : avisos.iniciado
        ? elaboracao
          ? "Dados da demanda completos. Inicie a elaboração automática."
          : "Dados da demanda completos. A geração dos documentos ainda é feita no GovDocs, até a próxima etapa da migração."
        : null;
  const editando = avisos.editar === "1";

  return (
    <>
      <PageHead
        eyebrow={
          <span className="justify-self-start">
            <StatusBadge status={situacaoDoProcesso(p.status)} label={p.status} />
          </span>
        }
        title={<span data-testid="titulo-processo">{p.nome_exibido}</span>}
        desc={`Atualizado em ${p.atualizado_em ? DATA.format(new Date(p.atualizado_em)) : "data indisponível"}.`}
        actions={
          govbotHabilitado() && (
            <Button href={`/app/govbot?processo=${p.id}`} variant="secondary" icon="sparkle">
              Perguntar ao GovBot
            </Button>
          )
        }
      />

      {aviso && <Alert variant="success" title={aviso} />}

      {elaboracao ? (
        <ElaboracaoAutomatica processoId={p.id} inicial={elaboracao} />
      ) : (
        <Card>
          <DataList
            stacked
            items={[
              { label: "Situação", value: p.status },
              { label: "Etapa", value: p.etapa },
              {
                label: "Documentos aprovados",
                value: (
                  <ProgressBar
                    size="sm"
                    value={p.progresso.feitos}
                    max={Math.max(p.progresso.total, 1)}
                    showValue={false}
                    hint={`${p.progresso.feitos} de ${p.progresso.total}`}
                  />
                ),
              },
            ]}
          />
        </Card>
      )}

      <Card
        title="Dados do processo"
        subtitle={editando ? undefined : "Nome, órgão e objeto. O Formulário Matriz traz o restante que os documentos usam."}
        divided
        actions={
          editando ? (
            <Button href={`/app/processos/${p.id}`} variant="subtle">
              Cancelar
            </Button>
          ) : (
            <>
              {modulos.consolidar_demandas && (
                <Button href={`/app/processos/${p.id}/demandas`} variant="secondary" icon="tray">
                  Consolidar demandas
                </Button>
              )}
              {/* Com a elaboração, faltar dado já é a próxima ação lá em cima. */}
              {elaboracao?.proximo.acao !== "formulario" && (
                <Button href={`/app/processos/${p.id}/formulario`} variant={elaboracao ? "secondary" : "primary"} icon="file-text">
                  {elaboracao ? "Dados da demanda" : "Preencher dados da demanda"}
                </Button>
              )}
              <Button href={`/app/processos/${p.id}?editar=1`} variant="secondary" icon="pencil-simple">
                Editar dados do processo
              </Button>
            </>
          )
        }
      >
        {editando ? (
          <div className="max-w-xl">
            <FormularioDeProcesso
              acao={editarProcesso}
              rotuloDoBotao="Salvar alterações"
              ocultos={{ id: p.id, versao: p.versao }}
              inicial={{ nome: p.nome, orgao: p.orgao, objeto: p.objeto }}
            />
          </div>
        ) : (
          <DataList
            items={[
              ...(p.nome ? [{ label: "Nome", value: p.nome }] : []),
              { label: "Órgão ou secretaria", value: p.orgao },
              { label: "Objeto da contratação", value: p.objeto },
            ]}
          />
        )}
      </Card>
    </>
  );
}
