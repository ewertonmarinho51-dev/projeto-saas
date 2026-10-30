"use client";

import { useState } from "react";

import {
  AiDraftBlock,
  AiProcessing,
  Alert,
  AppShell,
  AuthLayout,
  Avatar,
  Badge,
  Breadcrumbs,
  Button,
  Card,
  ChatComposer,
  ChatMessage,
  Checkbox,
  Cite,
  ContextBar,
  ConversationList,
  DataList,
  DocumentWorkspace,
  ExclusionDialog,
  Field,
  Input,
  LandingHero,
  Logo,
  MessageFeedback,
  PageHead,
  PriceBasket,
  PriceDispersion,
  PriceItemNav,
  PriceMapTable,
  PriceReferenceRow,
  PriceStats,
  PromptSuggestions,
  PublicFeature,
  PublicFooter,
  PublicGrid,
  PublicSection,
  PublicSteps,
  ScreeningSummary,
  SourceList,
  SourcePicker,
  TraceabilityPanel,
  UserCard,
  ValidationSummary,
  type ScreeningKey,
  type SidebarGroup,
} from "../index";
import { Exemplo, Grade, Palco, Secao } from "./partes";

const FONTES = [
  { n: 1, title: "Lei nº 14.133/2021, art. 18", meta: "Referência normativa", excerpt: "A fase preparatória do processo licitatório é caracterizada pelo planejamento…" },
  { n: 2, title: "DFD — Material de expediente", meta: "Documento do processo", href: "#" },
];

const MENU: SidebarGroup[] = [
  {
    items: [
      { id: "inicio", icon: "house", label: "Início" },
      { id: "processos", icon: "folder-open", label: "Processos", active: true },
      { id: "cotacoes", icon: "currency-circle-dollar", label: "Cotações" },
    ],
  },
];

