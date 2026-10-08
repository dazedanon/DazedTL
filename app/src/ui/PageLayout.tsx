import type { ComponentProps, ReactNode, Ref } from "react";
export function PageLayout({
  variant = "document",
  wide = false,
  className = "",
  ...props
}: ComponentProps<"section"> & {
  variant?: "document" | "editor";
  /** Spans the window instead of the shared column, for a workspace such as
   * Images whose grid and preview use every pixel. */
  wide?: boolean;
}) {
  return (
    <section
      {...props}
      className={`page-layout page-layout--${variant}${wide ? " page-layout--wide" : ""} ${className}`}
    />
  );
}
export function PageHeader({
  title,
  description,
  actions,
  divided = false,
  className = "",
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  divided?: boolean;
  className?: string;
}) {
  return (
    <header
      className={`page-header ${divided ? "page-header--divided" : ""} ${className}`}
    >
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions}
    </header>
  );
}
export function PageBody({
  className = "",
  ref,
  ...props
}: ComponentProps<"div"> & { ref?: Ref<HTMLDivElement> }) {
  return <div {...props} ref={ref} className={`page-body ${className}`} />;
}
