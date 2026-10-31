import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EditorDeDocumento } from "@/components/editor-documento";
import { chamarApi, documentosDoProcesso, ErroDaApi, type Processo } from "@/lib/api";

export const metadata: Metadata = { title: "Editar documento" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * WordCraft Workspace. A página só confere que o documento é do processo e
 * que o editor está liberado para quem chama (a API responde 404 fora do
 * canário). A sessão do editor abre no navegador, depois da montagem: abrir
 * importa o texto legado quando ainda não há revisão nativa, e efeito
 * colateral não roda em renderização de servidor nem em prefetch.
 */
export default async function EditarDocumento({ params }: { params: Promise<{ id: string; documentoId: string }> }) {
  const { id, documentoId } = await params;
  if (!UUID.test(id) || !UUID.test(documentoId)) notFound();

  let processo: Processo;
  let lista: Awaited<ReturnType<typeof documentosDoProcesso>>;
  try {
    [processo, lista] = await Promise.all([
      chamarApi<Processo>(`/processos/${id}`).then((r) => r.dados),
      documentosDoProcesso(id),
    ]);
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }
  const documento = lista?.documentos.find((d) => d.id === documentoId);
  if (!documento) notFound();

  // Sem o endereço, o editor só perde a pré-carga: o host baixa o motor sozinho.
  const motor = await chamarApi<{ wasm_url: string }>("/documentos/motor")
    .then((r) => r.dados.wasm_url)
    .catch(() => null);

  return (
    <>
      {/* O download começa com a página, e não depois da sessão, que leva ~7 s:
          abrir custa o maior dos dois tempos, não a soma. Abaixo de `--bp-md` o
          editor não monta, e 16 MB não são baixados à toa. */}
      {motor && (
        // eslint-disable-next-line no-restricted-syntax -- atributo `media` não lê `var()`
        <link rel="preload" as="fetch" crossOrigin="anonymous" href={motor} media="(min-width: 768px)" />
      )}
      <EditorDeDocumento processo={{ id, nome: processo.nome_exibido }} documento={documento} />
    </>
  );
}
