"use client";

import { useState } from "react";

import {
  Accordion,
  Alert,
  Badge,
  BarChart,
  Button,
  Card,
  DataList,
  DataTable,
  Dialog,
  DocumentViewer,
  EmptyState,
  KpiCard,
  Pagination,
  PROCESS_STATUS,
  ProgressBar,
  Skeleton,
  SkeletonText,
  Spinner,
  StatusBadge,
  TableContainer,
  Tag,
  Toast,
  ToastStack,
  type BadgeVariant,
  type DataTableColumn,
  type ProcessStatus,
  type RowKey,
  type SortState,
} from "../index";
import { Exemplo, Grade, Linha, Palco, Secao } from "./partes";

const BADGES: BadgeVariant[] = ["neutral", "brand", "info", "success", "warning", "error", "solid"];

interface LinhaItem {
  id: number;
  n: string;
  desc: string;
  unidade: string;
  preco: string;
  status: ProcessStatus;
  _muted?: boolean;
}

const LINHAS: LinhaItem[] = [
  { id: 1, n: "01", desc: "Papel A4 75 g/m², caixa com 10 resmas", unidade: "CX", preco: "R$ 229,90", status: "concluido" },
  { id: 2, n: "02", desc: "Caneta esferográfica azul", unidade: "UN", preco: "R$ 1,35", status: "em_revisao" },
  { id: 3, n: "03", desc: "Grampeador de mesa 26/6", unidade: "UN", preco: "R$ 38,00", status: "pendente" },
  { id: 4, n: "04", desc: "Toner compatível (fora do cálculo)", unidade: "UN", preco: "R$ 410,00", status: "arquivado", _muted: true },
];

const COLUNAS: DataTableColumn<LinhaItem>[] = [
  { key: "n", label: "Nº", width: "4rem" },
  { key: "desc", label: "Descrição", sortable: true },
  { key: "unidade", label: "Unidade" },
  { key: "preco", label: "Preço estimado", align: "right", sortable: true, render: (r) => <span className="gc-num">{r.preco}</span> },
  { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} size="sm" /> },
];

