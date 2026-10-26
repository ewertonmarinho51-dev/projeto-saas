const { ChatMessage, Cite, ChatComposer, PromptSuggestions, SourceList, Button, IconButton, Badge } = window.GovConectDesignSystem_76359c;
function GovBotPanel({ onClose }) {
  const [msgs, setMsgs] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const end = React.useRef(null);
  React.useEffect(() => { if (end.current) end.current.parentNode.scrollTop = 1e6; }, [msgs, busy]);
  const ask = (t) => { setMsgs((m) => [...m, { role: "user", t }]); setBusy(true); setTimeout(() => { setBusy(false); setMsgs((m) => [...m, { role: "assistant", t }]); }, 1200); };
  return (
    <aside className="kit-govbot" style={{ width: 400, maxWidth: "100%", flexShrink: 0, borderLeft: "1px solid var(--border-subtle)", background: "var(--surface-card)", display: "flex", flexDirection: "column", minHeight: 0 }} aria-label="GovBot">
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--border-subtle)" }}><span className="gc-msg__avatar"><i className="gc-icon ph-fill ph-sparkle" /></span><div style={{ flex: 1 }}><div style={{ fontWeight: 600 }}>GovBot</div><div style={{ fontSize: 12, color: "var(--text-secondary)" }}>Assistente da fase preparatória</div></div><IconButton size="sm" icon="x" label="Fechar GovBot" onClick={onClose} /></div>
      <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "grid", alignContent: "start", gap: 18 }}>
        {msgs.length === 0 && <div style={{ display: "grid", gap: 12 }}><p style={{ color: "var(--text-secondary)" }}>Pergunte sobre o processo aberto, a Lei 14.133 ou os documentos da base de conhecimento.</p><PromptSuggestions onPick={(it) => ask(it.label)} items={[{ icon: "file-text", label: "O que falta no DFD?", description: "Campos obrigatórios pendentes" }, { icon: "scales", label: "Explique o art. 23 da Lei 14.133", description: "Pesquisa de preços" }, { icon: "warning", label: "Por que a referência C é discrepante?" }]} /></div>}
        {msgs.map((m, i) => m.role === "user" ? <ChatMessage key={i} role="user">{m.t}</ChatMessage> :
          <ChatMessage key={i} time="agora" notice="Confira as fontes antes de usar o conteúdo em documentos oficiais." sources={<SourceList compact items={[{ n: 1, title: "Lei nº 14.133/2021, art. 23", meta: "Referência normativa" }, { n: 2, title: "Parecer jurídico nº 128/2026 — SEJUR", meta: "Base de conhecimento · 22 trechos" }]} />} actions={<><Button variant="ghost" size="sm" icon="copy">Copiar</Button><Button variant="ghost" size="sm" icon="arrow-clockwise">Gerar novamente</Button></>}>
            <p>O art. 23 define os parâmetros da pesquisa de preços <Cite n={1} />. No seu órgão, o parecer da SEJUR recomenda ao menos três referências válidas por item <Cite n={2} />.</p><p>O item 03 tem apenas 3 referências, uma delas sinalizada para conferência.</p>
          </ChatMessage>)}
        {busy && <ChatMessage loading />}
        <span ref={end} />
      </div>
      <div style={{ padding: 12, borderTop: "1px solid var(--border-subtle)" }}><ChatComposer onSend={ask} busy={busy} /></div>
    </aside>);
}
window.GovBotPanel = GovBotPanel;
