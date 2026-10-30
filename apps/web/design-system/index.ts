/**
 * Design system Gov Conect — ponto de entrada único. Fora de
 * design-system/, importe SEMPRE daqui (`@/design-system`), nunca de um
 * arquivo interno: o ESLint avisa.
 *
 * 70 componentes + PROCESS_STATUS — exatamente os 71 nomes do export do
 * Claude Design — e 11 templates (AppShell, AuthLayout, LandingHero,
 * PageHead e as 7 peças do site público, PublicSite.tsx). tests/design-system.test.ts confere a lista.
 */

// core
export { Avatar, type AvatarProps } from "./components/core/Avatar";
export { Icon, type IconName, type IconProps } from "./components/core/Icon";
export { Logo, type LogoProps } from "./components/core/Logo";
export { Tooltip, type TooltipProps } from "./components/core/Tooltip";

// actions
export { Button, buttonClasses, type ButtonProps, type ButtonVariant } from "./components/actions/Button";
export { IconButton, type IconButtonProps } from "./components/actions/IconButton";
export { Menu, type MenuItem, type MenuProps } from "./components/actions/Menu";
export { Toolbar, ToolbarSeparator, ToolbarSpacer, type ToolbarProps } from "./components/actions/Toolbar";

// forms
export { Checkbox, type CheckboxProps } from "./components/forms/Checkbox";
export { DateField, type DateFieldProps } from "./components/forms/DateField";
export { Field, type FieldProps } from "./components/forms/Field";
export { FileUpload, type FileUploadProps, type UploadFile } from "./components/forms/FileUpload";
export { Input, type InputProps } from "./components/forms/Input";
export { Radio, RadioGroup, type RadioGroupProps, type RadioOption, type RadioProps } from "./components/forms/Radio";
export { SearchField, type SearchFieldProps } from "./components/forms/SearchField";
export { Select, type SelectOption, type SelectProps } from "./components/forms/Select";
export { Switch, type SwitchProps } from "./components/forms/Switch";
export { Textarea, type TextareaProps } from "./components/forms/Textarea";

// navigation
export { Breadcrumbs, type BreadcrumbItem, type BreadcrumbsProps } from "./components/navigation/Breadcrumbs";
export {
  NavItem,
  Sidebar,
  UserCard,
  type NavItemProps,
  type SidebarGroup,
  type SidebarProps,
  type UserCardProps,
} from "./components/navigation/Sidebar";
export { Stepper, type StepItem, type StepperProps, type StepState } from "./components/navigation/Stepper";
export { Tabs, type TabItem, type TabsProps } from "./components/navigation/Tabs";
export { Topbar, type TopbarProps } from "./components/navigation/Topbar";

// content
export { Accordion, type AccordionItem, type AccordionProps } from "./components/content/Accordion";
export { Card, type CardProps } from "./components/content/Card";
export { DataList, type DataListItem, type DataListProps } from "./components/content/DataList";
export { Dialog, type DialogProps } from "./components/content/Dialog";
export { DocumentViewer, type DocumentViewerProps } from "./components/content/DocumentViewer";

// feedback
export { Alert, type AlertProps, type AlertVariant } from "./components/feedback/Alert";
export { Badge, type BadgeProps, type BadgeVariant } from "./components/feedback/Badge";
export { EmptyState, type EmptyStateProps } from "./components/feedback/EmptyState";
export { ProgressBar, type ProgressBarProps } from "./components/feedback/ProgressBar";
export { Skeleton, SkeletonText, type SkeletonProps } from "./components/feedback/Skeleton";
export { Spinner, type SpinnerProps } from "./components/feedback/Spinner";
export { PROCESS_STATUS, StatusBadge, type ProcessStatus, type StatusBadgeProps } from "./components/feedback/StatusBadge";
export { Tag, type TagProps } from "./components/feedback/Tag";
export { Toast, ToastStack, type ToastProps, type ToastVariant } from "./components/feedback/Toast";

// data
export { BarChart, type BarChartDatum, type BarChartProps } from "./components/data/BarChart";
export {
  DataTable,
  TableContainer,
  type DataTableColumn,
  type DataTableProps,
  type RowKey,
  type SortState,
} from "./components/data/DataTable";
export { KpiCard, type KpiCardProps } from "./components/data/KpiCard";
export { Pagination, type PaginationProps } from "./components/data/Pagination";

// ai (GovBot)
export { AiDraftBlock, type AiDraftBlockProps } from "./components/ai/AiDraftBlock";
export { AiProcessing, type AiProcessingProps, type AiProcessingStep } from "./components/ai/AiProcessing";
export { ChatComposer, type ChatComposerProps } from "./components/ai/ChatComposer";
export { ChatMessage, Cite, type ChatMessageProps } from "./components/ai/ChatMessage";
export { ContextBar, type ContextBarProps, type ContextItem } from "./components/ai/ContextBar";
export { ConversationList, type ConversationItem, type ConversationListProps } from "./components/ai/ConversationList";
export { MessageFeedback, type FeedbackValue, type MessageFeedbackProps } from "./components/ai/MessageFeedback";
export { PromptSuggestions, type PromptSuggestion, type PromptSuggestionsProps } from "./components/ai/PromptSuggestions";
export { SourceList, type SourceItem, type SourceListProps } from "./components/ai/SourceList";

// price (pesquisa de preços)
export { ExclusionDialog, type ExclusionDialogProps } from "./components/price/ExclusionDialog";
export { PriceBasket, type PriceBasketItem, type PriceBasketProps } from "./components/price/PriceBasket";
export { PriceDispersion, type DispersionLabels, type DispersionValue, type PriceDispersionProps } from "./components/price/PriceDispersion";
export { PriceItemNav, type PriceItem, type PriceItemNavProps } from "./components/price/PriceItemNav";
export { PriceMapTable, type PriceMapRow, type PriceMapTableProps } from "./components/price/PriceMapTable";
export { PriceReferenceRow, type PriceReferenceRowProps, type ReferenceStatus } from "./components/price/PriceReferenceRow";
export { PriceStats, type PriceStat, type PriceStatsProps } from "./components/price/PriceStats";
export { ScreeningSummary, type ScreeningKey, type ScreeningSummaryProps } from "./components/price/ScreeningSummary";
export { SourcePicker, type PriceSource, type SourcePickerProps } from "./components/price/SourcePicker";
export { TraceabilityPanel, type TraceabilityPanelProps } from "./components/price/TraceabilityPanel";
export { ValidationSummary, type Severity, type ValidationIssue, type ValidationSummaryProps } from "./components/price/ValidationSummary";

// templates (composições de página, do ui_kit do export)
export { AppShell, type AppShellProps } from "./templates/AppShell";
export { AuthLayout, type AuthLayoutProps } from "./templates/AuthLayout";
export { LandingHero, type LandingHeroProps, type LandingLink } from "./templates/LandingHero";
export { PageHead, type PageHeadProps } from "./templates/PageHead";
export {
  PublicFeature,
  PublicFooter,
  PublicGrid,
  PublicHeader,
  PublicPage,
  PublicSection,
  PublicSteps,
  type PublicFeatureProps,
  type PublicFooterColumn,
  type PublicFooterProps,
  type PublicHeaderProps,
  type PublicLink,
  type PublicPageProps,
  type PublicSectionProps,
  type PublicStep,
} from "./templates/PublicSite";
