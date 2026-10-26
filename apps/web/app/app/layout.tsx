import { redirect } from "next/navigation";
import { Books, Buildings, CurrencyCircleDollar, FolderOpen, House, Key, ShieldCheck, SignOut, UsersThree } from "@phosphor-icons/react/dist/ssr";

import { MarcaComNome } from "@/components/marca";
import { LinkDoMenu } from "@/components/menu";
import { sair } from "@/app/entrar/acoes";
import { chamarApi, ErroDaApi, precosHabilitado, type Identidade } from "@/lib/api";
import { claimsVerificadas } from "@/lib/supabase/server";

/**
 * Casca da área autenticada. Verifica a sessão de novo, no servidor —
 * o proxy já barrou, mas camada que confia na anterior não é camada.
 * A identidade exibida vem da API (`/api/v1/me`), que é quem decide o
 * vínculo: conta desativada cai aqui mesmo com JWT ainda válido.
 */
export default async function LayoutDoApp({ children }: { children: React.ReactNode }) {
  const claims = await claimsVerificadas();
  if (!claims) redirect("/entrar");

  let eu: Identidade | null = null;
  let falha: string | null = null;
  try {
    eu = (await chamarApi<Identidade>("/me")).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 401) redirect("/entrar");
    falha =
      e instanceof ErroDaApi && e.status === 403
        ? "Sua conta está sem vínculo ativo com um órgão. Procure o administrador."
        : "O serviço está indisponível no momento. Tente de novo em instantes.";
  }

  const email = typeof claims.email === "string" ? claims.email : "";

  return (
    <div className="min-h-[100dvh] md:grid md:grid-cols-[15rem_1fr]">
      <aside className="border-b border-linha bg-superficie md:sticky md:top-0 md:h-[100dvh] md:border-b-0 md:border-r">
        <div className="flex h-16 items-center px-4 md:px-5">
          <MarcaComNome href="/app" />
        </div>
        <nav aria-label="Área de trabalho" className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0">
          <LinkDoMenu href="/app" icone={<House size={18} weight="bold" aria-hidden />}>
            Início
          </LinkDoMenu>
          <LinkDoMenu href="/app/processos" icone={<FolderOpen size={18} weight="bold" aria-hidden />}>
            Processos
          </LinkDoMenu>
          {precosHabilitado() && (
            <LinkDoMenu href="/app/precos" icone={<CurrencyCircleDollar size={18} weight="bold" aria-hidden />}>
              Preços
            </LinkDoMenu>
          )}
          {eu?.papel === "admin" && (
            <LinkDoMenu href="/app/admin/instituicao" icone={<Buildings size={18} weight="bold" aria-hidden />}>
              Instituição
            </LinkDoMenu>
          )}
          {eu?.papel === "admin" && (
            <LinkDoMenu href="/app/admin/base-conhecimento" icone={<Books size={18} weight="bold" aria-hidden />}>
              Base de Conhecimento
            </LinkDoMenu>
          )}
          {eu?.papel === "admin" && (
            <LinkDoMenu href="/app/admin/usuarios" icone={<UsersThree size={18} weight="bold" aria-hidden />}>
              Usuários
            </LinkDoMenu>
          )}
          {eu?.governanca && (
            <LinkDoMenu href="/app/governanca" icone={<ShieldCheck size={18} weight="bold" aria-hidden />}>
              Governança
            </LinkDoMenu>
          )}
          <LinkDoMenu href="/app/conta/senha" icone={<Key size={18} weight="bold" aria-hidden />}>
            Senha
          </LinkDoMenu>
        </nav>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="flex h-16 items-center justify-end gap-4 border-b border-linha bg-canvas px-4 sm:px-8">
          <div className="min-w-0 text-right leading-tight">
            <p className="truncate text-sm font-medium" data-testid="usuario-email">
              {email}
            </p>
            {eu && (
              <p className="text-xs text-secundario">{eu.papel === "admin" ? "Administrador" : "Servidor"}</p>
            )}
          </div>
          <form action={sair}>
            <button
              type="submit"
              className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-ui)] border border-linha px-3 text-sm transition-colors hover:border-campo hover:bg-superficie"
            >
              <SignOut size={16} weight="bold" aria-hidden />
              Sair
            </button>
          </form>
        </header>
        <main id="conteudo" className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-8 sm:py-10">
          {falha ? (
            <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-4 py-3 text-sm text-erro">
              {falha}
            </p>
          ) : (
            children
          )}
        </main>
      </div>
    </div>
  );
}
