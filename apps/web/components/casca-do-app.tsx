"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { sair } from "@/app/entrar/acoes";
import {
  AppShell,
  Avatar,
  Badge,
  Breadcrumbs,
  IconButton,
  Logo,
  UserCard,
  type BreadcrumbItem,
  type NavItemProps,
  type SidebarGroup,
} from "@/design-system";

/**
 * Casca da área autenticada, sobre o `AppShell` do design system.
 *
 * O que aparece no menu vem do SERVIDOR (layout): papel e flags já
 * decididos por `/api/v1/me` e pelo ambiente. Aqui só se desenha — e a
 * API recusa de novo quem chegar pela URL. Item sem tela funcional
 * (GovBot, Parecer jurídico) não entra: menu não promete o que não há.
 */
export type Acesso = {
  email: string;
  papel: "admin" | "usuario" | null;
  governanca: boolean;
  precos: boolean;
  govbot: boolean;
};

type Item = NavItemProps & { href: string };

function ativo(caminho: string, href: string): boolean {
  return href === "/app" ? caminho === "/app" : caminho === href || caminho.startsWith(`${href}/`);
}

function grupos(acesso: Acesso, caminho: string): SidebarGroup[] {
  const admin = acesso.papel === "admin";
  const lista: { label?: string; items: (Item | false)[] }[] = [
    {
      items: [
        { id: "inicio", icon: "house", label: "Início", href: "/app" },
        { id: "processos", icon: "folder-open", label: "Processos", href: "/app/processos" },
      ],
    },
    {
      label: "Preparação",
      items: [
        acesso.precos && { id: "precos", icon: "currency-circle-dollar", label: "Preços", href: "/app/precos" },
        acesso.govbot && { id: "govbot", icon: "sparkle", label: "GovBot", href: "/app/govbot" },
        admin && { id: "conhecimento", icon: "books", label: "Base de Conhecimento", href: "/app/admin/base-conhecimento" },
      ],
    },
    {
      label: "Gestão",
      items: [
        acesso.governanca && { id: "governanca", icon: "shield-check", label: "Governança", href: "/app/governanca" },
        admin && { id: "instituicao", icon: "buildings", label: "Instituição", href: "/app/admin/instituicao" },
        admin && { id: "usuarios", icon: "users-three", label: "Usuários", href: "/app/admin/usuarios" },
      ],
    },
    { label: "Conta", items: [{ id: "senha", icon: "key", label: "Senha", href: "/app/conta/senha" }] },
  ];
  return lista
    .map((g) => ({
      label: g.label,
      items: g.items.filter((i): i is Item => Boolean(i)).map((i) => ({ ...i, active: ativo(caminho, i.href) })),
    }))
    .filter((g) => g.items.length > 0);
}

/** Nome de cada trecho fixo da rota; trecho variável (id) vira o nome genérico do recurso. */
const TRECHOS: Record<string, string> = {
  processos: "Processos",
  formulario: "Dados da demanda",
  demandas: "Consolidar demandas",
  precos: "Preços",
  govbot: "GovBot",
  nova: "Nova pesquisa",
  itens: "Itens",
  admin: "Administração",
  instituicao: "Instituição",
  "base-conhecimento": "Base de Conhecimento",
  usuarios: "Usuários",
  governanca: "Governança",
  conta: "Conta",
  senha: "Senha",
};

const RECURSO: Record<string, string> = { processos: "Processo", precos: "Pesquisa", itens: "Item" };

/** Trilha a partir da rota. Sem link para trecho que não é página (Administração, Conta, Itens). */
export function trilha(caminho: string): BreadcrumbItem[] {
  const partes = caminho.replace(/^\/app\/?/, "").split("/").filter(Boolean);
  if (partes.length === 0) return [{ label: "Início" }];
  const itens: BreadcrumbItem[] = [];
  let href = "/app";
  partes.forEach((parte, i) => {
    href += `/${parte}`;
    const anterior = partes[i - 1];
    const label = TRECHOS[parte] ?? (anterior && RECURSO[anterior]) ?? parte;
    const pagina = !["admin", "conta", "itens"].includes(parte);
    itens.push(pagina ? { label, href } : { label });
  });
  // "Itens" fica de fora: a trilha vai da pesquisa direto ao item.
  return itens.filter((i) => i.label !== "Itens");
}

export function CascaDoApp({ acesso, children }: { acesso: Acesso; children: ReactNode }) {
  const caminho = usePathname() ?? "/app";
  const papel = acesso.papel === "admin" ? "Administrador" : acesso.papel ? "Servidor" : "Sem vínculo";
  return (
    <AppShell
      brand={<Logo size={28} href="/app" />}
      groups={grupos(acesso, caminho)}
      footer={
        <UserCard
          name={<span data-testid="usuario-email">{acesso.email}</span>}
          role={papel}
          avatar={<Avatar name={acesso.email} />}
          action={
            <form action={sair}>
              <IconButton type="submit" size="sm" icon="sign-out" label="Sair" />
            </form>
          }
        />
      }
      topStart={<Breadcrumbs items={trilha(caminho)} />}
      topEnd={
        <>
          {acesso.papel && (
            <Badge variant={acesso.papel === "admin" ? "brand" : "neutral"} size="sm">
              {papel}
            </Badge>
          )}
          <Avatar name={acesso.email} />
        </>
      }
    >
      {children}
    </AppShell>
  );
}