export function GaleriaIA({ tema }: { tema: string }) {
  const [rascunho, setRascunho] = useState<"pending" | "accepted" | "rejected">("pending");
  const [filtro, setFiltro] = useState<ScreeningKey | null>(null);
  const [fontes, setFontes] = useState(["pncp", "compras"]);
  const [item, setItem] = useState<string | number>(1);
  const [cesta, setCesta] = useState([true, true, false]);
  const [exclusao, setExclusao] = useState<string | null>(null);

  return (
    <>
      <Secao
        id="ai"
        tema={tema}
        titulo="GovBot (IA)"
        descricao="Toda resposta mostra o contexto usado, cita as fontes e leva o aviso de revisão. Nada entra no documento sem o clique do usuário."
      >
        <Grade>
          <Exemplo rotulo="ContextBar" largo>
            <ContextBar
              onAdd={() => undefined}
              items={[
                { kind: "process", icon: "folder-open", label: "Proc. 2026/001234" },
                { kind: "document", icon: "file-text", label: "DFD v2" },
                { kind: "knowledge", icon: "books", label: "Base do órgão", onRemove: () => undefined },
                { kind: "law", icon: "scales", label: "Lei 14.133/2021" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="ChatMessage — usuário, assistente com fontes, escrevendo" largo>
            <div className="grid gap-5">
              <ChatMessage role="user">Quais requisitos devo pôr no ETP de material de expediente?</ChatMessage>
              <ChatMessage
                time="14:02"
                notice="O conteúdo gerado deve ser conferido pelo responsável pela contratação."
                sources={<SourceList compact items={FONTES} />}
                actions={
                  <>
                    <Button variant="ghost" size="sm" icon="copy">
                      Copiar
                    </Button>
                    <Button variant="ghost" size="sm" icon="arrow-clockwise">
                      Gerar novamente
                    </Button>
                    <MessageFeedback onReport={() => undefined} />
                  </>
                }
              >
                Com base na demanda registrada <Cite n={1} /> e no DFD <Cite n={2} />, o ETP deve descrever a necessidade, a estimativa
                de quantidades e o levantamento de mercado.
              </ChatMessage>
              <ChatMessage loading />
            </div>
          </Exemplo>
          <Exemplo rotulo="ChatComposer — livre e ocupado">
            <div className="grid gap-3">
              <ChatComposer onSend={() => undefined} />
              <ChatComposer busy value="Explique o art. 23" onChange={() => undefined} />
            </div>
          </Exemplo>
          <Exemplo rotulo="PromptSuggestions — cartões e fichas">
            <div className="grid gap-3">
              <PromptSuggestions
                items={[
                  { icon: "file-text", label: "Gerar DFD", description: "A partir da demanda cadastrada" },
                  { icon: "scales", label: "Explicar art. 23 da Lei 14.133" },
                ]}
              />
              <PromptSuggestions chips items={[{ label: "Resumir o ETP" }, { label: "Listar riscos", icon: "warning" }]} />
            </div>
          </Exemplo>
          <Exemplo rotulo="AiProcessing">
            <AiProcessing
              title="Gerando ETP"
              progress={55}
              steps={[
                { label: "Lendo DFD e demanda", state: "done" },
                { label: "Consultando base de conhecimento", state: "active", meta: "12 trechos" },
                { label: "Redigindo seções", state: "pending" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="SourceList — completa">
            <SourceList items={FONTES} />
          </Exemplo>
          <Exemplo rotulo="ConversationList">
            <ConversationList
              activeId="c1"
              onNew={() => undefined}
              onSelect={() => undefined}
              groups={[
                { label: "Hoje", items: [{ id: "c1", title: "Requisitos do ETP de expediente", meta: "Proc. 2026/001234" }] },
                { label: "Esta semana", items: [{ id: "c2", title: "Dúvida sobre dispensa", icon: "scales" }] },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo={`AiDraftBlock — ${rascunho === "pending" ? "aguardando revisão" : rascunho === "accepted" ? "inserido" : "descartado"}`} largo>
            <AiDraftBlock
              target="ETP · Seção 4"
              title="Requisitos da contratação"
              meta="Baseado em 3 fontes"
              status={rascunho}
              onAccept={() => setRascunho("accepted")}
              onEdit={() => undefined}
              onReject={() => setRascunho("rejected")}
              onUndo={() => setRascunho("pending")}
            >
              Os materiais devem atender às normas da ABNT aplicáveis e ser entregues em até 15 dias.
            </AiDraftBlock>
          </Exemplo>
        </Grade>
      </Secao>

      <Secao
        id="price"
        tema={tema}
        titulo="Pesquisa de preços"
        descricao="Definir itens → Coletar preços → Triagem → Mapa de preços → Relatório. Sinal estatístico é avaliação preliminar; nada sai do cálculo sem motivo registrado."
      >
        <Grade>
          <Exemplo rotulo="SourcePicker" largo>
            <SourcePicker
              value={fontes}
              onChange={setFontes}
              sources={[
                { id: "pncp", name: "PNCP", description: "Contratações e atas registradas" },
                { id: "compras", name: "Compras.gov.br", description: "Dados abertos de compras federais" },
                { id: "painel", name: "Painel de Preços", description: "Fora do ar nesta demonstração", disabled: true },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="PriceItemNav">
            <PriceItemNav
              activeId={item}
              onSelect={setItem}
              items={[
                { id: 1, n: "01", title: "Papel A4 75 g/m²", unit: "CX", refs: 8, value: "R$ 22,33", status: "done" },
                { id: 2, n: "02", title: "Caneta esferográfica azul", unit: "UN", refs: 2, status: "review" },
                { id: 3, n: "03", title: "Grampeador de mesa", unit: "UN", refs: 0, status: "pending" },
                { id: 4, n: "04", title: "Toner compatível", unit: "UN", refs: 4, status: "blocked" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="ScreeningSummary — filtra a lista">
            <ScreeningSummary counts={{ total: 5, valid: 3, attention: 1, discrepant: 1, excluded: 0 }} active={filtro} onFilter={setFiltro} />
          </Exemplo>
          <Exemplo rotulo="PriceDispersion" largo>
            <PriceDispersion
              median={22}
              band={[16.5, 27.5]}
              values={[
                { label: "PNCP · Belém", value: 22 },
                { label: "PNCP · Ananindeua", value: 21.4 },
                { label: "Compras.gov.br", value: 23.1 },
                { label: "Pesquisa direta", value: 27.9, state: "attention" },
                { label: "PNCP · Estado", value: 48.9, state: "discrepant" },
                { label: "Fornecedor X", value: 12, state: "excluded" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="PriceDispersion — rótulos do servidor" largo>
            <PriceDispersion
              median={12}
              band={[8, 16]}
              labels={{ median: "R$ 12,00", band: ["R$ 8,00", "R$ 16,00"], scale: ["R$ 9,00", "R$ 50,00"] }}
              values={[
                { label: "Compras.gov · PA", value: 9, display: "R$ 9,00", state: "excluded" },
                { label: "PNCP · PA", value: 10, display: "R$ 10,00" },
                { label: "PNCP · PA", value: 11, display: "R$ 11,00" },
                { label: "PNCP", value: 12, display: "R$ 12,00" },
                { label: "Compras.gov · SP", value: 13, display: "R$ 13,00" },
                { label: "Compras.gov · SP", value: 40, display: "R$ 40,00", state: "discrepant" },
                { label: "PNCP · SP", value: 50, display: "R$ 50,00", state: "discrepant" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="PriceReferenceRow — todos os estados" largo>
            <div className="grid gap-2">
              <PriceReferenceRow
                title="Papel A4 75 g/m² — caixa com 10 resmas"
                source="PNCP"
                agency="Pref. de Belém · PA"
                date="12/09/2026"
                value="R$ 229,90"
                unitNote="R$ 22,99 / resma"
                status="compatible"
                selected={cesta[0]}
                onToggle={() => setCesta((c) => [!c[0], c[1], c[2]])}
              />
              <PriceReferenceRow
                title="Papel A4 75 g/m² — resma"
                source="Compras.gov.br"
                date="02/08/2026"
                value="R$ 23,10"
                status="attention"
                selected={cesta[1]}
                onToggle={() => setCesta((c) => [c[0], !c[1], c[2]])}
              />
              <PriceReferenceRow
                title="Papel A4 premium 90 g/m²"
                source="PNCP"
                agency="Governo do Estado"
                value="R$ 48,90"
                status="discrepant"
                selected={cesta[2]}
                onToggle={() => setCesta((c) => [c[0], c[1], !c[2]])}
                actions={
                  <Button size="sm" variant="ghost" icon="minus-circle" onClick={() => setExclusao("Papel A4 premium 90 g/m²")}>
                    Retirar
                  </Button>
                }
              />
              <PriceReferenceRow title="Papel reciclado" source="Pesquisa direta" value="R$ 12,00" status="excluded" />
              <PriceReferenceRow title="Papel A4 (sem análise)" value="R$ 21,80" status="pending" statusLabel="Aguardando triagem" />
            </div>
          </Exemplo>
          <Exemplo rotulo="PriceBasket">
            <Card title="Cesta de preços" actions={<Badge variant="brand">3 selecionadas</Badge>}>
              <PriceBasket
                total="R$ 22,33"
                onRemove={() => undefined}
                items={[
                  { source: "PNCP", detail: "Pref. de Belém · 12/09/2026", value: "R$ 22,99" },
                  { source: "PNCP", detail: "Pref. de Ananindeua · 30/08/2026", value: "R$ 21,40" },
                  { source: "Compras.gov.br", detail: "02/08/2026", value: "R$ 23,10" },
                ]}
              />
            </Card>
          </Exemplo>
          <Exemplo rotulo="PriceStats">
            <PriceStats
              items={[
                { label: "Referências", value: "8" },
                { label: "Menor", value: "R$ 21,40" },
                { label: "Média", value: "R$ 22,33", highlight: true, hint: "Método adotado" },
                { label: "Mediana", value: "R$ 22,10" },
                { label: "Maior", value: "R$ 23,10" },
                { label: "CV", value: "6,4%", help: "Coeficiente de variação" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="TraceabilityPanel — com e sem URL pública">
            <div className="grid gap-3">
              <TraceabilityPanel
                url="#"
                hash="a91f…3c07"
                status={
                  <Badge variant="warning" icon="warning-circle">
                    Exige conferência
                  </Badge>
                }
                fields={[
                  { label: "Fonte consultada", value: "PNCP — Contratações" },
                  { label: "Identificador", value: <span className="gc-mono">05.149.726/0001-04-1-000312/2026</span> },
                  { label: "Data", value: "12/09/2026" },
                ]}
              />
              <TraceabilityPanel fields={[{ label: "Fonte consultada", value: "Pesquisa direta com fornecedor" }]} />
            </div>
          </Exemplo>
          <Exemplo rotulo="ValidationSummary — impedimento, aviso e nota">
            <ValidationSummary
              onAction={() => undefined}
              issues={[
                { severity: "blocking", title: "Item 03 tem só 2 referências válidas", item: "Item 03", action: "Revisar" },
                { severity: "warning", title: "Referência com mais de 1 ano", detail: "Compras.gov.br · 02/08/2025" },
                { severity: "info", title: "Método por média em todos os itens" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="ValidationSummary — sem impedimentos">
            <ValidationSummary issues={[{ severity: "info", title: "Tudo pronto para emitir" }]} />
          </Exemplo>
          <Exemplo rotulo="PriceMapTable" largo>
            <PriceMapTable
              method="Média"
              total="R$ 11.866,25"
              sources={[
                { key: "r1", label: "Ref. 1", sub: "PNCP" },
                { key: "r2", label: "Ref. 2", sub: "Compras.gov.br" },
                { key: "r3", label: "Ref. 3", sub: "Pesquisa direta" },
              ]}
              rows={[
                {
                  id: 1,
                  n: "01",
                  desc: "Papel A4 75 g/m²",
                  unit: "CX",
                  qty: "500",
                  cells: { r1: { value: "R$ 22,99" }, r2: { value: "R$ 23,10" }, r3: { value: "R$ 12,00", excluded: true } },
                  estimate: "R$ 23,05",
                  total: "R$ 11.525,00",
                },
                {
                  id: 2,
                  n: "02",
                  desc: "Caneta esferográfica azul",
                  unit: "UN",
                  qty: "250",
                  cells: { r1: { value: "R$ 1,35" }, r2: { value: "R$ 1,38" } },
                  estimate: "R$ 1,37",
                  total: "R$ 341,25",
                },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="ExclusionDialog — motivo obrigatório (contido)" largo>
            <Palco alto>
              <ExclusionDialog
                contained
                open
                reference={{ title: exclusao ?? "Papel A4 premium 90 g/m²", value: "R$ 48,90" }}
                onCancel={() => setExclusao(null)}
                onConfirm={() => setExclusao(null)}
              />
            </Palco>
          </Exemplo>
        </Grade>
      </Secao>

      <Secao id="templates" tema={tema} titulo="Templates" descricao="PageHead, AppShell, AuthLayout, LandingHero e DocumentWorkspace: composições de página.">
        <Exemplo rotulo="PageHead">
          <PageHead
            eyebrow={<Badge variant="brand">Proc. 2026/001234</Badge>}
            title="Material de expediente"
            desc="Pesquisa de preços para as secretarias. Dados ilustrativos."
            actions={
              <>
                <Button variant="secondary" icon="download-simple">
                  Exportar
                </Button>
                <Button icon="arrows-clockwise">Coletar preços</Button>
              </>
            }
          />
        </Exemplo>
        <Exemplo rotulo="AppShell (contido)">
          <Palco alto>
            <div className="h-full [&_.gc-shell]:h-full [&_.gc-shell]:min-h-0 [&_.gc-shell\_\_nav]:h-full">
              <AppShell
                embedded
                brand={<Logo size={28} />}
                groups={MENU}
                footer={<UserCard name="Ana Souza" role="Administradora" avatar={<Avatar name="Ana Souza" />} />}
                topStart={<Breadcrumbs items={[{ label: "Processos", href: "#" }, { label: "Novo processo" }]} />}
                topEnd={<Avatar name="Ana Souza" />}
              >
                <PageHead title="Novo processo" desc="Comece registrando o órgão e o objeto da contratação. Os documentos vêm depois." />
                <Card>
                  <Field label="Quem está pedindo" htmlFor={`${tema}-orgao`}>
                    <Input id={`${tema}-orgao`} placeholder="Ex.: Secretaria Municipal de Saúde" />
                  </Field>
                </Card>
              </AppShell>
            </div>
          </Palco>
        </Exemplo>
        <Exemplo rotulo="DocumentWorkspace: salvo, com painel de revisão" largo>
          <Palco alto>
            <div className="flex h-full flex-col">
              <DocumentWorkspace
                back={
                  <Button size="sm" variant="ghost" icon="arrow-left">
                    Voltar ao processo
                  </Button>
                }
                kicker="DFD"
                title="Documento de Formalização da Demanda"
                meta={
                  <>
                    <Badge size="sm">Rascunho</Badge>
                    <Badge size="sm">Revisão 4</Badge>
                  </>
                }
                save={{ tone: "success", label: "Salvo · revisão 4" }}
                actions={
                  <Button size="sm" variant="subtle" icon="seal-check" aria-pressed>
                    Revisão
                  </Button>
                }
                panelTitle="Revisão e aprovação"
                panel={
                  <DataList
                    items={[
                      { label: "Situação", value: "Rascunho" },
                      { label: "Revisão salva", value: 4, numeric: true },
                    ]}
                  />
                }
              >
                <div className="grid h-full place-items-center text-sm text-[var(--text-tertiary)]">Área do editor nativo</div>
              </DocumentWorkspace>
            </div>
          </Palco>
        </Exemplo>
        <Exemplo rotulo="DocumentWorkspace: salvando" largo>
          <DocumentWorkspace
            back={
              <Button size="sm" variant="ghost" icon="arrow-left">
                Voltar ao processo
              </Button>
            }
            kicker="ETP"
            title="Estudo Técnico Preliminar"
            save={{ tone: "progress", label: "Salvando…" }}
          >
            <div className="h-16" />
          </DocumentWorkspace>
        </Exemplo>
        <Exemplo rotulo="DocumentWorkspace: conflito" largo>
          <DocumentWorkspace
            back={
              <Button size="sm" variant="ghost" icon="arrow-left">
                Voltar ao processo
              </Button>
            }
            kicker="TR"
            title="Termo de Referência"
            save={{ tone: "error", label: "Conflito de revisão" }}
            notice={
              <Alert variant="error" compact title="Outra sessão salvou este documento antes.">
                Seu rascunho continua no editor e não foi gravado.
              </Alert>
            }
          >
            <div className="h-16" />
          </DocumentWorkspace>
        </Exemplo>
        <Exemplo rotulo="LandingHero (contido)" largo>
          <Palco>
            <LandingHero
              embedded
              idPrefix={`${tema}-hero`}
              nav={[{ label: "Plataforma", href: "#" }]}
              signIn={{ label: "Acessar sistema", href: "#" }}
              explore={{ label: "Conhecer a plataforma", href: "#" }}
            />
          </Palco>
        </Exemplo>
        <Exemplo rotulo="PublicSection + PublicGrid + PublicFeature" largo>
          <PublicSection eyebrow="Plataforma" title="Seção do site público" lead="Abertura curta, até 62 caracteres por linha.">
            <PublicGrid>
              <PublicFeature icon="file-text" title="Recurso em destaque" wide href="#">
                Ocupa duas colunas e ganha o fundo de destaque.
              </PublicFeature>
              <PublicFeature icon="currency-circle-dollar" title="Recurso">
                Ícone, título e texto.
              </PublicFeature>
            </PublicGrid>
          </PublicSection>
        </Exemplo>
        <Exemplo rotulo="PublicSteps" largo>
          <PublicSteps
            steps={[
              { tag: "DFD", title: "Formalização da demanda", text: "Primeira etapa." },
              { tag: "ETP", title: "Estudo técnico preliminar" },
              { tag: "TR", title: "Termo de referência" },
            ]}
          />
        </Exemplo>
        <Exemplo rotulo="PublicFooter" largo>
          <PublicFooter
            columns={[
              { title: "Plataforma", links: [{ label: "Soluções", href: "#" }] },
              { title: "Institucional", links: [{ label: "Sobre", href: "#" }] },
              { title: "Acesso", links: [{ label: "Acessar sistema", href: "#" }] },
            ]}
            note="Linha final do rodapé."
          />
        </Exemplo>
        <Exemplo rotulo="AuthLayout (contido)">
          <Palco alto>
            <div className="h-full [&_.gc-auth]:h-full [&_.gc-auth]:min-h-0">
              <AuthLayout embedded>
                <div className="grid gap-1.5">
                  <h1>Entrar</h1>
                  <p className="text-secundario">Use a conta criada pelo administrador do seu órgão.</p>
                </div>
                <Field label="E-mail institucional" htmlFor={`${tema}-login`}>
                  <Input id={`${tema}-login`} size="lg" icon="envelope-simple" placeholder="usuario@orgao.example" />
                </Field>
                <Field label="Senha" htmlFor={`${tema}-senha`}>
                  <Input id={`${tema}-senha`} size="lg" icon="lock-simple" type="password" />
                </Field>
                <Checkbox label="Manter conectado" defaultChecked />
                <Button size="lg" block>
                  Entrar
                </Button>
              </AuthLayout>
            </div>
          </Palco>
        </Exemplo>
      </Secao>
    </>
  );
}
