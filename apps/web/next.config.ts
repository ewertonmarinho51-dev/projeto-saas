import type { NextConfig } from "next";

const config: NextConfig = {
  // O servidor não precisa anunciar o que é.
  poweredByHeader: false,
  // Imagem pronta para o container do P06 (node server.js, sem node_modules inteiro).
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    // Server Actions aceitam 1 MB por padrão. As que recebem arquivo
    // (memorando até 15 MB, planilha até 5 MB, DFDs de demanda até 30 MB
    // no total) recusariam acima disso antes de chegar ao código. O teto de
    // cada arquivo continua conferido na action e na API.
    serverActions: { bodySizeLimit: "32mb" },
  },
  async headers() {
    const base = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
    ];
    return [
      { source: "/:caminho*", headers: base },
      // Área privada e telas de sessão: nada em cache, em lugar nenhum.
      {
        source: "/app/:caminho*",
        headers: [{ key: "Cache-Control", value: "private, no-store" }],
      },
      {
        source: "/entrar/:caminho*",
        headers: [{ key: "Cache-Control", value: "private, no-store" }],
      },
    ];
  },
};

export default config;
