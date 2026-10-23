import type { CSSProperties } from "react";
import type { Icon as PhosphorIcon } from "@phosphor-icons/react";
import {
  Archive,
  ArrowClockwise,
  ArrowLeft,
  ArrowRight,
  ArrowSquareOut,
  ArrowUp,
  ArrowsClockwise,
  Bell,
  BookOpen,
  Books,
  Briefcase,
  Buildings,
  CalendarBlank,
  CaretDoubleLeft,
  CaretDoubleRight,
  CaretDown,
  CaretLeft,
  CaretRight,
  CaretUp,
  CaretUpDown,
  ChatCenteredText,
  Check,
  CheckCircle,
  Circle,
  CircleDashed,
  Clock,
  Copy,
  CurrencyCircleDollar,
  Database,
  DotsThreeVertical,
  DownloadSimple,
  EnvelopeSimple,
  ExclamationMark,
  Eye,
  EyeSlash,
  FileArrowDown,
  FilePdf,
  FileText,
  FolderOpen,
  Funnel,
  GearSix,
  HourglassMedium,
  House,
  Info,
  Key,
  LockSimple,
  MagnifyingGlass,
  MicrosoftExcelLogo,
  MinusCircle,
  Paperclip,
  PencilSimple,
  PencilSimpleLine,
  Plus,
  PlusCircle,
  Prohibit,
  Question,
  Scales,
  SealCheck,
  ShieldCheck,
  SignOut,
  SortAscending,
  Sparkle,
  ThumbsDown,
  ThumbsUp,
  Trash,
  Tray,
  UploadSimple,
  Warning,
  WarningCircle,
  WarningOctagon,
  X,
} from "@phosphor-icons/react/dist/ssr";

import { cx } from "../../lib/cx";

/**
 * Registro fechado dos ícones do Gov Conect (Phosphor, nome em kebab-case
 * como em phosphoricons.com). Fechado de propósito: importar o Phosphor
 * inteiro por nome levaria milhares de ícones para o navegador, e o nome
 * digitado errado vira erro de tipo, não ícone vazio. Ícone novo entra
 * aqui.
 */
const ICONES = {
  archive: Archive,
  "arrow-clockwise": ArrowClockwise,
  "arrow-left": ArrowLeft,
  "arrow-right": ArrowRight,
  "arrow-square-out": ArrowSquareOut,
  "arrow-up": ArrowUp,
  "arrows-clockwise": ArrowsClockwise,
  bell: Bell,
  "book-open": BookOpen,
  books: Books,
  briefcase: Briefcase,
  buildings: Buildings,
  "calendar-blank": CalendarBlank,
  "caret-double-left": CaretDoubleLeft,
  "caret-double-right": CaretDoubleRight,
  "caret-down": CaretDown,
  "caret-left": CaretLeft,
  "caret-right": CaretRight,
  "caret-up": CaretUp,
  "caret-up-down": CaretUpDown,
  "chat-centered-text": ChatCenteredText,
  check: Check,
  "check-circle": CheckCircle,
  circle: Circle,
  "circle-dashed": CircleDashed,
  clock: Clock,
  copy: Copy,
  "currency-circle-dollar": CurrencyCircleDollar,
  database: Database,
  "dots-three-vertical": DotsThreeVertical,
  "download-simple": DownloadSimple,
  "envelope-simple": EnvelopeSimple,
  "exclamation-mark": ExclamationMark,
  eye: Eye,
  "eye-slash": EyeSlash,
  "file-arrow-down": FileArrowDown,
  "file-pdf": FilePdf,
  "file-text": FileText,
  "folder-open": FolderOpen,
  funnel: Funnel,
  "gear-six": GearSix,
  "hourglass-medium": HourglassMedium,
  house: House,
  info: Info,
  key: Key,
  "lock-simple": LockSimple,
  "magnifying-glass": MagnifyingGlass,
  "microsoft-excel-logo": MicrosoftExcelLogo,
  "minus-circle": MinusCircle,
  paperclip: Paperclip,
  "pencil-simple": PencilSimple,
  "pencil-simple-line": PencilSimpleLine,
  plus: Plus,
  "plus-circle": PlusCircle,
  prohibit: Prohibit,
  question: Question,
  scales: Scales,
  "seal-check": SealCheck,
  "shield-check": ShieldCheck,
  "sign-out": SignOut,
  "sort-ascending": SortAscending,
  sparkle: Sparkle,
  "thumbs-down": ThumbsDown,
  "thumbs-up": ThumbsUp,
  trash: Trash,
  tray: Tray,
  "upload-simple": UploadSimple,
  warning: Warning,
  "warning-circle": WarningCircle,
  "warning-octagon": WarningOctagon,
  x: X,
} satisfies Record<string, PhosphorIcon>;

export type IconName = keyof typeof ICONES;

/** Nomes registrados, para a vitrine e para as provas. */
export const ICON_NAMES = Object.keys(ICONES) as IconName[];

export interface IconProps {
  name: IconName;
  /** bold é o padrão; fill só em item de menu ativo, status e no brilho do GovBot. */
  weight?: "bold" | "fill" | "regular";
  /** Em px. Sem tamanho, o ícone acompanha o font-size (1em) — é o que os componentes usam. */
  size?: number;
  /** Só quando o ícone sozinho carrega sentido; sem rótulo ele é decorativo (aria-hidden). */
  label?: string;
  className?: string;
  style?: CSSProperties;
}

/** Ícone Phosphor. Use em todo ícone da interface: 16 px em linha, 18 px em botão e menu, 20 px em alerta. */
export function Icon({ name, weight = "bold", size, label, className, style }: IconProps) {
  const Glifo = ICONES[name];
  return (
    <Glifo
      weight={weight}
      size={size ?? "1em"}
      className={cx("gc-icon", className)}
      style={style}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
    />
  );
}