export function GaleriaConteudo({ tema }: { tema: string }) {
  const [dialogo, setDialogo] = useState<"default" | "danger" | "warning" | null>(null);
  const [selecao, setSelecao] = useState<RowKey[]>([2]);
  const [ordem, setOrdem] = useState<SortState>({ key: "desc", dir: "asc" });
  const [pagina, setPagina] = useState(2);
  const [filtros, setFiltros] = useState(["PNCP", "Compras.gov.br"]);
  const [aviso, setAviso] = useState(true);

  return (
    <>
      <Secao id="content" tema={tema} titulo="Content" descricao="Card, DataList, Accordion, Dialog e DocumentViewer.">
        <Grade>
          <Exemplo rotulo="Card — cabeçalho, ações e rodapé">
            <Card
              eyebrow="Pesquisa de preços"
              title="Cesta de preços"
              subtitle="Referências selecionadas para o cálculo."
              actions={<Badge variant="brand">3 selecionadas</Badge>}
              footer={
                <Button size="sm" variant="secondary">
                  Ver cesta
                </Button>
              }
            >
              <p className="text-secundario">Média das referências válidas: R$ 22,33.</p>
            </Card>
          </Exemplo>
          <Exemplo rotulo="Card — elevado, interativo, selecionado, rebaixado">
            <div className="grid gap-3">
              <Card elevated>Elevado (sombra pequena)</Card>
              <Card interactive>Interativo (passe o mouse)</Card>
              <Card selected>Selecionado</Card>
              <Card sunken>Rebaixado</Card>
            </div>
          </Exemplo>
          <Exemplo rotulo="Card — flush e dividido (tabela dentro)" largo>
            <Card flush divided title="Itens" subtitle="Sem padding no corpo.">
              <DataTable compact columns={COLUNAS.slice(0, 4)} rows={LINHAS.slice(0, 2)} caption="Itens (compacta)" />
            </Card>
          </Exemplo>
          <Exemplo rotulo="DataList — duas colunas">
            <DataList
              items={[
                { label: "Fonte consultada", value: "PNCP — Contratações" },
                { label: "Órgão", value: "Prefeitura de Belém · PA" },
                { label: "Valor", value: "R$ 229,90", numeric: true },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="DataList — empilhada (resumo)">
            <DataList
              stacked
              items={[
                { label: "Situação", value: "Em elaboração" },
                { label: "Valor global", value: "R$ 18.535,00", numeric: true },
                { label: "Data-base", value: "23/10/2026" },
                { label: "Responsável", value: "Não informado" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="Accordion — aberto, com ícone e meta" largo>
            <Accordion
              items={[
                { title: "Entenda o cálculo", content: "Média aritmética das referências válidas da cesta.", defaultOpen: true },
                { title: "Filtros aplicados", meta: "8 considerados", icon: "funnel", content: "Período de 12 meses; mesma unidade de medida." },
                { title: "Método do item", icon: "scales", content: "Lei nº 14.133/2021, art. 23." },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="Dialog — padrão, perigo, atenção (contidos)" largo>
            <Linha>
              <Button variant="secondary" onClick={() => setDialogo("default")}>
                Abrir padrão
              </Button>
              <Button variant="danger-subtle" onClick={() => setDialogo("danger")}>
                Abrir perigo
              </Button>
              <Button variant="secondary" onClick={() => setDialogo("warning")}>
                Abrir atenção
              </Button>
            </Linha>
            <Palco>
              <Dialog
                contained
                size="sm"
                open
                title="Excluir processo?"
                tone="danger"
                icon="trash"
                description="Os documentos gerados também serão removidos."
                footer={
                  <>
                    <Button variant="secondary">Cancelar</Button>
                    <Button variant="danger">Excluir processo</Button>
                  </>
                }
              />
            </Palco>
            {dialogo && (
              <Dialog
                open
                onClose={() => setDialogo(null)}
                tone={dialogo}
                size={dialogo === "warning" ? "lg" : "md"}
                icon={dialogo === "default" ? "info" : dialogo === "danger" ? "trash" : "warning"}
                title={dialogo === "default" ? "Gerar o ETP agora?" : dialogo === "danger" ? "Excluir processo?" : "Valores divergentes"}
                description="Esc e clique fora fecham o diálogo."
                footer={
                  <>
                    <Button variant="secondary" onClick={() => setDialogo(null)}>
                      Cancelar
                    </Button>
                    <Button variant={dialogo === "danger" ? "danger" : "primary"} onClick={() => setDialogo(null)}>
                      {dialogo === "danger" ? "Excluir processo" : "Continuar"}
                    </Button>
                  </>
                }
              >
                <p className="text-secundario">Conteúdo do diálogo.</p>
              </Dialog>
            )}
          </Exemplo>
          <Exemplo rotulo="DocumentViewer — trecho de IA e trecho a revisar" largo>
            <DocumentViewer
              name="ETP — Aquisição de material de expediente"
              meta="Versão 3 · editado há 2 h"
              badges={<StatusBadge status="em_revisao" size="sm" />}
              actions={
                <Button size="sm" variant="ghost" icon="download-simple">
                  Baixar
                </Button>
              }
              height="calc(var(--space-16) * 6)"
            >
              <h1>Estudo Técnico Preliminar</h1>
              <p>
                <span className="gc-mark-ai">A necessidade decorre do consumo médio das secretarias nos últimos 12 meses.</span>{" "}
                <span className="gc-mark-review">O quantitativo precisa ser conferido pelo setor requisitante.</span>
              </p>
            </DocumentViewer>
          </Exemplo>
        </Grade>
      </Secao>

      <Secao id="feedback" tema={tema} titulo="Feedback" descricao="Alert, Toast, Badge, StatusBadge, Tag, EmptyState, Skeleton, Spinner e ProgressBar.">
        <Grade>
          <Exemplo rotulo="Alert — variantes" largo>
            <div className="grid gap-3">
              <Alert variant="info" title="Avaliação preliminar">
                Sinalização estatística não substitui a análise de comparabilidade.
              </Alert>
              <Alert variant="success" title="Pesquisa concluída">
                Os 7 itens têm preço estimado.
              </Alert>
              <Alert
                variant="warning"
                title="Atenção aos valores divergentes"
                actions={
                  <Button size="sm" variant="secondary">
                    Revisar itens
                  </Button>
                }
              >
                Revise os preços antes de gerar o relatório.
              </Alert>
              {aviso && (
                <Alert variant="error" title="Não foi possível entrar" onClose={() => setAviso(false)}>
                  E-mail ou senha não conferem. Verifique os dados ou procure o administrador do órgão.
                </Alert>
              )}
              <Alert variant="neutral" compact>
                Dados ilustrativos.
              </Alert>
            </div>
          </Exemplo>
          <Exemplo rotulo="Toast — variantes (pilha contida)">
            <div className="[&_.gc-toast-stack]:static">
              <ToastStack>
                <Toast title="Pesquisa salva" description="7 itens · 42 referências" onClose={() => undefined} />
                <Toast variant="info" title="Coleta na fila" action={<a href="#">Acompanhar</a>} />
                <Toast variant="warning" title="Uma fonte não respondeu" />
                <Toast variant="error" title="Falha ao gerar o relatório" />
              </ToastStack>
            </div>
          </Exemplo>
          <Exemplo rotulo="Badge — variantes, tamanhos, ponto, caixa alta, quadrado">
            <div className="grid gap-3">
              <Linha>
                {BADGES.map((v) => (
                  <Badge key={v} variant={v}>
                    {v}
                  </Badge>
                ))}
              </Linha>
              <Linha>
                <Badge size="sm" variant="success" icon="check">
                  Compatível
                </Badge>
                <Badge size="lg" variant="brand">
                  PNCP
                </Badge>
                <Badge variant="success" dot>
                  Salvo
                </Badge>
                <Badge variant="warning" caps>
                  Avaliação preliminar
                </Badge>
                <Badge variant="neutral" square>
                  12
                </Badge>
              </Linha>
            </div>
          </Exemplo>
          <Exemplo rotulo="StatusBadge — vocabulário inteiro">
            <Linha>
              {(Object.keys(PROCESS_STATUS) as ProcessStatus[]).map((s) => (
                <StatusBadge key={s} status={s} />
              ))}
            </Linha>
          </Exemplo>
          <Exemplo rotulo="Tag — removível, ativa, estática">
            <Linha>
              {filtros.map((f) => (
                <Tag key={f} keyLabel="Fonte" label={f} onRemove={() => setFiltros((l) => l.filter((x) => x !== f))} />
              ))}
              <Tag label="Últimos 12 meses" active onRemove={() => undefined} />
              <Tag>Estática</Tag>
            </Linha>
          </Exemplo>
          <Exemplo rotulo="EmptyState">
            <Card>
              <EmptyState
                title="Nenhum processo ainda"
                description="Comece registrando o órgão e o objeto da contratação. Os documentos vêm depois."
                actions={<Button icon="plus">Novo processo</Button>}
              />
            </Card>
          </Exemplo>
          <Exemplo rotulo="Skeleton e Spinner">
            <div className="grid gap-4">
              <Linha>
                <Skeleton circle width={40} height={40} />
                <Skeleton width={160} height={20} />
              </Linha>
              <SkeletonText lines={3} />
              <Linha>
                <Spinner label="Coletando preços" />
                <Spinner size="lg" label="Carregando" />
                <Spinner accent={false} label="Carregando" />
              </Linha>
            </div>
          </Exemplo>
          <Exemplo rotulo="ProgressBar — valor, tons, pequena, indeterminada">
            <div className="grid gap-4">
              <ProgressBar label="Estudo Técnico Preliminar" value={65} hint="4 de 6 seções revisadas" />
              <ProgressBar label="Itens com preço" value={7} max={7} tone="success" />
              <ProgressBar label="Referências antigas" value={30} tone="warning" size="sm" />
              <ProgressBar label="Coletando no PNCP" indeterminate />
            </div>
          </Exemplo>
        </Grade>
      </Secao>

      <Secao id="data" tema={tema} titulo="Data" descricao="KpiCard, DataTable, TableContainer, Pagination e BarChart. Número à direita, tabular.">
        <div className="grid gap-4 md:grid-cols-3">
          <KpiCard label="Processos ativos" value="24" icon="briefcase" delta="+12% neste mês" footnote="Em andamento no órgão" trend={[4, 7, 6, 11, 10, 14, 16]} />
          <KpiCard label="Valor estimado" value="18.535" unit="R$" delta="−3%" deltaTone="warning" footnote="Comparado ao PCA" />
          <KpiCard
            compact
            label="Itens sem preço"
            value="2"
            delta="Pendente"
            deltaTone="error"
            action={
              <Button size="sm" variant="link">
                Ver
              </Button>
            }
          />
        </div>
        <Exemplo rotulo="DataTable — selecionável, ordenável, linha apagada">
          <TableContainer>
            <DataTable
              selectable
              selected={selecao}
              onSelect={setSelecao}
              sort={ordem}
              onSort={setOrdem}
              columns={COLUNAS}
              rows={LINHAS}
              caption="Itens da pesquisa"
              minWidth="48rem"
            />
          </TableContainer>
        </Exemplo>
        <Grade>
          <Exemplo rotulo="DataTable — vazia">
            <TableContainer>
              <DataTable columns={COLUNAS.slice(0, 3)} rows={[] as LinhaItem[]} caption="Sem itens" />
            </TableContainer>
          </Exemplo>
          <Exemplo rotulo="DataTable — stack (cartão até 640 px; nunca em tabela de preço)">
            <TableContainer>
              <DataTable stack compact columns={COLUNAS.slice(0, 3)} rows={LINHAS.slice(0, 2)} caption="Itens (empilhada)" />
            </TableContainer>
          </Exemplo>
          <Exemplo rotulo="Pagination">
            <Pagination page={pagina} pageSize={10} total={48} onChange={setPagina} />
          </Exemplo>
          <Exemplo rotulo="BarChart — preço unitário por fonte" largo>
            <BarChart
              data={[
                { label: "PNCP", value: 3890 },
                { label: "Compras.gov.br", value: 4250 },
                { label: "Painel de Preços", value: 4320 },
                { label: "Pesquisa direta", value: 4610 },
              ]}
            />
          </Exemplo>
        </Grade>
      </Secao>
    </>
  );
}
