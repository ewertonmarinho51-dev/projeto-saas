const { KpiCard, Card, Button, StatusBadge, ProgressBar, Alert, Icon } = window.GovConectDesignSystem_76359c;
const PROCESSOS = [
  { id: 1, nome: "Aquisição de equipamentos de TI", org: "Secretaria Municipal de Administração", num: "2026/001234", status: "em_elaboracao", etapa: "Estudo Técnico Preliminar", feitos: 2, total: 6, quando: "há 2 h" },
  { id: 2, nome: "Fornecimento de materiais de expediente", org: "Secretaria Municipal de Educação", num: "2026/001198", status: "em_revisao", etapa: "Termo de Referência", feitos: 4, total: 6, quando: "ontem, 16:40" },
  { id: 3, nome: "Contratação de assessoria em licitações", org: "Gabinete do Prefeito", num: "2026/001102", status: "concluido", etapa: "Minuta do edital", feitos: 6, total: 6, quando: "21/10/2026" },
  { id: 4, nome: "Serviço de limpeza e conservação predial", org: "Secretaria Municipal de Saúde", num: "2026/001087", status: "rascunho", etapa: "Dados da demanda", feitos: 0, total: 6, quando: "20/10/2026" },
];
function ProcessRow({ p, onOpen }) {
  return (
    <a href="#" onClick={(e) => { e.preventDefault(); onOpen(p); }} className="gc-proc-row" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 180px auto 16px", alignItems: "center", gap: 20, padding: "14px 20px", color: "inherit", textDecoration: "none", borderTop: "1px solid var(--border-subtle)" }}>
      <span style={{ display: "grid", gap: 4, minWidth: 0 }}><span style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.nome}</span><span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{p.org} · <span className="gc-mono">Proc. {p.num}</span> · Atualizado {p.quando}</span></span>
      <ProgressBar size="sm" value={p.feitos} max={p.total} showValue={false} hint={p.feitos + " de " + p.total + " documentos · " + p.etapa} />
      <StatusBadge status={p.status} />
      <Icon name="caret-right" style={{ color: "var(--text-tertiary)" }} />
    </a>);
}
function HomeScreen({ go }) {
  return (<>
    <PageHead title="Bom dia, Antonio" desc="Prefeitura Municipal de Paragominas · 4 processos em andamento no seu órgão." actions={<><Button variant="secondary" icon="currency-circle-dollar" onClick={() => go("cotacao")}>Nova cotação</Button><Button icon="plus" onClick={() => go("novo")}>Novo processo</Button></>} />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 16 }}>
      <KpiCard label="Processos ativos" value="24" icon="folder-open" delta="+3 neste mês" footnote="no órgão" />
      <KpiCard label="Documentos gerados" value="61" icon="file-text" footnote="DFD, ETP, MR e TR" />
      <KpiCard label="Cotações concluídas" value="R$ 59,6" unit="mil" trend={[12, 18, 16, 24, 30, 34, 41, 59]} />
      <KpiCard label="Itens com pendência" value="3" icon="warning-circle" delta="2 discrepâncias" deltaTone="warning" />
    </div>
    <Alert variant="warning" title="2 itens com valores discrepantes" actions={<Button size="sm" variant="secondary" onClick={() => go("cotacao")}>Revisar triagem</Button>}>A cotação "Fornecimento de materiais de expediente" tem referências fora da faixa esperada.</Alert>
    <Card title="Processos recentes" subtitle="Os últimos atualizados no seu órgão." flush actions={<Button variant="link" size="sm" onClick={() => go("processos")}>Ver todos</Button>}>
      {PROCESSOS.map((p) => <ProcessRow key={p.id} p={p} onOpen={() => go(p.status === "rascunho" ? "novo" : "processos")} />)}
    </Card>
  </>);
}
Object.assign(window, { HomeScreen, PROCESSOS });
