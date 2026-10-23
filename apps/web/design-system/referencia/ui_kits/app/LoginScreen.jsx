const { Logo, Field, Input, Button, Checkbox, Alert } = window.GovConectDesignSystem_76359c;
function LoginScreen({ onLogin }) {
  const [show, setShow] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const [authErr, setAuthErr] = React.useState(false);
  const [email, setEmail] = React.useState("antonio.marinho@paragominas.pa.gov.br");
  const submit = (e) => { e.preventDefault(); setAuthErr(false); if (!email.includes("@")) { setErr("Informe o e-mail institucional."); return; } setErr(null); setLoading(true); setTimeout(() => { if (!email.endsWith(".gov.br")) { setLoading(false); setAuthErr(true); return; } onLogin(); }, 700); };
  return (
    <main style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,520px)", minHeight: "100vh" }}>
      <section style={{ position: "relative", overflow: "hidden", borderRight: "1px solid var(--border-subtle)", background: "var(--bg-app) url(../../assets/fundo-hero-claro.png) center/cover" }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", height: "100%", padding: 48 }}>
          <Logo size={32} src="../../assets/logo-govconect-96.png" />
          <div style={{ maxWidth: 460, display: "grid", gap: 16 }}>
            <img src="../../assets/logo-govconect.png" width="88" height="88" alt="" />
            <p style={{ font: "600 30px/1.2 var(--font-sans)", letterSpacing: "-0.02em" }}>Planejamento público, com método.</p>
            <p style={{ font: "var(--type-body-lg)", color: "var(--text-secondary)" }}>Elabore os documentos da fase preparatória em um fluxo seguro, rastreável e alinhado à Lei nº 14.133/2021 — com revisão humana e preços de fonte verificável.</p>
          </div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>Lei 14.133/2021 · fase preparatória</p>
        </div>
      </section>
      <section style={{ display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface-card)", padding: "48px 40px" }}>
        <form onSubmit={submit} style={{ width: "100%", maxWidth: 360, display: "grid", gap: 20 }}>
          <div style={{ display: "grid", gap: 6 }}><h1>Entrar</h1><p style={{ color: "var(--text-secondary)" }}>Use a conta criada pelo administrador do seu órgão.</p></div>
          {authErr && <div style={{ animation: "gc-fade-up var(--dur-slow) var(--ease-out)" }}><Alert variant="error" title="Não foi possível entrar" onClose={() => setAuthErr(false)}>E-mail ou senha não conferem. Verifique os dados ou procure o administrador do órgão.</Alert></div>}
          <Field label="E-mail institucional" htmlFor="email" error={err}><Input id="email" size="lg" icon="envelope-simple" value={email} invalid={!!err} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Senha" htmlFor="senha"><Input id="senha" size="lg" icon="lock-simple" type={show ? "text" : "password"} defaultValue="••••••••••" suffix={<button type="button" className="gc-input__clear" aria-label={show ? "Ocultar senha" : "Mostrar senha"} onClick={() => setShow(!show)}><i className={"gc-icon ph-bold ph-" + (show ? "eye-slash" : "eye")} /></button>} /></Field>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Checkbox label="Manter conectado" defaultChecked /><a href="#" style={{ fontSize: 13 }}>Esqueci a senha</a></div>
          <Button type="submit" size="lg" block loading={loading}>{loading ? "Entrando" : "Entrar"}</Button>
          <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>Ao entrar, você concorda com a <a href="#">política de privacidade</a>.</p>
        </form>
      </section>
    </main>);
}
window.LoginScreen = LoginScreen;
