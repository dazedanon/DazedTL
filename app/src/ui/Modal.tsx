import { useEffectEvent, useLayoutEffect, useRef, type ReactNode } from "react";

export function Modal({
  label,
  children,
  onDismiss,
  dismissible = true,
  className = "",
  returnFocus,
}: {
  label: string;
  children: ReactNode;
  onDismiss: () => void;
  dismissible?: boolean;
  className?: string;
  returnFocus?: HTMLElement | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  // The dialog opens once; closing returns focus to the latest requested target.
  const focusTarget = useEffectEvent(() => returnFocus);
  useLayoutEffect(() => {
    const element = dialog.current!;
    const opener = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      const previous = focusTarget() || opener;
      queueMicrotask(() => {
        if (
          previous instanceof HTMLElement &&
          previous.isConnected &&
          !document.querySelector("dialog[open]")
        ) {
          previous.focus({ preventScroll: true });
        }
      });
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`modal ${className}`}
      aria-label={label}
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (dismissible) onDismiss();
      }}
    >
      {children}
    </dialog>
  );
}
