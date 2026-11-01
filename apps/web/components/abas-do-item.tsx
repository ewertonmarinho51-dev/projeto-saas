"use client";

import { useState, type ReactNode } from "react";

import { Tabs } from "@/design-system";

/**
 * Triagem e análise do item em abas. As duas já vêm renderizadas do servidor:
 * trocar de aba não refaz leitura, e a análise ganha a largura inteira da
 * página. A aba fica na URL para sobreviver ao recarregar e ao compartilhar.
 */
export function AbasDoItem({
  inicial,
  referencias,
  triagem,
  analise,
}: {
  inicial: "triagem" | "analise";
  referencias: number;
  triagem: ReactNode;
  analise: ReactNode;
}) {
  const [aba, setAba] = useState(inicial);
  const trocar = (valor: string) => {
    const proxima = valor === "analise" ? "analise" : "triagem";
    setAba(proxima);
    const url = new URL(window.location.href);
    if (proxima === "analise") url.searchParams.set("aba", "analise");
    else url.searchParams.delete("aba");
    window.history.replaceState(window.history.state, "", url);
  };
  return (
    <div className="grid min-w-0 gap-5">
      <Tabs
        ariaLabel="Visões do item"
        value={aba}
        onChange={trocar}
        tabs={[
          { value: "triagem", label: "Triagem", count: referencias },
          { value: "analise", label: "Análise da série" },
        ]}
      />
      <div hidden={aba !== "triagem"} className="min-w-0">
        {triagem}
      </div>
      <div hidden={aba !== "analise"} className="min-w-0">
        {analise}
      </div>
    </div>
  );
}
