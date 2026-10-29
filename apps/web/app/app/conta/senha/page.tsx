import type { Metadata } from "next";

import { Card, PageHead } from "@/design-system";

import { FormularioDeSenha } from "./formulario";

export const metadata: Metadata = { title: "Senha" };

export default function Senha() {
  return (
    <>
      <PageHead title="Senha" desc="Ao trocar a senha, as outras sessões abertas são encerradas." />
      <Card className="max-w-xl">
        <FormularioDeSenha />
      </Card>
    </>
  );
}
