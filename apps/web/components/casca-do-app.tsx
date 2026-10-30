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
  type NavItemProps,
  type SidebarGroup,
} from "@/design-system";

import { emEditor, trilha } from "./trilha";

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

export function CascaDoApp({ acesso, children }: { acesso: Acesso; children: ReactNode }) {
  const caminho = usePathname() ?? "/app";
  const papel = acesso.papel === "admin" ? "Administrador" : acesso.papel ? "Servidor" : "Sem vínculo";
  return (
    <AppShell
      workspace={emEditor(caminho)}
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
