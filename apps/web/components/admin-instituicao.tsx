"use client";

import { useActionState, useState, useTransition } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  DateField,
  Field,
  Input,
  Select,
  StatusBadge,
  Switch,
  type ProcessStatus,
} from "@/design-system";
import {
  adicionarMembro,
  alternarServidor,
  cadastrarServidor,
  moduloNaPrefeitura,
  moduloNaSecretaria,
  mudarSituacaoDaPortaria,
  registrarPortaria,
  type EstadoDoAto,
} from "@/app/app/admin/instituicao/acoes";
import type { ModuloInstitucional, Opcao, PortariaInstitucional, ServidorInstitucional } from "@/lib/api";

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
