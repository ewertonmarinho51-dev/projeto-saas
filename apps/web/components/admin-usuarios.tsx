"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  Field,
  Input,
  Select,
  Switch,
  TableContainer,
  type DataTableColumn,
} from "@/design-system";
import { alterarUsuario, convidarUsuario, type EstadoDoAto } from "@/app/app/admin/usuarios/acoes";
import type { GestaoDeUsuarios, UsuarioDoMunicipio } from "@/lib/api";

const INICIAL: EstadoDoAto = { erro: null, ok: null };
const PAPEIS = [
  { value: "usuario", label: "Usuário (elabora documentos)" },
  { value: "admin", label: "Administrador" },
];

function Retorno({ estado }: { estado: EstadoDoAto }) {
  if (estado.erro) return <Alert variant="error" compact>{estado.erro}</Alert>;
  if (estado.ok) return <Alert variant="success" compact>{estado.ok}</Alert>;
  return null;
}

function Convite({ secretarias }: { secretarias: GestaoDeUsuarios["secretarias"] }) {
  const [estado, acao, enviando] = useActionState(convidarUsuario, INICIAL);
  return (
    <Card
      title="Convidar pessoa"
      subtitle="A conta nasce com o papel e a secretaria escolhidos aqui. Para entrar, a pessoa define a senha em “Esqueci minha senha”, na tela de entrada."
      divided
    >
      <form action={acao} className="grid gap-4 md:grid-cols-2" data-testid="convite">
        <Field label="Nome completo" htmlFor="conv-nome" required>
          <Input id="conv-nome" name="nome" maxLength={200} />
        </Field>
        <Field label="E-mail institucional" htmlFor="conv-email" required>
          <Input id="conv-email" name="email" type="email" maxLength={254} />
        </Field>
        <Field label="Papel" htmlFor="conv-papel">
          <Select id="conv-papel" name="papel" options={PAPEIS} defaultValue="usuario" />
        </Field>
        <Field label="Secretaria" htmlFor="conv-sec" optional>
          <Select
            id="conv-sec"
            name="secretaria_id"
            options={[{ value: "", label: "Sem vínculo (vale a identidade padrão)" }, ...secretarias.map((s) => ({ value: s.id, label: s.nome }))]}
          />
        </Field>
        <div className="grid gap-3 md:col-span-2">
          <Retorno estado={estado} />
          <Button type="submit" icon="plus" loading={enviando} className="justify-self-start">
            Criar conta
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function GestaoDeUsuariosTela({ dados }: { dados: GestaoDeUsuarios }) {
  const [estado, setEstado] = useState<EstadoDoAto>(INICIAL);
  const [ocupado, executar] = useTransition();
  const router = useRouter();
  const rodar = (id: string, mudanca: Parameters<typeof alterarUsuario>[1]) =>
    executar(async () => {
      const r = await alterarUsuario(id, mudanca);
      setEstado(r);
      if (!r.erro) router.refresh();
    });
  const acesso = dados.gestao_de_acesso;
  const secretarias = [{ value: "", label: "Sem vínculo" }, ...dados.secretarias.map((s) => ({ value: s.id, label: s.nome }))];

  const colunas: DataTableColumn<UsuarioDoMunicipio>[] = [
    {
      key: "nome",
      label: "Pessoa",
      render: (u) => (
        <span className="grid">
          <span className="flex flex-wrap items-center gap-2 font-[number:var(--weight-medium)]">
            {u.nome}
            {u.eu && <Badge size="sm" variant="brand">você</Badge>}
            {!u.acesso_por_email && <Badge size="sm">login antigo</Badge>}
          </span>
          <span className="gc-mono text-[length:var(--gc-fs-sm)] text-secundario">{u.login}</span>
        </span>
      ),
    },
    {
      key: "papel",
      label: "Papel",
      render: (u) => (
        <Select
          size="sm"
          aria-label={`Papel de ${u.nome}`}
          options={PAPEIS}
          value={u.papel}
          disabled={ocupado || u.eu || (u.acesso_por_email && !acesso)}
          onChange={(e) => rodar(u.id, { papel: e.target.value === "admin" ? "admin" : "usuario" })}
        />
      ),
    },
    {
      key: "secretaria_id",
      label: "Secretaria",
      render: (u) => (
        <Select
          size="sm"
          aria-label={`Secretaria de ${u.nome}`}
          options={secretarias}
          value={u.secretaria_id ?? ""}
          disabled={ocupado || (u.acesso_por_email && !acesso)}
          onChange={(e) => rodar(u.id, { secretaria_id: e.target.value || null })}
        />
      ),
    },
    {
      key: "ativo",
      label: "Acesso",
      render: (u) => (
        <Switch
          label={u.ativo ? "Ativo" : "Desativado"}
          checked={u.ativo}
          disabled={ocupado || u.eu}
          onChange={(e) => rodar(u.id, { ativo: e.target.checked })}
        />
      ),
    },
  ];

  return (
    <div className="grid gap-6">
      {!acesso && (
        <Alert variant="warning">
          A chave da Admin API não está configurada no servidor. Desativar ainda corta a interface, mas não bloqueia a conta no
          serviço de login; convidar e trocar papel ou secretaria de conta por e-mail ficam indisponíveis.
        </Alert>
      )}
      {acesso && <Convite secretarias={dados.secretarias} />}
      <Card title={`${dados.usuarios.length} usuário(s)`} subtitle="Você não altera o próprio papel nem se desativa, e o último administrador ativo não sai." divided flush>
        <TableContainer>
          <div data-testid="lista-usuarios">
            <DataTable stack compact caption="Usuários do município" minWidth="48rem" columns={colunas} rows={dados.usuarios} />
          </div>
        </TableContainer>
      </Card>
      <Retorno estado={estado} />
    </div>
  );
}
