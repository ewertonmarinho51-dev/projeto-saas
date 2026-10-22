import type { NextConfig } from "next";

const config: NextConfig = {
  // O servidor não precisa anunciar o que é.
  poweredByHeader: false,
  // Imagem pronta para o container do P06 (node server.js, sem node_modules inteiro).
  output: "standalone",
  reactStrictMode: true,
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
