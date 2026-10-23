"use client";

import { useState } from "react";

import {
  Avatar,
  Badge,
  Breadcrumbs,
  Button,
  Checkbox,
  DateField,
  Field,
  FileUpload,
  Icon,
  IconButton,
  Input,
  Logo,
  Menu,
  NavItem,
  Radio,
  RadioGroup,
  SearchField,
  Select,
  Sidebar,
  Stepper,
  Switch,
  Tabs,
  Textarea,
  Toolbar,
  ToolbarSeparator,
  ToolbarSpacer,
  Tooltip,
  Topbar,
  UserCard,
  type ButtonVariant,
  type SidebarGroup,
} from "../index";
import { Exemplo, Grade, Linha, Secao } from "./partes";

const VARIANTES: ButtonVariant[] = ["primary", "secondary", "subtle", "ghost", "link", "danger", "danger-subtle"];

const GRUPOS: SidebarGroup[] = [
  {
    items: [
      { id: "inicio", icon: "house", label: "Início", active: true },
      { id: "processos", icon: "folder-open", label: "Processos", badge: 7 },
      { id: "govbot", icon: "sparkle", label: "GovBot" },
    ],
  },
  {
    label: "Preparação",
    items: [
      { id: "cotacoes", icon: "currency-circle-dollar", label: "Cotações" },
      { id: "conhecimento", icon: "books", label: "Base de conhecimento" },
      { id: "parecer", icon: "scales", label: "Parecer jurídico" },
    ],
  },
  {
    label: "Gestão",
    items: [
      { id: "governanca", icon: "shield-check", label: "Governança" },
      { id: "admin", icon: "gear-six", label: "Administração" },
    ],
  },
];

