const { Card, Button, Stepper, Field, Input, Select, Textarea, RadioGroup, FileUpload, Alert, Badge, AiProcessing, DocumentViewer, IconButton, Tabs } = window.GovConectDesignSystem_76359c;
function NewProcessScreen({ toast }) {
  const [step, setStep] = React.useState(0);
  const [gen, setGen] = React.useState(0);
  const [obj, setObj] = React.useState("");
  const [err, setErr] = React.useState(false);
  const steps = [{ label: "Dados da demanda" }, { label: "DFD" }, { label: "ETP" }, { label: "Mapa de Riscos" }, { label: "TR" }, { label: "Minuta do edital" }, { label: "Concluído" }];
  const next = () => { if (step === 0 && obj.trim().length < 10) { setErr(true); return; } setErr(false); setStep(1); setGen(1); setTimeout(() => setGen(2), 1400); setTimeout(() => setGen(3), 2800); };
  return (<>
    <PageHead title={step === 0 ? "Dados da demanda" : "Documento de Formalização da Demanda"} desc={step === 0 ? "Preencha as informações essenciais para iniciar o planejamento da contratação." : "Gerado a partir dos dados da demanda. Revise antes de avançar."} actions={step > 0 && gen === 3 && <><Button variant="secondary" icon="arrow-left" onClick={() => setStep(0)}>Voltar</Button><Button icon="check" onClick={() => toast("DFD aprovado", "Próxima etapa: ETP")}>Aprovar DFD</Button></>} />
    <Card><div style={{ padding: "4px 0" }}><Stepper current={step} steps={steps} /></div></Card>
    {step === 0 ? <div className="kit-2col">
      <div style={{ display: "grid", gap: 16 }}>
        <Card title="Informações gerais" subtitle="Identificação da contratação" divided>
          <div className="kit-form2">
            <Field label="Quem está pedindo" required help="Órgão ou secretaria demandante."><Input placeholder="Ex.: Secretaria Municipal de Saúde" defaultValue="Secretaria Municipal de Administração" /></Field>
            <Field label="Quem assina o pedido" required><Input placeholder="Ex.: Maria Silva, Diretora de Compras" /></Field>
            <Field label="Para quando você precisa" required><Input type="date" /></Field>
            <Field label="Como a entrega vai acontecer" required><Select placeholder="Selecione uma opção" options={["Entrega única", "Entregas parceladas", "Prestação contínua"]} /></Field>
          </div>
        </Card>
        <Card title="Objeto e justificativa" divided>
          <div style={{ display: "grid", gap: 16 }}>
            <Field label="O que vai ser comprado ou contratado" required counter={obj.length + " / 2.000"} error={err ? "Descreva o objeto com pelo menos 10 caracteres." : null}><Textarea invalid={err} value={obj} onChange={(e) => setObj(e.target.value)} placeholder="Ex.: Aquisição de 40 computadores desktop tipo corporativo, com monitor de 24 polegadas, para as unidades administrativas." /></Field>
            <RadioGroup name="cat" legend="Categoria" row defaultValue="Materiais" options={["Materiais", "Serviços", "Obras e serviços de engenharia"]} />
          </div>
        </Card>
      </div>
      <div style={{ display: "grid", gap: 16 }}>
        <Card title="Documento inicial" subtitle="Opcional — o GovBot extrai os campos."><FileUpload hint="PDF ou DOCX até 200 MB" /></Card>
        <Alert variant="info" compact>0 de 5 campos obrigatórios preenchidos. O que falta: quem assina, prazo, forma de entrega.</Alert>
        <Button size="lg" iconRight="arrow-right" onClick={next}>Gerar DFD</Button>
      </div>
    </div> : gen < 3 ?
      <AiProcessing title="Gerando DFD" progress={gen === 1 ? 35 : 75} steps={[{ label: "Lendo dados da demanda", state: "done" }, { label: "Consultando base de conhecimento do órgão", state: gen === 1 ? "active" : "done", meta: "12 trechos" }, { label: "Redigindo seções do DFD", state: gen === 2 ? "active" : "pending" }]} /> :
      <DocumentViewer name="DFD — Aquisição de equipamentos de TI" meta="Versão 1 · gerado agora" badges={<Badge variant="warning" icon="eye">Aguardando revisão</Badge>} actions={<><IconButton size="sm" icon="pencil-simple" label="Editar" /><IconButton size="sm" icon="download-simple" label="Baixar DOCX" /></>}>
        <h1>Documento de Formalização da Demanda</h1>
        <h2>1. Identificação da área requisitante</h2><p>Secretaria Municipal de Administração — Prefeitura Municipal de Paragominas.</p>
        <h2>2. Descrição do objeto</h2><p><span className="gc-mark-ai">{obj || "Aquisição de 40 computadores desktop tipo corporativo, com monitor de 24 polegadas."}</span></p>
        <h2>3. Justificativa da necessidade</h2><p><span className="gc-mark-ai">O parque computacional atual possui equipamentos com mais de oito anos de uso, com recorrentes falhas que comprometem a continuidade dos serviços administrativos.</span> <span className="gc-mark-review">Indicar o número de chamados de manutenção no último ano.</span></p>
        <h2>4. Previsão no plano de contratações anual</h2><p><span className="gc-mark-review">Informar o item do PCA 2026 correspondente.</span></p>
      </DocumentViewer>}
  </>);
}
window.NewProcessScreen = NewProcessScreen;
