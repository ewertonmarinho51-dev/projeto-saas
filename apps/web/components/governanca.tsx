import { Badge, Card, EmptyState, type BadgeVariant } from "@/design-system";
import type { ArtefatoDeGovernanca, VersaoDeGovernanca } from "@/lib/api";

const TOM: Record<string, BadgeVariant> = {
  PUBLISHED: "success",
  DRAFT: "neutral",
  UNDER_REVIEW: "info",
  APPROVED_FOR_SIMULATION: "info",
  SHADOW: "info",
  SCHEDULED: "info",
  SUPERSEDED: "neutral",
  REVOKED: "error",
};

const VAZIO: Record<string, string> = {
  clausula: "Nenhuma cláusula no catálogo.",
  politica: "Nenhuma política de aplicação.",
  familia: "Nenhum modelo na biblioteca.",
  template: "Nenhum template.",
};

function texto(valor: unknown): string {
  return typeof valor === "string" ? valor : "";
}

function lista(valor: unknown): string[] {
  return Array.isArray(valor) ? valor.filter((v): v is string => typeof v === "string") : [];
}

/** O conteúdo da versão, por tipo — o mesmo recorte que o GovDocs mostra. */
function Conteudo({ tipo, versao, descricao }: { tipo: string; versao: VersaoDeGovernanca; descricao: string }) {
  const p = versao.payload;
  if (tipo === "clausula") {
    return (
      <div className="grid gap-2">
        <p className="text-[length:var(--gc-fs-sm)] text-secundario">
          {texto(p.comportamento) || "comportamento não informado"} · documento {texto(p.tipo_documental) || "—"}
        </p>
        {lista(p.blocos).map((b, i) => (
          <blockquote key={i} className="border-l-2 border-linha pl-3 text-[length:var(--gc-fs-sm)]">
            {b}
          </blockquote>
        ))}
        {lista(p.parametros_permitidos).length > 0 && (
          <p className="text-[length:var(--gc-fs-sm)] text-secundario">Parâmetros: {lista(p.parametros_permitidos).join(", ")}</p>
        )}
        {lista(p.base_legal).length > 0 && (
          <p className="text-[length:var(--gc-fs-sm)] text-secundario">Base legal: {lista(p.base_legal).join("; ")}</p>
        )}
      </div>
    );
  }
  if (tipo === "politica" || tipo === "familia") {
    return (
      <div className="grid gap-1 text-[length:var(--gc-fs-sm)]">
        {tipo === "familia" && texto(p.nome) && <p className="font-[number:var(--weight-medium)]">{texto(p.nome)}</p>}
        {descricao && (
          <p>
            <span className="text-secundario">{tipo === "politica" ? "SE " : "Critérios: "}</span>
            <span className="gc-mono">{descricao}</span>
          </p>
        )}
      </div>
    );
  }
  const blocos = Array.isArray(p.blocos) ? p.blocos.length : 0;
  return <p className="text-[length:var(--gc-fs-sm)] text-secundario">{blocos} bloco(s) no template.</p>;
}

export function ArtefatosDaGovernanca({ tipo, artefatos }: { tipo: string; artefatos: ArtefatoDeGovernanca[] }) {
  if (artefatos.length === 0) return <EmptyState icon="folder-open" title={VAZIO[tipo] ?? "Nada aqui ainda."} />;
  return (
    <ul className="grid gap-4" data-testid="artefatos-governanca">
      {artefatos.map((a) => {
        const titulo = texto(a.ultima?.payload.titulo) || texto(a.ultima?.payload.nome) || a.chave;
        return (
          <li key={a.id}>
            <Card
              eyebrow={a.escopo === "plataforma" ? "Plataforma" : "Município"}
              title={titulo}
              subtitle={<span className="gc-mono">{a.chave}</span>}
              actions={
                a.ultima ? (
                  <Badge variant={TOM[a.ultima.status] ?? "neutral"}>
                    v{a.ultima.versao} · {a.ultima.status_rotulo}
                  </Badge>
                ) : (
                  <Badge>sem versões</Badge>
                )
              }
              divided
            >
              <div className="grid gap-3">
                {a.ultima && <Conteudo tipo={tipo} versao={a.ultima} descricao={a.descricao} />}
                <p className="text-[length:var(--gc-fs-sm)] text-secundario">
                  {a.vigente && a.vigente.id !== a.ultima?.id
                    ? `Vigente: v${a.vigente.versao} (hash ${a.vigente.hash}…) — a versão acima está em elaboração.`
                    : a.ultima
                      ? `Hash ${a.ultima.hash}… · ${a.versoes} versão(ões)`
                      : ""}
                </p>
              </div>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}
