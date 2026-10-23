const { Card, Button, Badge, PriceMapTable, ValidationSummary, Checkbox, RadioGroup, Field, Input, Alert, DataList, AiProcessing } = window.GovConectDesignSystem_76359c;
function PriceMapStage({ go }) {
  const c = (v, ex) => ({ value: v, excluded: ex });
  return (<>
    <Alert variant="info" compact>Mapa consolidado das referências mantidas após a triagem. Valores riscados ficaram fora do cálculo, com motivo registrado.</Alert>
    <div className="gc-page-head"><div className="gc-page-head__titles"><h2>Mapa de preços</h2><p className="gc-page-head__desc">Preço unitário por referência · método: média</p></div><Button size="sm" variant="secondary" icon="microsoft-excel-logo">Exportar XLSX</Button></div>
      <PriceMapTable method="Média" total="R$ 18.535,00" sources={[{ key: "r1", label: "Ref. 1", sub: "PNCP" }, { key: "r2", label: "Ref. 2", sub: "Compras.gov.br" }, { key: "r3", label: "Ref. 3", sub: "PNCP" }, { key: "r4", label: "Ref. 4", sub: "Painel de Preços" }, { key: "r5", label: "Ref. 5", sub: "PNCP" }]}
        rows={[
          { id: 1, n: "01", desc: "Papel A4 branco 75 g/m²", unit: "CX", qty: "500", cells: { r1: c("R$ 22,00"), r2: c("R$ 21,50"), r3: c("R$ 23,50"), r4: c("R$ 19,03", true), r5: c("R$ 48,90", true) }, estimate: "R$ 22,33", total: "R$ 11.165,00" },
          { id: 2, n: "02", desc: "Caneta esferográfica azul", unit: "UN", qty: "1.200", cells: { r1: c("R$ 1,35"), r2: c("R$ 1,42"), r3: c("R$ 1,37"), r4: c("R$ 1,39") }, estimate: "R$ 1,38", total: "R$ 1.656,00" },
          { id: 3, n: "03", desc: "Pasta arquivo A-Z", unit: "UN", qty: "80", cells: { r1: c("R$ 18,40"), r2: c("R$ 17,90") }, estimate: <span style={{ color: "var(--error-fg)" }}>Insuficiente</span>, total: "—" },
          { id: 4, n: "04", desc: "Grampeador de mesa 26/6", unit: "UN", qty: "100", cells: { r1: c("R$ 41,80"), r2: c("R$ 42,40"), r3: c("R$ 42,10") }, estimate: "R$ 42,10", total: "R$ 4.210,00" },
          { id: 5, n: "05", desc: "Clipes metálicos nº 2/0", unit: "CX", qty: "220", cells: { r1: c("R$ 6,80"), r2: c("R$ 7,10"), r3: c("R$ 6,80") }, estimate: "R$ 6,90", total: "R$ 1.518,00" },
        ]} />
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}><Button variant="secondary" icon="arrow-left" onClick={() => go(2)}>Voltar à triagem</Button><Button iconRight="arrow-right" onClick={() => go(4)}>Revisar e emitir relatório</Button></div>
  </>);
}
function ReportStage({ go, toast }) {
  const [fixed, setFixed] = React.useState(false);
  const [busy, setBusy] = React.useState(0);
  const issues = [
    !fixed && { severity: "blocking", title: "Item 03 tem apenas 2 referências válidas", detail: "O mínimo configurado pelo órgão é 3. Colete novas referências ou justifique a pesquisa com menos fontes.", item: "Item 03", action: "Resolver" },
    { severity: "blocking", title: "Item 06 ainda não foi pesquisado", detail: "Nenhuma referência coletada para “Livro ata 100 folhas”.", item: "Item 06", action: "Coletar" },
    { severity: "warning", title: "1 referência com mais de 180 dias", detail: "Painel de Preços · 15/06/2026 — já retirada do cálculo do item 01.", item: "Item 01" },
    { severity: "warning", title: "Coeficiente de variação acima de 25% no item 04", detail: "Considere revisar a homogeneidade das referências.", item: "Item 04" },
    { severity: "info", title: "Relatório inclui as justificativas de exclusão registradas na triagem" },
  ].filter(Boolean);
  const blocking = issues.some((i) => i.severity === "blocking");
  const emit = () => { setBusy(1); setTimeout(() => setBusy(2), 1200); setTimeout(() => { setBusy(0); toast("Relatório emitido", "Identificador 7c2e·19ab — PDF disponível"); }, 2400); };
  return (
    <div className="kit-2col">
      <ValidationSummary issues={issues} onAction={(it) => { if (it.item === "Item 03") { setFixed(true); toast("Justificativa registrada", "Item 03 · pesquisa com 2 fontes"); } else go(2, 6); }} />
      <div style={{ display: "grid", gap: 16 }}>
        <Card title="Conteúdo do relatório" divided>
          <div style={{ display: "grid", gap: 12 }}>
            <Checkbox label="Mapa de preços" defaultChecked />
            <Checkbox label="Memória de cálculo por item" description="Método, estatísticas e referências" defaultChecked />
            <Checkbox label="Justificativas de exclusão" defaultChecked />
            <Checkbox label="Links para os registros originais" defaultChecked />
            <RadioGroup name="fmt" legend="Formato" row defaultValue="PDF" options={["PDF", "DOCX", "XLSX"]} />
            <Field label="Assinatura" help="Nome que aparece no rodapé."><Input defaultValue="Maria Silva — Diretora de Compras" /></Field>
          </div>
        </Card>
        {busy ? <AiProcessing title="Emitindo relatório" progress={busy === 1 ? 40 : 85} steps={[{ label: "Consolidando mapa de preços", state: "done" }, { label: "Gerando memória de cálculo", state: busy === 1 ? "active" : "done" }, { label: "Montando PDF", state: busy === 2 ? "active" : "pending" }]} /> :
        <Button size="lg" icon="file-pdf" disabled={blocking} onClick={emit}>Emitir relatório</Button>}
        {blocking && <p className="gc-help">Resolva os impedimentos para emitir. Avisos não bloqueiam a emissão.</p>}
      </div>
    </div>);
}
Object.assign(window, { PriceMapStage, ReportStage });
