const { Card, Button, Badge, ChatMessage, Cite, ChatComposer, PromptSuggestions, SourceList, ConversationList, ContextBar, AiDraftBlock, MessageFeedback, AiProcessing, SearchField, IconButton, EmptyState } = window.GovConectDesignSystem_76359c;
const CONVS = [{ label: "Hoje", items: [{ id: "c1", title: "Requisitos do ETP de computadores", meta: "Proc. 2026/001234" }, { id: "c2", title: "Mínimo de referências por item", meta: "Cotação · Materiais de expediente" }] }, { label: "Esta semana", items: [{ id: "c3", title: "Riscos de entrega parcelada", meta: "Proc. 2026/001198" }, { id: "c4", title: "Art. 75 — dispensa por valor", meta: "Sem processo vinculado" }] }];
const FONTES = [
  { n: 1, title: "Lei nº 14.133/2021, art. 18, §1º", meta: "Referência normativa", excerpt: "O estudo técnico preliminar… deverá conter a descrição da necessidade, os requisitos da contratação e a estimativa das quantidades." },
  { n: 2, title: "DFD — Aquisição de equipamentos de TI", meta: "Processo 2026/001234 · versão 2", excerpt: "40 computadores desktop tipo corporativo, com monitor de 24 polegadas, para as unidades administrativas." },
  { n: 3, title: "Parecer jurídico nº 128/2026 — SEJUR", meta: "Base de conhecimento · trecho 7 de 22", excerpt: "Recomenda-se vedar a indicação de marca, admitindo-se referência de desempenho mínimo." },
];
function GovBotScreen({ toast }) {
  const [active, setActive] = React.useState("c1");
  const [draft, setDraft] = React.useState("pending");
  const [msgs, setMsgs] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [ctx, setCtx] = React.useState(true);
  const fresh = active === "new";
  const ask = (t) => { setMsgs((m) => [...m, { role: "user", t }]); setBusy(true); setTimeout(() => { setBusy(false); setMsgs((m) => [...m, { role: "assistant", t }]); }, 1800); };
  return (
    <div className="kit-bot">
      <aside className="kit-bot__list"><ConversationList activeId={active} onNew={() => { setActive("new"); setMsgs([]); }} onSelect={(id) => { setActive(id); setMsgs([]); }} search={<SearchField size="sm" placeholder="Buscar conversas" />} groups={CONVS} /></aside>
      <section className="kit-bot__main">
        <div className="kit-bot__head">
          <div style={{ display: "grid", gap: 4, minWidth: 0 }}><h2 style={{ fontSize: 16 }}>{fresh ? "Nova conversa" : "Requisitos do ETP de computadores"}</h2>
            <ContextBar onAdd={() => toast("Selecione um documento", "Base de conhecimento ou processo")} items={[ctx && { kind: "process", icon: "folder-open", label: "Proc. 2026/001234 · Equipamentos de TI", onRemove: () => setCtx(false) }, { kind: "document", icon: "file-text", label: "DFD v2" }, { kind: "knowledge", icon: "books", label: "Base do órgão (38 documentos)" }, { kind: "law", icon: "scales", label: "Lei 14.133/2021" }].filter(Boolean)} /></div>
          <IconButton icon="dots-three-vertical" label="Mais opções" />
        </div>
        <div className="kit-bot__thread">
          {fresh && msgs.length === 0 && <div style={{ display: "grid", gap: 16, maxWidth: 640, margin: "24px auto", width: "100%" }}>
            <EmptyState icon="sparkle" title="Como posso ajudar no planejamento?" description="O GovBot responde com base no contexto acima e sempre indica as fontes. Revise antes de usar em documentos oficiais." />
            <PromptSuggestions onPick={(it) => ask(it.label)} items={[{ icon: "file-text", label: "Proponha os requisitos do ETP", description: "A partir do DFD vinculado" }, { icon: "warning", label: "Quais riscos devo mapear?", description: "Mapa de Riscos do processo" }, { icon: "currency-circle-dollar", label: "Resuma a pesquisa de preços", description: "Itens, método e pendências" }, { icon: "scales", label: "Explique o art. 23 da Lei 14.133" }]} />
          </div>}
          {!fresh && <>
            <ChatMessage role="user">Proponha a seção de requisitos da contratação para o ETP, com base no DFD.</ChatMessage>
            <ChatMessage time="14:02" notice="Proposta gerada a partir do contexto listado. Confira as fontes e ajuste antes de inserir." sources={<SourceList compact items={FONTES.map((f) => ({ n: f.n, title: f.title, meta: f.meta }))} />}
              actions={<><Button variant="ghost" size="sm" icon="copy">Copiar</Button><Button variant="ghost" size="sm" icon="arrow-clockwise">Gerar novamente</Button><MessageFeedback onReport={() => toast("Obrigado", "Descreva o problema na próxima mensagem")} /></>}>
              <p>O art. 18 exige que o ETP descreva os requisitos da contratação <Cite n={1} />. Com base no DFD <Cite n={2} /> e na orientação da SEJUR sobre indicação de marca <Cite n={3} />, preparei a proposta abaixo.</p>
              <div style={{ marginTop: 12 }}><AiDraftBlock target="ETP · Seção 4" title="Requisitos da contratação" meta="3 fontes · 182 palavras" status={draft} acceptedNote="Inserido no ETP · seção 4, por você às 14:05" onAccept={() => { setDraft("accepted"); toast("Trecho inserido no ETP", "Seção 4 · versão 4"); }} onEdit={() => toast("Abrindo editor", "ETP · seção 4")} onReject={() => setDraft("rejected")} onUndo={() => setDraft("pending")}>
                <p>Os equipamentos deverão atender aos seguintes requisitos mínimos de desempenho, vedada a indicação de marca:</p>
                <ul><li>Processador com, no mínimo, 6 núcleos e desempenho equivalente ou superior à referência de mercado;</li><li>16 GB de memória RAM e armazenamento SSD de 512 GB;</li><li>Monitor de 24 polegadas, resolução Full HD;</li><li><span className="gc-mark-review">Garantia on-site de 36 meses — confirmar com a área de TI.</span></li></ul>
              </AiDraftBlock></div>
            </ChatMessage>
          </>}
          {msgs.map((m, i) => m.role === "user" ? <ChatMessage key={i} role="user">{m.t}</ChatMessage> :
            <ChatMessage key={i} time="agora" notice="Confira as fontes antes de usar o conteúdo em documentos oficiais." sources={<SourceList compact items={[{ n: 1, title: "Lei nº 14.133/2021, art. 23", meta: "Referência normativa" }, { n: 2, title: "Cotação · Materiais de expediente", meta: "6 itens · 2 impedimentos" }]} />} actions={<><Button variant="ghost" size="sm" icon="copy">Copiar</Button><MessageFeedback /></>}>
              <p>O art. 23 estabelece os parâmetros da pesquisa de preços <Cite n={1} />. Na cotação vinculada, os itens 03 e 06 ainda impedem a emissão do relatório <Cite n={2} />.</p>
            </ChatMessage>)}
          {busy && <div style={{ maxWidth: 520, marginLeft: 44 }}><AiProcessing title="Consultando" steps={[{ label: "Lendo contexto do processo", state: "done" }, { label: "Buscando na base de conhecimento", state: "active", meta: "38 documentos" }, { label: "Redigindo resposta", state: "pending" }]} /></div>}
        </div>
        <div className="kit-bot__composer"><ChatComposer onSend={ask} busy={busy} /></div>
      </section>
      <aside className="kit-bot__sources">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}><h3>Fontes desta conversa</h3><Badge size="sm">{FONTES.length}</Badge></div>
        <SourceList items={FONTES.map((f) => ({ ...f, href: "#" }))} />
        <p className="gc-help">As fontes exibidas são as efetivamente usadas na resposta. O GovBot não acessa a internet fora das fontes oficiais configuradas.</p>
      </aside>
    </div>);
}
window.GovBotScreen = GovBotScreen;
