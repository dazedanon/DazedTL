import { Copy } from "lucide-react";
import { useAction } from "../state/useAction";
import { Button } from "../ui/Button";

export function DiagnosticsAction() {
  const action = useAction();
  async function copy() {
    try {
      await window.dazedtl.copyDiagnostics();
    } catch {
      throw new Error("Diagnostics could not be copied. Try again.");
    }
  }
  return (
    <>
      <Button
        variant="quiet"
        pending={action.busy}
        title="Copy app versions and recent error details"
        onClick={() => action.run(copy, "Diagnostics copied.")}
      >
        <Copy size={16} />
        Copy diagnostics
      </Button>
      {(action.error || action.notice) && (
        <p
          className="sidebar-feedback"
          role={action.error ? "alert" : "status"}
        >
          {action.error || action.notice}
        </p>
      )}
    </>
  );
}
