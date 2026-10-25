"use client";

import { useActionState, useState, useTransition } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DateField,
  Dialog,
  Field,
  FileUpload,
  Input,
  Select,
  StatusBadge,
  Switch,
  Tabs,
  type ProcessStatus,
} from "@/design-system";
import {
  adicionarMembro,
  alternarServidor,
  cadastrarServidor,
  criarSecretaria,
  editarSecretaria,
  excluirIdentidade,
  previaDoModelo,
  salvarIdentidadePorImagem,
  salvarIdentidadePorTexto,
  salvarPrefeitura,
  tornarIdentidadePadrao,
  moduloNaPrefeitura,
  moduloNaSecretaria,
  mudarSituacaoDaPortaria,
  registrarPortaria,
  type EstadoDoAto,
} from "@/app/app/admin/instituicao/acoes";
import type {
  IdentidadeVisual,
  ModuloInstitucional,
  Opcao,
  PortariaInstitucional,
  PrefeituraInstitucional,
  PreviaDoModelo,
  SecretariaCadastrada,
  ServidorInstitucional,
} from "@/lib/api";

const INICIAL: EstadoDoAto = { erro: null, ok: null };

function Retorno({ estado }: { estado: EstadoDoAto }) {
  if (estado.erro) return <Alert variant="error" compact>{estado.erro}</Alert>;
  if (estado.ok) return <Alert variant="success" compact>{estado.ok}</Alert>;
  return null;
}

/** Ato de um clique (alternar, mudar situação): mostra o retorno ao lado. */
function useAto() {
  const [estado, setEstado] = useState<EstadoDoAto>(INICIAL);
  const [ocupado, executar] = useTransition();
  return { estado, ocupado, rodar: (f: () => Promise<EstadoDoAto>) => executar(async () => setEstado(await f())) };
}

