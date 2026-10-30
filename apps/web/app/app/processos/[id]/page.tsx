import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { FormularioDeProcesso } from "@/components/form-processo";
import { situacaoDoProcesso } from "@/components/situacao";
import { Alert, Badge, Button, Card, DataList, PageHead, ProgressBar, StatusBadge } from "@/design-system";
import {
  chamarApi,
  documentosDoProcesso,
  ErroDaApi,
  type DocumentosDoProcesso,
  type Modulos,
  type Processo,
} from "@/lib/api";

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
  let documentos: DocumentosDoProcesso | null = null;
  try {
    p = (await chamarApi<Processo>(`/processos/${id}`)).dados;
    // Módulos opcionais: falha aqui não derruba a página, só some o atalho.
    modulos = await chamarApi<Modulos>("/modulos").then((r) => r.dados).catch(() => modulos);
    // Editor de documentos (WordCraft Workspace): só com o canário ligado para quem chama.
    documentos = await documentosDoProcesso(id).catch(() => null);
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
        ? "Dados da demanda completos. A geração dos documentos ainda é feita no GovDocs, até a próxima etapa da migração."
        : null;

  return (
    <>
      <PageHead
        eyebrow={<StatusBadge status={situacaoDoProcesso(p.status)} label={p.status} />}
        title={<span data-testid="titulo-processo">{p.nome_exibido}</span>}
        desc={`Atualizado em ${p.atualizado_em ? DATA.format(new Date(p.atualizado_em)) : "data indisponível"}.`}
      />

      {aviso && <Alert variant="success" title={aviso} />}

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

      <Card
        title="Dados da demanda"
        subtitle="Formulário Matriz: objeto, justificativa, planilha de itens e o restante que os documentos usam."
        actions={
          <>
            {modulos.consolidar_demandas && (
              <Button href={`/app/processos/${p.id}/demandas`} variant="secondary" icon="tray">
                Consolidar demandas
              </Button>
            )}
            <Button href={`/app/processos/${p.id}/formulario`} icon="pencil-simple">
              Preencher dados da demanda
            </Button>
          </>
        }
      />

      {documentos && documentos.documentos.length > 0 && (
        <Card title="Documentos" subtitle="Edite em tela ampla no editor nativo; o salvamento é confirmado pelo servidor." divided>
          <ul className="grid gap-3" data-testid="documentos-do-processo">
            {documentos.documentos.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3">
                <span className="grid gap-0.5">
                  <span className="font-medium">{d.rotulo}</span>
                  <span className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                    {d.nativo ? (
                      <>
                        <Badge size="sm" variant={d.status === "aprovado" ? "success" : "neutral"}>
                          {d.status === "aprovado" ? "Aprovado" : d.status === "emitido" ? "Emitido" : "Rascunho"}
                        </Badge>
                        Revisão {d.revisao}
                      </>
                    ) : (
                      "Gerado no GovDocs; ainda não aberto no editor"
                    )}
                  </span>
                </span>
                {/* Sem revisão nativa, abrir importa o texto do GovDocs: é gravação. */}
                {(d.nativo || documentos.escrita) && (
                  <Button size="sm" variant="secondary" icon="pencil-simple" href={`/app/processos/${p.id}/documentos/${d.id}/editar`}>
                    Abrir no editor
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Dados do processo" divided>
        <div className="max-w-xl">
          <FormularioDeProcesso
            acao={editarProcesso}
            rotuloDoBotao="Salvar alterações"
            ocultos={{ id: p.id, versao: p.versao }}
            inicial={{ nome: p.nome, orgao: p.orgao, objeto: p.objeto }}
          />
        </div>
      </Card>
    </>
  );
}
