-- ============================================================
-- 0017 — Categoria `manual` no catálogo da Base de Conhecimento
--         APLICADA EM 11/08/2026 (com autorização)
--
-- MOTIVO
-- Os três documentos hoje gravados como `entendimento` não são
-- entendimentos de Tribunal de Contas:
--   • instrumento-de-padronizacao-...-agu-fev-2024.pdf (158 chunks)
--     → AGU + Ministério da Gestão e da Inovação em Serviços Públicos
--   • manual de fase de planejamento.pdf (43 chunks)
--     → Ministério das Comunicações, "Manual de Contratações", ago/2025
--   • ManualdeLicitacoeseContratacoesAdministrativas.pdf (1.110 chunks)
--     → AGU — Consultoria-Geral da União / Corregedoria-Geral
--
-- São MANUAIS/ORIENTAÇÕES do Executivo federal. Como `entendimento` está
-- declarado no código como "Entendimento / Orientação de TC", o bloco do
-- RAG os apresenta ao modelo como jurisprudência/orientação de ÓRGÃO DE
-- CONTROLE — o que superestima um manual interno federal diante de uma
-- contratação MUNICIPAL. Nenhum deles fornece lastro de dispositivo
-- (só `lei` fornece), então o risco é de PESO no prompt, não de citação.
--
-- POR QUE UMA MIGRAÇÃO É NECESSÁRIA
-- `documentos_referencia_categoria_check` restringe a coluna a
--   ('lei','acordao','entendimento','processo_anterior','modelo','outro')
-- Um UPDATE para 'manual' hoje FALHA. E incluir 'manual' apenas em
-- `rag.CATEGORIAS` faria a tela de upload oferecer uma opção que o banco
-- rejeita. Por isso a ordem abaixo é obrigatória.
--
-- ORDEM SEGURA DE EXECUÇÃO
--   1. aplicar ESTA migração (só AMPLIA o conjunto aceito — nenhum dado
--      existente se torna inválido; a versão em produção continua
--      gravando as categorias antigas normalmente);
--   2. reclassificar os 3 documentos (bloco 2, revisado antes de rodar);
--   3. só então publicar o código com `manual` em `rag.CATEGORIAS`,
--      `_PAPEL_DA_FONTE` e `_prioridade_fonte` — se o código for antes,
--      a opção aparece na tela e o insert quebra no CHECK.
--
-- ALTERAÇÃO DE CÓDIGO QUE ACOMPANHA (não incluída aqui):
--   CATEGORIAS["manual"] = "Manual / Orientação técnica"
--   _PAPEL_DA_FONTE["manual"] = "manual/orientação técnica — apoia a
--       redação e a estrutura; NÃO fundamenta dispositivo"
--   _prioridade_fonte: 'manual' acima de modelo/processo_anterior e
--       abaixo de acórdão/entendimento; FORA de LEGISLACAO (sem lastro).
-- ============================================================

-- ---- BLOCO 1: ampliar o domínio aceito -----------------------------
alter table public.documentos_referencia
  drop constraint if exists documentos_referencia_categoria_check;

alter table public.documentos_referencia
  add constraint documentos_referencia_categoria_check
  check (categoria = any (array[
    'lei'::text,               -- legislação / regulamento vigente
    'acordao'::text,           -- jurisprudência de controle
    'entendimento'::text,      -- orientação de Tribunal de Contas
    'manual'::text,            -- manual / orientação técnica (novo)
    'processo_anterior'::text, -- molde: processo já realizado
    'modelo'::text,            -- molde: minuta padrão
    'outro'::text
  ]));

-- ---- BLOCO 2: reclassificação (executada como DML, por ID) ---------
-- Feita fora desta migração, por IDs conferidos um a um — jamais por
-- um UPDATE genérico que pudesse alcançar documentos futuros:
--
--   update public.documentos_referencia set categoria = 'manual'
--    where id in ('dfac3fad-414c-4719-a853-40fe2785320d',   -- AGU + MGI
--                 '8c030522-33c3-4ca1-8d9c-dc14da29e217',   -- MCom
--                 '82dcb022-32e9-4ca6-bc8e-f53ff5873cb7')   -- AGU/CGU
--      and categoria = 'entendimento';
--
-- Resultado conferido: 3 documentos migrados; `entendimento` zerado;
-- 40 documentos no total; 4.539 chunks e 2.978 embeddings legados
-- intactos; impressão estrutural 90c41e57140a984909bbd86547d72d50
-- inalterada. Reversível: basta voltar `categoria` para 'entendimento'.