// ---------------------------------------------------------------------------
// Servidores
// ---------------------------------------------------------------------------
export function Servidores({ servidores }: { servidores: ServidorInstitucional[] }) {
  const [estado, acao, enviando] = useActionState(cadastrarServidor, INICIAL);
  const alternar = useAto();
  return (
    <div className="grid gap-6">
      <Card
        title="Novo servidor"
        subtitle="Sem CPF: o documento precisa de nome, cargo, matrícula e função — guardar dado pessoal sem necessidade funcional é obrigação sem contrapartida."
        divided
      >
        <form action={acao} className="grid gap-4 md:grid-cols-2">
          <Field label="Nome" htmlFor="srv-nome" required>
            <Input id="srv-nome" name="nome" placeholder="Nome completo" maxLength={200} />
          </Field>
          <Field label="Cargo" htmlFor="srv-cargo" optional>
            <Input id="srv-cargo" name="cargo" placeholder="Ex.: Agente Administrativo" maxLength={200} />
          </Field>
          <Field label="Matrícula" htmlFor="srv-matricula" optional>
            <Input id="srv-matricula" name="matricula" maxLength={60} />
          </Field>
          <Field label="E-mail" htmlFor="srv-email" optional>
            <Input id="srv-email" name="email" type="email" maxLength={200} />
          </Field>
          <div className="grid gap-3 md:col-span-2">
            <Retorno estado={estado} />
            <Button type="submit" loading={enviando} className="justify-self-start">
              Cadastrar servidor
            </Button>
          </div>
        </form>
      </Card>

      <Card title={`${servidores.length} servidor(es)`} divided flush>
        {servidores.length === 0 ? (
          <p className="p-5 text-secundario">Nenhum servidor cadastrado ainda.</p>
        ) : (
          <ul className="divide-y divide-linha" data-testid="lista-servidores">
            {servidores.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <span className="grid">
                  <span className="font-[number:var(--weight-medium)]">
                    {s.nome}
                    {s.matricula && <span className="text-secundario"> · mat. {s.matricula}</span>}
                  </span>
                  <span className="text-[length:var(--gc-fs-sm)] text-secundario">{s.cargo ?? "sem cargo"}</span>
                </span>
                <Switch
                  label={s.ativo ? "Ativo" : "Inativo"}
                  checked={s.ativo}
                  disabled={alternar.ocupado}
                  onChange={(e) => alternar.rodar(() => alternarServidor(s.id, e.target.checked))}
                />
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Retorno estado={alternar.estado} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portarias
// ---------------------------------------------------------------------------
const SITUACAO_PARA_STATUS: Record<string, ProcessStatus> = {
  ATIVA: "concluido",
  FUTURA: "pendente",
  EXPIRADA: "arquivado",
  REVOGADA: "bloqueado",
  RASCUNHO: "rascunho",
};

export function NovaPortaria({ secretaria, tipos }: { secretaria: string; tipos: Opcao[] }) {
  const [estado, acao, enviando] = useActionState(registrarPortaria, INICIAL);
  const ano = new Date().getFullYear();
  return (
    <Card title="Nova portaria" subtitle="Nasce como RASCUNHO; ative-a quando estiver publicada." divided>
      <form action={acao} className="grid gap-4 md:grid-cols-3">
        <input type="hidden" name="secretaria_id" value={secretaria} />
        <Field label="Tipo" htmlFor="por-tipo" className="md:col-span-1">
          <Select id="por-tipo" name="tipo" options={tipos.map((t) => ({ value: t.codigo, label: t.rotulo }))} />
        </Field>
        <Field label="Número" htmlFor="por-numero" required>
          <Input id="por-numero" name="numero" placeholder="Ex.: 003" maxLength={20} />
        </Field>
        <Field label="Ano" htmlFor="por-ano" required>
          <Input id="por-ano" name="ano" type="number" min={2000} max={2100} defaultValue={ano} />
        </Field>
        <Field label="Publicação" htmlFor="por-pub" optional>
          <DateField id="por-pub" name="data_publicacao" />
        </Field>
        <Field label="Início da vigência" htmlFor="por-ini" required>
          <DateField id="por-ini" name="data_inicio_vigencia" defaultValue={new Date().toISOString().slice(0, 10)} />
        </Field>
        <Field label="Fim da vigência" htmlFor="por-fim" optional>
          <DateField id="por-fim" name="data_fim_vigencia" />
        </Field>
        <div className="grid gap-3 md:col-span-3">
          <Retorno estado={estado} />
          <Button type="submit" loading={enviando} className="justify-self-start">
            Registrar portaria
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function UmaPortaria({
  portaria,
  situacoes,
  funcoes,
  servidores,
}: {
  portaria: PortariaInstitucional;
  situacoes: string[];
  funcoes: Opcao[];
  servidores: ServidorInstitucional[];
}) {
  const mudar = useAto();
  const [estado, acao, enviando] = useActionState(adicionarMembro.bind(null, portaria.id), INICIAL);
  const ativos = servidores.filter((s) => s.ativo);
  return (
    <Card
      eyebrow={portaria.tipo_rotulo}
      title={`Portaria ${portaria.numero}/${portaria.ano}`}
      subtitle={portaria.citacao}
      actions={<StatusBadge status={SITUACAO_PARA_STATUS[portaria.situacao] ?? "rascunho"} label={portaria.situacao} />}
      divided
    >
      <div className="grid gap-4">
        <Field
          label="Situação declarada"
          htmlFor={`sit-${portaria.id}`}
          help="EXPIRADA e FUTURA são efeito da vigência e o sistema calcula sozinho. Aqui fica a decisão administrativa."
        >
          <Select
            id={`sit-${portaria.id}`}
            options={situacoes}
            value={portaria.situacao_declarada}
            disabled={mudar.ocupado}
            onChange={(e) => mudar.rodar(() => mudarSituacaoDaPortaria(portaria.id, e.target.value))}
          />
        </Field>
        <Retorno estado={mudar.estado} />

        <div className="grid gap-2">
          <p className="font-[number:var(--weight-semibold)]">Membros</p>
          {portaria.membros.length === 0 ? (
            <p className="text-secundario">Nenhum membro designado.</p>
          ) : (
            <ul className="grid gap-1">
              {portaria.membros.map((m, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  {m.nome} — {m.funcao_rotulo}
                  {!m.servidor_ativo && <Badge variant="warning" size="sm">servidor inativo no cadastro</Badge>}
                </li>
              ))}
            </ul>
          )}
        </div>

        {ativos.length === 0 ? (
          <p className="text-[length:var(--gc-fs-sm)] text-secundario">Cadastre servidores na seção Servidores para designá-los aqui.</p>
        ) : (
          <form action={acao} className="grid gap-3 md:grid-cols-[2fr_2fr_auto] md:items-end">
            <Field label="Servidor" htmlFor={`mem-srv-${portaria.id}`}>
              <Select id={`mem-srv-${portaria.id}`} name="servidor_id" options={ativos.map((s) => ({ value: s.id, label: s.nome }))} />
            </Field>
            <Field label="Função" htmlFor={`mem-fun-${portaria.id}`}>
              <Select id={`mem-fun-${portaria.id}`} name="funcao" options={funcoes.map((f) => ({ value: f.codigo, label: f.rotulo }))} />
            </Field>
            <Button type="submit" variant="secondary" loading={enviando}>
              Adicionar
            </Button>
            <div className="md:col-span-3">
              <Retorno estado={estado} />
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Módulos
// ---------------------------------------------------------------------------
export function ModulosDaPrefeitura({ modulos }: { modulos: ModuloInstitucional[] }) {
  const ato = useAto();
  return (
    <Card
      title="Na Prefeitura"
      subtitle="O módulo precisa existir no sistema, a Prefeitura precisa tê-lo habilitado, e a secretaria pode dispensá-lo."
      divided
      flush
    >
      <ul className="divide-y divide-linha">
        {modulos.map((m) => (
          <li key={m.modulo} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
            <span>{m.rotulo}</span>
            {m.disponivel_no_sistema ? (
              <Switch
                label={m.na_prefeitura ? "Habilitado" : "Desabilitado"}
                checked={m.na_prefeitura}
                disabled={ato.ocupado}
                onChange={(e) => ato.rodar(() => moduloNaPrefeitura(m.modulo, e.target.checked))}
              />
            ) : (
              <span className="text-[length:var(--gc-fs-sm)] text-secundario">indisponível nesta versão do sistema</span>
            )}
          </li>
        ))}
      </ul>
      <div className="px-5 pb-4">
        <Retorno estado={ato.estado} />
      </div>
    </Card>
  );
}

const ESTADOS = [
  { value: "HERDAR", label: "Herdar da Prefeitura" },
  { value: "HABILITADO", label: "Habilitado" },
  { value: "DESABILITADO", label: "Desabilitado" },
];

export function ModulosDaSecretaria({ secretaria, modulos }: { secretaria: string; modulos: ModuloInstitucional[] }) {
  const ato = useAto();
  const disponiveis = modulos.filter((m) => m.disponivel_no_sistema);
  return (
    <Card title="Nesta secretaria" divided flush>
      <ul className="divide-y divide-linha">
        {disponiveis.map((m) => (
          <li key={m.modulo} className="grid gap-2 px-5 py-3 md:grid-cols-[2fr_1fr] md:items-center">
            <span className="grid">
              <span>{m.rotulo}</span>
              <span className="text-[length:var(--gc-fs-sm)] text-secundario">{m.explicacao}</span>
            </span>
            <Select
              aria-label={`${m.rotulo} nesta secretaria`}
              options={ESTADOS}
              value={m.na_secretaria ?? "HERDAR"}
              disabled={ato.ocupado}
              onChange={(e) => ato.rodar(() => moduloNaSecretaria(secretaria, m.modulo, e.target.value))}
            />
          </li>
        ))}
      </ul>
      <div className="px-5 pb-4">
        <Retorno estado={ato.estado} />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Prefeitura (M7b)
// ---------------------------------------------------------------------------
export function DadosDaPrefeitura({ prefeitura }: { prefeitura: PrefeituraInstitucional }) {
  const [estado, acao, enviando] = useActionState(salvarPrefeitura, INICIAL);
  return (
    <Card
      title={prefeitura.nome}
      subtitle="Campos opcionais. Nada é preenchido automaticamente: o sistema não inventa CNPJ nem endereço."
      divided
    >
      <form action={acao} className="grid gap-4 md:grid-cols-2">
        {prefeitura.campos.map((c) => (
          <Field key={c.chave} label={c.rotulo} htmlFor={`pref-${c.chave}`} optional>
            <Input
              id={`pref-${c.chave}`}
              name={c.chave}
              defaultValue={c.valor}
              placeholder={c.exemplo}
              maxLength={["endereco", "nome_oficial", "site"].includes(c.chave) ? 300 : 120}
              type={c.chave === "email" ? "email" : "text"}
            />
          </Field>
        ))}
        <div className="grid gap-3 md:col-span-2">
          <Retorno estado={estado} />
          <Button type="submit" loading={enviando} className="justify-self-start">
            Salvar dados institucionais
          </Button>
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Secretarias (M7b)
// ---------------------------------------------------------------------------
export function Secretarias({ secretarias }: { secretarias: SecretariaCadastrada[] }) {
  const [estado, acao, enviando] = useActionState(criarSecretaria, INICIAL);
  const editar = useAto();
  return (
    <div className="grid gap-6">
      <Card
        title="Nova secretaria"
        subtitle="Secretarias são as unidades do município. O timbrado de cada documento segue a secretaria do processo: a identidade própria dela, senão a padrão do município."
        divided
      >
        <form action={acao} className="grid gap-4 md:grid-cols-[3fr_1fr]">
          <Field label="Nome" htmlFor="sec-nome" required>
            <Input id="sec-nome" name="nome" placeholder="Ex.: Secretaria Municipal de Educação" maxLength={200} />
          </Field>
          <Field label="Sigla" htmlFor="sec-sigla" optional>
            <Input id="sec-sigla" name="sigla" placeholder="Ex.: SEMED" maxLength={30} />
          </Field>
          <div className="grid gap-3 md:col-span-2">
            <Retorno estado={estado} />
            <Button type="submit" loading={enviando} className="justify-self-start">
              Criar secretaria
            </Button>
          </div>
        </form>
      </Card>

      <Card title={`${secretarias.length} secretaria(s)`} divided flush>
        {secretarias.length === 0 ? (
          <p className="p-5 text-secundario">Nenhuma secretaria cadastrada. Crie acima ou salve uma identidade visual.</p>
        ) : (
          <ul className="divide-y divide-linha" data-testid="lista-secretarias">
            {secretarias.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <span className="grid">
                  <span className="font-[number:var(--weight-medium)]">
                    {s.nome}
                    {s.sigla && <span className="text-secundario"> ({s.sigla})</span>}
                  </span>
                  <span className="flex flex-wrap items-center gap-2 text-[length:var(--gc-fs-sm)] text-secundario">
                    {s.identidade_propria ? "identidade própria" : "herda a identidade padrão"}
                    {s.padrao && (
                      <Badge size="sm" variant="brand">
                        padrão do município
                      </Badge>
                    )}
                    {!s.ativo && (
                      <Badge size="sm" variant="warning">
                        desativada
                      </Badge>
                    )}
                  </span>
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  {!s.padrao && s.identidade_propria && s.ativo && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={editar.ocupado}
                      onClick={() => editar.rodar(() => editarSecretaria(s.id, { padrao: true }))}
                    >
                      Tornar padrão
                    </Button>
                  )}
                  <Switch
                    label={s.ativo ? "Ativa" : "Desativada"}
                    checked={s.ativo}
                    disabled={editar.ocupado}
                    onChange={(e) => editar.rodar(() => editarSecretaria(s.id, { ativo: e.target.checked }))}
                  />
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Retorno estado={editar.estado} />
      <p className="text-[length:var(--gc-fs-sm)] text-secundario">
        O vínculo de cada usuário a uma secretaria continua na Administração do GovDocs.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Identidade visual (M7b)
// ---------------------------------------------------------------------------
function PorImagem() {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [cabecalho, setCabecalho] = useState(14);
  const [rodape, setRodape] = useState(10);
  const [marca, setMarca] = useState(false);
  const [orgao, setOrgao] = useState("");
  const [padrao, setPadrao] = useState(false);
  const [previa, setPrevia] = useState<PreviaDoModelo | null>(null);
  const [estado, setEstado] = useState<EstadoDoAto>(INICIAL);
  const [ocupado, iniciar] = useTransition();

  const montar = (a: File) => {
    const form = new FormData();
    form.set("modelo", a);
    form.set("cabecalho_pct", String(cabecalho));
    form.set("rodape_pct", String(rodape));
    if (marca) form.set("marca", "on");
    return form;
  };

  const verPrevia = (a: File) =>
    iniciar(async () => {
      const r = await previaDoModelo(montar(a));
      setEstado({ erro: r.erro, ok: null });
      setPrevia(r.previa);
    });

  const salvar = (a: File) =>
    iniciar(async () => {
      const form = montar(a);
      form.set("orgao", orgao);
      if (padrao) form.set("padrao", "on");
      const r = await salvarIdentidadePorImagem(form);
      setEstado(r);
      if (!r.erro) {
        setArquivo(null);
        setPrevia(null);
        setOrgao("");
        setPadrao(false);
      }
    });

  return (
    <div className="grid gap-4" data-testid="identidade-imagem">
      <FileUpload
        title="Arraste o documento-modelo aqui ou"
        hint="PDF oficial do órgão: a 1ª página é usada para capturar cabeçalho, rodapé e marca d'água"
        accept=".pdf,application/pdf"
        multiple={false}
        files={arquivo ? [{ name: arquivo.name, icon: "file-pdf", meta: "documento-modelo" }] : []}
        onFiles={(lista) => {
          const a = lista[0];
          if (!a) return;
          setArquivo(a);
          setPrevia(null);
          verPrevia(a);
        }}
        onRemove={() => {
          setArquivo(null);
          setPrevia(null);
        }}
      />
      {arquivo && (
        <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <Field label="Altura do cabeçalho (% da página)" htmlFor="id-cab">
            <Input id="id-cab" type="number" min={3} max={40} value={cabecalho} onChange={(e) => setCabecalho(Number(e.target.value))} />
          </Field>
          <Field label="Altura do rodapé (% da página)" htmlFor="id-rod">
            <Input id="id-rod" type="number" min={3} max={40} value={rodape} onChange={(e) => setRodape(Number(e.target.value))} />
          </Field>
          <Button variant="secondary" icon="arrows-clockwise" loading={ocupado} onClick={() => verPrevia(arquivo)}>
            Atualizar prévia
          </Button>
          <Checkbox
            label="Capturar marca d'água (miolo translúcido)"
            checked={marca}
            onChange={(e) => setMarca(e.target.checked)}
            className="md:col-span-3"
          />
        </div>
      )}
      {previa && (
        <Card title="Prévia do que será carimbado" divided>
          <div className="grid gap-3" data-testid="previa-identidade">
            {/* eslint-disable-next-line @next/next/no-img-element -- data URL da API */}
            <img src={previa.cabecalho} alt="Cabeçalho capturado" className="w-full border border-linha" />
            {/* eslint-disable-next-line @next/next/no-img-element -- data URL da API */}
            <img src={previa.rodape} alt="Rodapé capturado" className="w-full border border-linha" />
            {previa.marca && (
              /* eslint-disable-next-line @next/next/no-img-element -- data URL da API */
              <img src={previa.marca} alt="Marca d'água capturada" className="w-56" />
            )}
          </div>
        </Card>
      )}
      {arquivo && (
        <div className="grid gap-4 md:grid-cols-[2fr_1fr] md:items-end">
          <Field label="Órgão" htmlFor="id-orgao" required>
            <Input
              id="id-orgao"
              value={orgao}
              onChange={(e) => setOrgao(e.target.value)}
              placeholder="Ex.: Prefeitura Municipal de Exemplo"
              maxLength={200}
            />
          </Field>
          <Checkbox label="Definir como identidade padrão" checked={padrao} onChange={(e) => setPadrao(e.target.checked)} />
        </div>
      )}
      <Retorno estado={estado} />
      <Button className="justify-self-start" loading={ocupado} disabled={!arquivo || !previa} onClick={() => arquivo && salvar(arquivo)}>
        Salvar identidade (imagem)
      </Button>
    </div>
  );
}

function PorTexto() {
  const [estado, acao, enviando] = useActionState(salvarIdentidadePorTexto, INICIAL);
  return (
    <form action={acao} className="grid gap-4 md:grid-cols-2" data-testid="identidade-texto">
      <Field label="Órgão" htmlFor="idt-orgao" required>
        <Input id="idt-orgao" name="orgao" placeholder="Ex.: Prefeitura Municipal de Exemplo" maxLength={200} />
      </Field>
      <Field label="Marca d'água (PDF)" htmlFor="idt-marca" optional>
        <Input id="idt-marca" name="marca_dagua" placeholder="Ex.: MINUTA ou nome do órgão" maxLength={120} />
      </Field>
      <Field label="Cabeçalho" htmlFor="idt-cab" optional className="md:col-span-2">
        <Input id="idt-cab" name="cabecalho" placeholder="Ex.: PREFEITURA MUNICIPAL DE EXEMPLO · SECRETARIA DE ADMINISTRAÇÃO" maxLength={500} />
      </Field>
      <Field label="Rodapé" htmlFor="idt-rod" optional className="md:col-span-2">
        <Input id="idt-rod" name="rodape" placeholder="Ex.: Rua das Flores, 100, Centro · (11) 4002-8922" maxLength={500} />
      </Field>
      <Checkbox name="padrao" label="Definir como identidade padrão" />
      <div className="grid gap-3 md:col-span-2">
        <Retorno estado={estado} />
        <Button type="submit" loading={enviando} className="justify-self-start">
          Salvar identidade (texto)
        </Button>
      </div>
    </form>
  );
}

export function IdentidadesVisuais({ identidades }: { identidades: IdentidadeVisual[] }) {
  const [modo, setModo] = useState("imagem");
  const [alvo, setAlvo] = useState<IdentidadeVisual | null>(null);
  const ato = useAto();
  return (
    <div className="grid gap-6">
      <Card
        title="Nova identidade"
        subtitle="Cabeçalho e rodapé são carimbados na mesma posição relativa dos documentos (PDF e DOCX); a marca d'água sai translúcida no PDF. Cada identidade também aparece em Secretarias."
        divided
      >
        <div className="grid gap-4">
          <Tabs
            ariaLabel="Forma de cadastro"
            variant="segmented"
            value={modo}
            onChange={setModo}
            tabs={[
              { value: "imagem", label: "Capturar de um modelo (PDF)" },
              { value: "texto", label: "Definir por texto" },
            ]}
          />
          {modo === "imagem" ? <PorImagem /> : <PorTexto />}
        </div>
      </Card>

      <Card title={`${identidades.length} identidade(s)`} divided flush>
        {identidades.length === 0 ? (
          <p className="p-5 text-secundario">Nenhuma identidade cadastrada.</p>
        ) : (
          <ul className="divide-y divide-linha" data-testid="lista-identidades">
            {identidades.map((o) => (
              <li key={o.id} className="grid gap-3 px-5 py-3 md:grid-cols-[2fr_1fr_auto] md:items-center">
                <span className="grid gap-1">
                  <span className="flex flex-wrap items-center gap-2 font-[number:var(--weight-medium)]">
                    {o.orgao}
                    {o.padrao && (
                      <Badge size="sm" variant="brand">
                        padrão
                      </Badge>
                    )}
                  </span>
                  <span className="text-[length:var(--gc-fs-sm)] text-secundario">
                    {o.por_imagem
                      ? "Identidade por imagem (capturada de modelo)"
                      : `${o.cabecalho || "sem cabeçalho"} · ${o.rodape || "sem rodapé"} · marca: ${o.marca_dagua || "nenhuma"}`}
                  </span>
                </span>
                {o.cabecalho_img ? (
                  /* eslint-disable-next-line @next/next/no-img-element -- data URL da API */
                  <img src={o.cabecalho_img} alt={`Cabeçalho de ${o.orgao}`} className="w-full border border-linha" />
                ) : (
                  <span />
                )}
                <span className="flex flex-wrap gap-2">
                  {!o.padrao && (
                    <Button variant="ghost" size="sm" disabled={ato.ocupado} onClick={() => ato.rodar(() => tornarIdentidadePadrao(o.id))}>
                      Tornar padrão
                    </Button>
                  )}
                  <Button variant="danger-subtle" size="sm" icon="trash" onClick={() => setAlvo(o)}>
                    Excluir
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Retorno estado={ato.estado} />
      <Dialog
        open={alvo !== null}
        onClose={() => setAlvo(null)}
        tone="danger"
        icon="trash"
        title="Excluir identidade"
        description={alvo ? `A identidade "${alvo.orgao}" sai do cadastro. A secretaria espelhada continua, como no GovDocs.` : ""}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAlvo(null)}>
              Cancelar
            </Button>
            <Button
              variant="danger"
              loading={ato.ocupado}
              onClick={() => {
                const id = alvo?.id;
                setAlvo(null);
                if (id) ato.rodar(() => excluirIdentidade(id));
              }}
            >
              Excluir
            </Button>
          </>
        }
      />
    </div>
  );
}
