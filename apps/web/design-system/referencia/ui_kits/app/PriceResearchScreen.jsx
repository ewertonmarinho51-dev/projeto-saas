const { Card, Button, Badge, StatusBadge, Stepper, DataList, SearchField, PriceReferenceRow, PriceBasket, PriceStats, TraceabilityPanel, SourcePicker, Alert, Accordion, Tabs, BarChart, Dialog, PriceItemNav, PriceDispersion, ScreeningSummary, ExclusionDialog } = window.GovConectDesignSystem_76359c;
const ITENS = [
  { id: 1, n: "01", title: "Papel A4 branco 75 g/m²", unit: "CX", refs: 5, status: "review" },
  { id: 2, n: "02", title: "Caneta esferográfica azul", unit: "UN", refs: 11, value: "R$ 1,38", status: "done" },
  { id: 3, n: "03", title: "Pasta arquivo A-Z", unit: "UN", refs: 2, status: "blocked" },
  { id: 4, n: "04", title: "Grampeador de mesa 26/6", unit: "UN", refs: 31, value: "R$ 42,10", status: "done" },
  { id: 5, n: "05", title: "Clipes metálicos nº 2/0", unit: "CX", refs: 3, value: "R$ 6,90", status: "done" },
  { id: 6, n: "06", title: "Livro ata 100 folhas", unit: "UN", refs: 0, status: "pending" },
];
const REFS0 = [
  { id: "a", t: "Papel A4 75 g/m², caixa c/ 10 resmas de 500 fls", src: "PNCP", ag: "Pref. de Belém · PA", dt: "12/09/2026", v: 22.0, st: "compatible", sel: true },
  { id: "b", t: "Papel sulfite A4 210×297 mm, 75 g/m², branco", src: "Compras.gov.br", ag: "UFPA · PA", dt: "03/08/2026", v: 21.5, st: "compatible", sel: true },
  { id: "c", t: "Papel A4 alcalino 75 g/m², resma 500 fls", src: "PNCP", ag: "Pref. de Marabá · PA", dt: "28/07/2026", v: 23.5, st: "compatible", sel: true },
  { id: "d", t: "Papel A4 reciclado 75 g/m²", src: "Painel de Preços", ag: "IFPA · PA", dt: "15/06/2026", v: 19.03, st: "attention", sel: false },
  { id: "e", t: "Papel A4 premium 90 g/m², resma", src: "PNCP", ag: "Gov. do Estado · PA", dt: "02/05/2026", v: 48.9, st: "discrepant", sel: false },
];
const MOTIVOS = { objeto: "Objeto não comparável", unidade: "Unidade divergente", data: "Data fora do período", valor: "Valor inexequível ou excessivo", outro: "Outro motivo" };
const brl = (n) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const refState = (r) => r.reason ? "excluded" : r.sel ? "valid" : r.st === "discrepant" ? "discrepant" : r.st === "attention" ? "attention" : "excluded";
function PriceResearchScreen({ toast }) {
  const [stage, setStage] = React.useState(2);
  const [item, setItem] = React.useState(1);
  const [refs, setRefs] = React.useState(REFS0);
  const [src, setSrc] = React.useState(["pncp", "compras", "painel"]);
  const [trace, setTrace] = React.useState(null);
  const [excl, setExcl] = React.useState(null);
  const [filter, setFilter] = React.useState(null);
  const [view, setView] = React.useState("triagem");
  const sel = refs.filter((r) => r.sel);
  const vals = sel.map((r) => r.v).sort((a, b) => a - b);
  const media = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  const mediana = vals.length ? (vals.length % 2 ? vals[(vals.length - 1) / 2] : (vals[vals.length / 2 - 1] + vals[vals.length / 2]) / 2) : 0;
  const sd = vals.length ? Math.sqrt(vals.reduce((a, b) => a + (b - media) ** 2, 0) / vals.length) : 0;
  const allV = refs.map((r) => r.v).sort((a, b) => a - b); const medAll = allV[Math.floor(allV.length / 2)];
  const counts = { total: refs.length, valid: sel.length, attention: refs.filter((r) => refState(r) === "attention").length, discrepant: refs.filter((r) => refState(r) === "discrepant").length, excluded: refs.filter((r) => refState(r) === "excluded").length };
  const toggle = (r) => { if (r.sel) setExcl(r); else setRefs(refs.map((x) => x.id === r.id ? { ...x, sel: true, reason: null } : x)); };
  const confirmExcl = ({ reason, note }) => { setRefs(refs.map((x) => x.id === excl.id ? { ...x, sel: false, reason, note } : x)); toast("Referência retirada do cálculo", MOTIVOS[reason]); setExcl(null); };
  const cur = ITENS.find((i) => i.id === item);
  const shown = refs.filter((r) => !filter || filter === "total" || refState(r) === filter);
  const goStage = (i) => { if (i >= 2) setStage(i); else toast("Etapa já concluída", i === 0 ? "7 itens definidos" : "Coleta de 18/10/2026"); };
  return (<>
    <PageHead eyebrow={<div style={{ display: "flex", gap: 6 }}><Badge variant="info" size="sm">Em elaboração</Badge><Badge variant="neutral" size="sm">Lei nº 14.133/2021, art. 23</Badge></div>} title="Fornecimento de materiais de expediente" actions={<><Button variant="secondary" icon="file-pdf" onClick={() => setStage(4)}>Relatório</Button><Button icon="arrows-clockwise" onClick={() => toast("Coleta iniciada", "PNCP, Compras.gov.br e Painel de Preços")}>Coletar preços</Button></>} />
    <DataList stacked items={[{ label: "Itens", value: "6" }, { label: "Com preços suficientes", value: "4 de 6" }, { label: "Data-base", value: "18/10/2026" }, { label: "Responsável", value: "Maria Silva" }, { label: "Estimativa (itens concluídos)", value: "R$ 18.535,00", numeric: true }]} />
    <Card><div style={{ padding: "4px 0" }}><Stepper current={stage} onStepClick={goStage} steps={[{ label: "Definir itens" }, { label: "Coletar preços" }, { label: "Triagem" }, { label: "Mapa de preços" }, { label: "Relatório final" }]} /></div></Card>
    {stage === 3 && <window.PriceMapStage go={setStage} />}
    {stage === 4 && <window.ReportStage go={(s, it) => { setStage(s); if (it) setItem(it); }} toast={toast} />}
    {stage === 2 && <div className="kit-3col">
      <Card title="Itens" flush actions={<Badge size="sm">{ITENS.length}</Badge>}>
        <div style={{ padding: "0 8px 12px", display: "grid", gap: 8 }}><div style={{ padding: "0 4px" }}><SearchField size="sm" placeholder="Buscar item" /></div><PriceItemNav items={ITENS} activeId={item} onSelect={setItem} /></div>
      </Card>
      <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}><h2>Item {cur.n} · {cur.title}</h2><span style={{ display: "flex", gap: 8 }}><Badge variant="neutral" size="sm">500 {cur.unit}</Badge><StatusBadge status={cur.status === "done" ? "concluido" : cur.status === "blocked" ? "bloqueado" : cur.status === "pending" ? "pendente" : "em_revisao"} /></span></div>
        <Tabs value={view} onChange={setView} tabs={[{ value: "triagem", label: "Triagem", count: refs.length }, { value: "fontes", label: "Fontes" }, { value: "comparativo", label: "Comparativo" }]} />
        {view === "triagem" && <>
          <ScreeningSummary counts={counts} active={filter} onFilter={setFilter} />
          <Card title="Dispersão das referências" subtitle="Faixa de referência: mediana ± 25% — sinalização preliminar." actions={<Badge variant="warning" caps size="sm">Avaliação preliminar</Badge>}>
            <PriceDispersion format={brl} median={medAll} band={[medAll * 0.75, medAll * 1.25]} values={refs.map((r) => ({ label: r.src + " · " + r.ag, value: r.v, state: refState(r) }))} />
          </Card>
          {counts.discrepant > 0 && <Alert variant="warning" compact title={counts.discrepant + " referência discrepante"}>Está 122% acima da mediana. Verifique a especificação antes de decidir — a sinalização não exclui o preço automaticamente.</Alert>}
          <div style={{ display: "grid", gap: 8 }}>{shown.map((r) => { const s = refState(r); return <PriceReferenceRow key={r.id} selected={r.sel} onToggle={() => toggle(r)} title={r.t} source={r.src} agency={r.ag} date={r.dt} value={brl(r.v)} unitNote="por resma" status={s === "valid" ? "compatible" : s} statusLabel={r.reason ? MOTIVOS[r.reason] : undefined} actions={<button type="button" className="gc-iconbtn gc-iconbtn--sm" aria-label="Ver origem" title="Ver origem" onClick={() => setTrace(r)}><i className="gc-icon ph-bold ph-path" /></button>} />; })}
            {shown.length === 0 && <p className="gc-help" style={{ padding: 12 }}>Nenhuma referência neste filtro.</p>}</div>
          <Accordion items={[{ title: "Entenda o cálculo", meta: "Média aritmética", content: "O preço estimado é a média das referências mantidas na cesta após a triagem. Referências discrepantes não entram automaticamente — a decisão é do responsável e fica registrada no relatório." }, { title: "Detalhes da busca", meta: "5 considerados · 15 abaixo do piso", content: "Busca em 18/10/2026 01:11 (horário de Brasília) · termo: “papel A4 75g” · CATMAT 461195." }]} />
          <div style={{ display: "flex", justifyContent: "flex-end" }}><Button iconRight="arrow-right" onClick={() => setStage(3)}>Avançar para o mapa de preços</Button></div>
        </>}
        {view === "fontes" && <Card title="Fontes consultadas" subtitle="Selecione onde a próxima coleta vai buscar."><SourcePicker value={src} onChange={setSrc} sources={[{ id: "pncp", name: "PNCP", description: "Contratações e atas registradas" }, { id: "compras", name: "Compras.gov.br", description: "Dados abertos de compras federais" }, { id: "painel", name: "Painel de Preços", description: "Homologações da Adm. federal" }, { id: "direta", name: "Pesquisa direta", description: "Propostas de fornecedores" }, { id: "midia", name: "Mídia especializada", description: "Indisponível neste órgão", disabled: true }]} /></Card>}
        {view === "comparativo" && <Card title="Comparativo entre fontes" subtitle="Preço unitário médio por fonte"><BarChart format={brl} data={[{ label: "PNCP", value: 31.47 }, { label: "Compras.gov.br", value: 21.5 }, { label: "Painel de Preços", value: 19.03 }]} /></Card>}
      </div>
      <div className="kit-aside">
        <Card title="Cesta de preços" subtitle="Referências que entram no cálculo." actions={<Badge variant="brand" size="sm">{sel.length}</Badge>}>
          <PriceBasket items={sel.map((r) => ({ source: r.src, detail: r.ag + " · " + r.dt, value: brl(r.v) }))} onRemove={(i) => toggle(sel[i])} total={vals.length ? brl(media) : "—"} />
        </Card>
        <PriceStats items={[{ label: "Média", value: brl(media), highlight: true, hint: "Método adotado" }, { label: "Mediana", value: brl(mediana) }, { label: "Coef. variação", value: media ? (sd / media * 100).toFixed(1).replace(".", ",") + "%" : "—", help: "Desvio-padrão ÷ média" }, { label: "Total do item", value: brl(media * 500), hint: "500 CX" }]} />
        <Button block variant="secondary" icon="check" disabled={sel.length < 3} onClick={() => toast("Item concluído", "Preço estimado " + brl(media))}>Concluir item</Button>
        {sel.length < 3 && <p className="gc-help">São necessárias ao menos 3 referências na cesta.</p>}
      </div>
    </div>}
    <ExclusionDialog open={!!excl} reference={excl ? { title: excl.t, value: brl(excl.v) } : null} onCancel={() => setExcl(null)} onConfirm={confirmExcl} />
    <Dialog open={!!trace} onClose={() => setTrace(null)} icon="path" title="Rastreabilidade da referência" description="Inspecione a origem antes de utilizar o preço." footer={<Button variant="secondary" onClick={() => setTrace(null)}>Fechar</Button>}>
      {trace && <TraceabilityPanel url="#" urlLabel="Consultar registro original" hash="a91f·3c07·e2b4" status={<Badge variant="warning" icon="warning-circle" size="sm">Exige conferência</Badge>} fields={[{ label: "Fonte consultada", value: trace.src }, { label: "Identificador do registro", value: <span className="gc-mono">05149726000104-1-000312/2026</span> }, { label: "Órgão responsável", value: trace.ag }, { label: "Data do registro", value: trace.dt }, { label: "Objeto relacionado", value: trace.t }, { label: "Valor unitário", value: brl(trace.v) }].concat(trace.reason ? [{ label: "Motivo da retirada", value: MOTIVOS[trace.reason] + (trace.note ? " — " + trace.note : "") }] : [])} />}
    </Dialog>
  </>);
}
window.PriceResearchScreen = PriceResearchScreen;
