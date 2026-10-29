import { redirect } from "next/navigation";

import { CascaDoApp } from "@/components/casca-do-app";
import { Alert } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type Identidade } from "@/lib/api";
import { claimsVerificadas } from "@/lib/supabase/server";

/**
 * Casca da área autenticada. Verifica a sessão de novo, no servidor —
 * o proxy já barrou, mas camada que confia na anterior não é camada.
 * A identidade exibida vem da API (`/api/v1/me`), que é quem decide o
 * vínculo: conta desativada cai aqui mesmo com JWT ainda válido.
 *
 * O desenho é o `AppShell` do design system (components/casca-do-app);
 * o que o menu mostra continua decidido AQUI, no servidor.
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

  const acesso = {
    email: typeof claims.email === "string" ? claims.email : "",
    papel: eu?.papel ?? null,
    governanca: Boolean(eu?.governanca),
    precos: Boolean(eu) && precosHabilitado(),
  };

  return (
    <CascaDoApp acesso={acesso}>
      {falha ? <Alert variant="error" title={falha} /> : children}
    </CascaDoApp>
  );
}
