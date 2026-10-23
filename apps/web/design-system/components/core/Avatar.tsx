/* eslint-disable @next/next/no-img-element -- foto de usuário vem de fora; o otimizador do Next não ajuda aqui */
import { cx } from "../../lib/cx";

export interface AvatarProps {
  name?: string;
  src?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/** Iniciais do primeiro e do último nome quando não há foto. */
export function iniciais(nome: string): string {
  const partes = nome.split(" ").filter(Boolean);
  if (partes.length === 0) return "";
  const primeira = partes[0][0];
  const ultima = partes.length > 1 ? partes[partes.length - 1][0] : "";
  return (primeira + ultima).toUpperCase();
}

/** Avatar circular do usuário, com iniciais de reserva. */
export function Avatar({ name = "", src, size = "md", className }: AvatarProps) {
  return (
    <span className={cx("gc-avatar", size !== "md" && `gc-avatar--${size}`, className)} title={name}>
      {src ? <img src={src} alt="" /> : iniciais(name)}
    </span>
  );
}