export function GaleriaBase({ tema }: { tema: string }) {
  const [busca, setBusca] = useState("");
  const [nota, setNota] = useState("");
  const [recolhida, setRecolhida] = useState(false);
  const [etapa, setEtapa] = useState(2);
  const [cliques, setCliques] = useState(0);

  return (
    <>
      <Secao id="core" tema={tema} titulo="Core" descricao="Logo, Icon, Avatar e Tooltip.">
        <Grade>
          <Exemplo rotulo="Logo">
            <Linha>
              <Logo size={32} />
              <Logo size={40} withName={false} />
              <span className="inline-flex rounded-[var(--gc-radius-md)] bg-[var(--gc-gray-800)] p-2.5">
                <Logo size={28} withName={false} className="[&_img]:brightness-0 [&_img]:invert" />
              </span>
            </Linha>
          </Exemplo>
          <Exemplo rotulo="Avatar (sm, md, lg; com foto ausente)">
            <Linha>
              <Avatar size="sm" name="Ana Lima" />
              <Avatar name="Carlos Souza" />
              <Avatar size="lg" name="Maria Silva" />
            </Linha>
          </Exemplo>
          <Exemplo rotulo="Icon (bold, fill, regular; com rótulo)">
            <Linha>
              <Icon name="folder-open" size={20} />
              <Icon name="folder-open" size={20} weight="fill" />
              <Icon name="folder-open" size={20} weight="regular" />
              <Icon name="check-circle" size={20} weight="fill" label="Concluído" />
            </Linha>
          </Exemplo>
          <Exemplo rotulo="Tooltip (aberto, embaixo, com quebra)">
            <div className="flex flex-wrap items-center gap-10 pt-10 pb-12">
              <Tooltip content="Ajuda contextual" open>
                <IconButton size="sm" icon="question" label="Ajuda" />
              </Tooltip>
              <Tooltip content="Abaixo do controle" placement="bottom" open>
                <IconButton size="sm" icon="info" label="Informação" />
              </Tooltip>
              <Tooltip content="Passe o mouse ou foque">
                <IconButton size="sm" icon="trash" label="Excluir referência" />
              </Tooltip>
            </div>
          </Exemplo>
        </Grade>
      </Secao>

      <Secao id="actions" tema={tema} titulo="Actions" descricao="Button, IconButton, Menu e Toolbar. Um primário por região; rótulo é verbo.">
        <Exemplo rotulo="Button — variantes">
          <Linha>
            {VARIANTES.map((v) => (
              <Button key={v} variant={v}>
                {v === "danger" || v === "danger-subtle" ? "Excluir processo" : "Salvar"}
              </Button>
            ))}
          </Linha>
        </Exemplo>
        <Grade>
          <Exemplo rotulo="Button — tamanhos, ícone, carregando, desabilitado">
            <Linha>
              <Button size="sm" icon="plus">
                Novo
              </Button>
              <Button icon="upload-simple" variant="secondary">
                Importar planilha
              </Button>
              <Button size="lg" iconRight="arrow-right">
                Continuar
              </Button>
              <Button loading>Gerando ETP</Button>
              <Button disabled>Indisponível</Button>
            </Linha>
          </Exemplo>
          <Exemplo rotulo="Button — bloco e como link">
            <div className="grid gap-3">
              <Button block onClick={() => setCliques((c) => c + 1)}>
                Clicado {cliques} vez(es)
              </Button>
              <Button href="#" variant="secondary">
                Ver todos os processos
              </Button>
            </div>
          </Exemplo>
          <Exemplo rotulo="IconButton — variantes e tamanhos">
            <Linha>
              <IconButton icon="dots-three-vertical" label="Mais ações" />
              <IconButton icon="pencil-simple" label="Editar" variant="secondary" />
              <IconButton icon="plus" label="Adicionar" variant="primary" />
              <IconButton icon="trash" label="Excluir" variant="danger" />
              <IconButton icon="x" label="Fechar" size="sm" />
              <IconButton icon="gear-six" label="Configurar" size="lg" />
              <IconButton icon="bell" label="Avisos" disabled />
            </Linha>
          </Exemplo>
          <Exemplo rotulo="Menu — aberto, com grupo, atalho, desabilitado e perigo">
            <div className="flex flex-wrap items-start gap-6">
              <Menu
                inline
                items={[
                  { group: "Processo" },
                  { label: "Abrir", icon: "arrow-square-out" },
                  { label: "Duplicar", icon: "copy", shortcut: "Ctrl D" },
                  { label: "Arquivar", icon: "archive", disabled: true },
                  { separator: true },
                  { label: "Excluir", icon: "trash", danger: true },
                ]}
              />
              <Menu
                align="start"
                trigger={({ toggle, open }) => (
                  <Button variant="secondary" size="sm" iconRight="caret-down" onClick={toggle} aria-expanded={open}>
                    Mais ações
                  </Button>
                )}
                items={[{ label: "Exportar PDF", icon: "file-pdf" }, { label: "Exportar planilha", icon: "microsoft-excel-logo" }]}
              />
            </div>
          </Exemplo>
        </Grade>
        <Exemplo rotulo="Toolbar — com separador e espaçador; plain">
          <div className="grid gap-3">
            <Toolbar>
              <SearchField placeholder="Buscar item" size="sm" />
              <ToolbarSeparator />
              <Button variant="ghost" size="sm" icon="sort-ascending">
                Ordenar
              </Button>
              <ToolbarSpacer />
              <Button variant="secondary" size="sm" icon="funnel">
                Filtros
              </Button>
            </Toolbar>
            <Toolbar plain>
              <Button size="sm" icon="plus">
                Novo item
              </Button>
              <Button variant="ghost" size="sm" icon="download-simple">
                Baixar
              </Button>
            </Toolbar>
          </div>
        </Exemplo>
      </Secao>

      <Secao id="forms" tema={tema} titulo="Forms" descricao="Field envolve rótulo, controle e ajuda ou erro. Rótulo como pergunta; placeholder começa com “Ex.:”.">
        <Grade>
          <Exemplo rotulo="Input — padrão, ícone, obrigatório com ajuda">
            <Field label="E-mail institucional" htmlFor={`${tema}-email`} required help="Use o domínio do órgão.">
              <Input id={`${tema}-email`} icon="envelope-simple" placeholder="usuario@orgao.example" />
            </Field>
          </Exemplo>
          <Exemplo rotulo="Input — erro">
            <Field label="E-mail institucional" htmlFor={`${tema}-email-erro`} error="Informe o e-mail institucional.">
              <Input id={`${tema}-email-erro`} invalid defaultValue="usuario@" aria-describedby={`${tema}-email-erro-erro`} />
            </Field>
          </Exemplo>
          <Exemplo rotulo="Input — prefixo e sufixo, opcional">
            <Field label="Valor estimado" htmlFor={`${tema}-valor`} optional>
              <Input id={`${tema}-valor`} prefix="R$" suffix="UN" placeholder="0,00" inputMode="decimal" />
            </Field>
          </Exemplo>
          <Exemplo rotulo="Input — desabilitado, somente leitura, tamanhos">
            <div className="grid gap-2">
              <Input disabled defaultValue="Secretaria Municipal de Saúde" aria-label="Órgão (desabilitado)" />
              <Input readOnly defaultValue="Proc. 2026/001234" aria-label="Número do processo" />
              <Input size="sm" placeholder="Pequeno (32 px)" aria-label="Pequeno" />
              <Input size="lg" placeholder="Grande (44 px)" aria-label="Grande" />
            </div>
          </Exemplo>
          <Exemplo rotulo="SearchField — atalho e limpar">
            <SearchField placeholder="Nome, órgão ou objeto" shortcut="/" value={busca} onChange={setBusca} />
          </Exemplo>
          <Exemplo rotulo="Textarea — com contador">
            <Field label="Objeto da contratação" htmlFor={`${tema}-objeto`} required counter={`${nota.length} / 2.000`}>
              <Textarea
                id={`${tema}-objeto`}
                value={nota}
                maxLength={2000}
                onChange={(e) => setNota(e.target.value)}
                placeholder="Ex.: Aquisição de material de expediente para as secretarias."
              />
            </Field>
          </Exemplo>
          <Exemplo rotulo="Select — placeholder, inválido, pequeno">
            <div className="grid gap-2">
              <Select placeholder="Selecione uma opção" options={["Materiais", "Serviços", "Obras"]} aria-label="Natureza" />
              <Select invalid options={[{ value: "x", label: "Opção inválida" }]} aria-label="Natureza (inválida)" />
              <Select size="sm" options={["Média", "Mediana", "Menor preço"]} aria-label="Método" />
            </div>
          </Exemplo>
          <Exemplo rotulo="DateField — simples e intervalo">
            <div className="grid gap-2">
              <Field label="Para quando você precisa" htmlFor={`${tema}-prazo`}>
                <DateField id={`${tema}-prazo`} />
              </Field>
              <Field label="Período da contratação">
                <DateField range />
              </Field>
            </div>
          </Exemplo>
          <Exemplo rotulo="Checkbox — marcado, misto, desabilitado, inválido">
            <div className="grid gap-3">
              <Checkbox label="Pesquisar apenas referências rastreáveis" description="Só entra o que tem link para o registro original." defaultChecked />
              <Checkbox label="Selecionar todos" indeterminate />
              <Checkbox label="Opção indisponível" disabled />
              <Checkbox label="Li e conferi os valores" invalid />
            </div>
          </Exemplo>
          <Exemplo rotulo="Radio e RadioGroup — coluna, linha, opção desabilitada">
            <div className="grid gap-4">
              <RadioGroup
                name={`${tema}-metodo`}
                legend="Método de cálculo"
                defaultValue="media"
                row
                options={[
                  { value: "media", label: "Média" },
                  { value: "mediana", label: "Mediana" },
                  { value: "menor", label: "Menor preço", disabled: true },
                ]}
              />
              <RadioGroup
                name={`${tema}-fonte`}
                legend="Fonte principal"
                options={[
                  { value: "pncp", label: "PNCP", description: "Contratações e atas registradas" },
                  { value: "compras", label: "Compras.gov.br" },
                ]}
              />
              <Radio name={`${tema}-solto`} label="Radio avulso" defaultChecked />
            </div>
          </Exemplo>
          <Exemplo rotulo="Switch — ligado, rótulo antes, desabilitado">
            <div className="grid gap-3">
              <Switch label="Mostrar apenas referências rastreáveis" defaultChecked />
              <Switch label="Notificar por e-mail" labelPosition="start" />
              <Switch label="Indisponível" disabled />
            </div>
          </Exemplo>
          <Exemplo rotulo="FileUpload — enviando e concluído" largo>
            <FileUpload
              files={[
                { name: "Planilha_itens.xlsx", icon: "microsoft-excel-logo", progress: 45 },
                { name: "Parecer_Juridico_128.pdf", meta: "PDF · 2,8 MB", icon: "file-pdf", status: <Badge variant="success">Indexado</Badge> },
              ]}
              onFiles={() => undefined}
              onRemove={() => undefined}
            />
          </Exemplo>
        </Grade>
      </Secao>

      <Secao id="navigation" tema={tema} titulo="Navigation" descricao="Sidebar, NavItem, UserCard, Topbar, Breadcrumbs, Tabs e Stepper.">
        <Grade>
          <Exemplo rotulo="Sidebar — expandida e recolhida (botão alterna)">
            <div className="flex h-[calc(var(--space-16)*8)] gap-3 overflow-hidden rounded-[var(--gc-radius-lg)] border border-linha">
              <Sidebar
                collapsed={recolhida}
                onToggle={() => setRecolhida((r) => !r)}
                brand={<Logo size={28} />}
                groups={GRUPOS}
                footer={<UserCard name="Ana Souza" role="Administradora" avatar={<Avatar name="Ana Souza" />} />}
              />
            </div>
          </Exemplo>
          <Exemplo rotulo="NavItem e UserCard soltos">
            <div className="grid gap-2 rounded-[var(--gc-radius-lg)] border border-linha bg-superficie p-3">
              <NavItem icon="folder-open" label="Processos" badge={3} />
              <NavItem icon="house" label="Início" active />
              <UserCard
                name="Carlos Souza"
                role="Servidor"
                avatar={<Avatar name="Carlos Souza" />}
                action={<IconButton size="sm" icon="sign-out" label="Sair" />}
              />
            </div>
          </Exemplo>
          <Exemplo rotulo="Topbar com Breadcrumbs" largo>
            <div className="overflow-hidden rounded-[var(--gc-radius-lg)] border border-linha">
              <Topbar
                start={<Breadcrumbs items={[{ label: "Cotações", href: "#" }, { label: "Material de expediente", href: "#" }, { label: "Triagem" }]} />}
                end={
                  <>
                    <Badge variant="success" dot>
                      Salvo
                    </Badge>
                    <Button size="sm" variant="secondary" icon="sparkle">
                      GovBot
                    </Button>
                    <IconButton icon="bell" label="Notificações" />
                    <Avatar name="Ana Souza" />
                  </>
                }
              />
            </div>
          </Exemplo>
          <Exemplo rotulo="Tabs — linha (ícone, contagem, desabilitada)">
            <Tabs
              ariaLabel="Seções do processo"
              tabs={[
                { value: "geral", label: "Visão geral", icon: "house" },
                { value: "documentos", label: "Documentos", count: 4 },
                { value: "clausulas", label: "Catálogo de cláusulas", count: 12 },
                { value: "historico", label: "Histórico", disabled: true },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="Tabs — segmentada">
            <Tabs
              variant="segmented"
              ariaLabel="Documento"
              tabs={[
                { value: "dfd", label: "DFD" },
                { value: "etp", label: "ETP" },
                { value: "tr", label: "TR" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="Stepper — atual, concluídas clicáveis" largo>
            <Stepper
              current={etapa}
              onStepClick={setEtapa}
              steps={[
                { label: "Definir itens", meta: "7 itens" },
                { label: "Coletar preços" },
                { label: "Triagem" },
                { label: "Mapa de preços" },
                { label: "Relatório final" },
              ]}
            />
          </Exemplo>
          <Exemplo rotulo="Stepper — com pendência" largo>
            <Stepper
              ariaLabel="Fase preparatória"
              steps={[
                { label: "Demanda", state: "done" },
                { label: "DFD", state: "done" },
                { label: "ETP", state: "error", meta: "2 seções sem revisão" },
                { label: "Mapa de Riscos", state: "todo" },
                { label: "TR", state: "todo" },
                { label: "Edital", state: "todo" },
              ]}
            />
          </Exemplo>
        </Grade>
      </Secao>
    </>
  );
}
