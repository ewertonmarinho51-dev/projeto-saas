const { Card, Button, SearchField, Select, Tabs, DataTable, Pagination, StatusBadge, Menu, IconButton, Tag, EmptyState, Dialog } = window.GovConectDesignSystem_76359c;
function ProcessesScreen({ go, toast }) {
  const [q, setQ] = React.useState("");
  const [tab, setTab] = React.useState("todos");
  const [sort, setSort] = React.useState({ key: "num", dir: "desc" });
  const [sel, setSel] = React.useState([]);
  const [del, setDel] = React.useState(null);
  const [rows, setRows] = React.useState(window.PROCESSOS);
  let list = rows.filter((p) => (tab === "todos" || (tab === "andamento" ? ["em_elaboracao", "em_revisao", "rascunho"].includes(p.status) : p.status === "concluido")) && (p.nome + p.org + p.num).toLowerCase().includes(q.toLowerCase()));
  list = [...list].sort((a, b) => (sort.dir === "asc" ? 1 : -1) * String(a[sort.key]).localeCompare(String(b[sort.key])));
  return (<>
    <PageHead title="Processos" desc="Todos os processos de contratação do órgão, com o andamento de cada documento." actions={<><Button variant="secondary" icon="upload-simple">Importar documento</Button><Button icon="plus" onClick={() => go("novo")}>Novo processo</Button></>} />
    <Tabs value={tab} onChange={setTab} tabs={[{ value: "todos", label: "Todos", count: rows.length }, { value: "andamento", label: "Em andamento", count: rows.filter((p) => p.status !== "concluido").length }, { value: "concluidos", label: "Concluídos", count: 1 }]} />
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <SearchField placeholder="Nome, órgão ou número" value={q} onChange={setQ} style={{ width: 320 }} shortcut="/" />
      <Select style={{ width: 220 }} options={["Secretaria: todas", "Administração", "Educação", "Saúde"]} />
      <Select style={{ width: 200 }} options={["Mais recentes", "Mais antigos", "Nome (A–Z)"]} />
      {q && <Tag keyLabel="Busca" label={q} onRemove={() => setQ("")} />}
      <span style={{ flex: 1 }} />
      {sel.length > 0 && <><span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{sel.length} selecionado(s)</span><Button size="sm" variant="secondary" icon="archive">Arquivar</Button></>}
    </div>
    <Card flush>
      {list.length === 0 ? <EmptyState icon="magnifying-glass" title="Nenhum processo encontrado" description="Revise a busca ou os filtros aplicados." actions={<Button variant="secondary" size="sm" onClick={() => setQ("")}>Limpar busca</Button>} /> :
      <div style={{ overflowX: "auto" }}><DataTable minWidth={860} selectable selected={sel} onSelect={setSel} sort={sort} onSort={setSort} rows={list} columns={[
        { key: "num", label: "Número", sortable: true, width: 120, render: (r) => <span className="gc-mono" style={{ color: "var(--text-secondary)" }}>{r.num}</span> },
        { key: "nome", label: "Objeto", sortable: true, render: (r) => <><a href="#" onClick={(e) => { e.preventDefault(); go("novo"); }} style={{ color: "var(--text-primary)", fontWeight: 500, textDecoration: "none" }}>{r.nome}</a><span className="gc-table__sub">{r.org}</span></> },
        { key: "etapa", label: "Etapa atual", render: (r) => <>{r.etapa}<span className="gc-table__sub">{r.feitos} de {r.total} documentos</span></> },
        { key: "quando", label: "Atualizado" },
        { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} size="sm" /> },
        { key: "a", label: <span className="gc-sr-only">Ações</span>, width: 48, render: (r) => <Menu align="end" trigger={({ toggle }) => <IconButton size="sm" icon="dots-three-vertical" label="Mais ações" onClick={toggle} />} items={[{ label: "Continuar de onde parou", icon: "arrow-right" }, { label: "Renomear", icon: "pencil-simple" }, { label: "Duplicar", icon: "copy" }, { separator: true }, { label: "Excluir", icon: "trash", danger: true, onSelect: () => setDel(r) }]} /> },
      ]} /></div>}
      <div className="gc-card__footer"><Pagination page={1} pageSize={10} total={list.length} /></div>
    </Card>
    <Dialog open={!!del} onClose={() => setDel(null)} tone="danger" icon="trash" size="sm" title="Excluir processo?" description={del ? "“" + del.nome + "” e os documentos gerados serão removidos. Esta ação não pode ser desfeita." : ""}
      footer={<><Button variant="secondary" onClick={() => setDel(null)}>Cancelar</Button><Button variant="danger" onClick={() => { setRows(rows.filter((x) => x.id !== del.id)); setDel(null); toast("Processo excluído"); }}>Excluir processo</Button></>} />
  </>);
}
window.ProcessesScreen = ProcessesScreen;
