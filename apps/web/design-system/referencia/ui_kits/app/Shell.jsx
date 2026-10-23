const { Sidebar, UserCard, Avatar, Logo, Topbar, Breadcrumbs, IconButton, Badge, Button, Tooltip } = window.GovConectDesignSystem_76359c;
const NAV = [
  { items: [{ id: "inicio", icon: "house", label: "Início" }, { id: "processos", icon: "folder-open", label: "Processos", badge: 7 }, { id: "novo", icon: "plus-circle", label: "Novo processo" }, { id: "govbot", icon: "sparkle", label: "GovBot" }, { id: "demandas", icon: "tray", label: "Consolidar demandas" }] },
  { label: "Preparação", items: [{ id: "cotacoes", icon: "currency-circle-dollar", label: "Cotações" }, { id: "conhecimento", icon: "books", label: "Base de conhecimento" }, { id: "parecer", icon: "scales", label: "Parecer jurídico" }] },
  { label: "Gestão", items: [{ id: "governanca", icon: "shield-check", label: "Governança" }, { id: "admin", icon: "gear-six", label: "Administração" }] },
];
function AppShell({ route, go, crumbs, children, onGovBot, govbotOpen, onLogout, bleed }) {
  const [collapsed, setCollapsed] = React.useState(false);
  const groups = NAV.map((g) => ({ ...g, items: g.items.map((it) => ({ ...it, active: route === it.id || (route === "cotacao" && it.id === "cotacoes"), href: "#" + it.id, onClick: (e) => { e.preventDefault(); go(it.id); } })) }));
  return (
    <div className="gc-shell" style={{ height: "100vh", minHeight: 0 }}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} brand={<Logo size={28} withName={!collapsed} src="../../assets/logo-govconect-96.png" />} groups={groups}
        footer={<UserCard name="Antonio Ewerton Marinho" role="Administrador" avatar={<Avatar name="Antonio Marinho" />} action={!collapsed && <IconButton size="sm" icon="sign-out" label="Sair" onClick={onLogout} />} />} />
      <div className="gc-shell__main" style={{ overflow: "hidden" }}>
        <Topbar start={<Breadcrumbs items={crumbs} />} end={<>
          <Badge variant="success" dot>Salvo</Badge>
          {!bleed && <Button size="sm" variant={govbotOpen ? "subtle" : "secondary"} icon="sparkle" onClick={onGovBot}>GovBot</Button>}
          <IconButton icon="bell" label="Notificações" />
          <Avatar name="Antonio Marinho" />
        </>} />
        <div className="kit-body" style={{ display: "flex", flex: 1, minHeight: 0, position: "relative" }}>
          {bleed ? <main style={{ flex: 1, minWidth: 0, display: "flex" }}>{children}</main> : <main style={{ flex: 1, minWidth: 0, overflowY: "auto" }}><div style={{ maxWidth: 1200, margin: "0 auto", padding: "28px 32px 48px", display: "grid", gap: 24 }}>{children}</div></main>}
          {govbotOpen && !bleed && <window.GovBotPanel onClose={onGovBot} />}
        </div>
      </div>
    </div>);
}
function PageHead({ title, desc, actions, eyebrow }) {
  return <div className="gc-page-head"><div className="gc-page-head__titles">{eyebrow}<h1>{title}</h1>{desc && <p className="gc-page-head__desc">{desc}</p>}</div>{actions && <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div>}</div>;
}
Object.assign(window, { AppShell, PageHead });
