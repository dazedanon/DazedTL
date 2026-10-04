import { Component, type ReactNode } from "react";
import { flushDrafts } from "../state/leaveGuards";
import { useAction } from "../state/useAction";
import { ActionControl } from "../ui/ActionControl";
import { reportRendererFailure } from "./rendererErrors";

function Recovery({ label, retry }: { label: string; retry: () => void }) {
  const action = useAction();
  const feedback = (key: string) => ({ pending: action.busy && action.key === key,
    error: action.key === key ? action.error : "", notice: action.key === key ? action.notice : "" });
  return <section className="view-recovery" aria-label="View recovery">
    <h2 role="alert">{label} couldn’t be displayed.</h2>
    <p>Try opening it again, or switch to another view. If the error continues, copy diagnostics and reload the interface. Running jobs stay active during recovery.</p>
    <div className="actions">
      <ActionControl label="Try again" variant="primary" disabled={action.busy} {...feedback("retry")}
        onClick={() => action.run(async () => { await flushDrafts(); retry(); }, "", "retry")} />
      <ActionControl label="Copy diagnostics" disabled={action.busy} {...feedback("copy")}
        onClick={() => action.run(() => window.dazedtl.copyDiagnostics(), "Diagnostics copied.", "copy")} />
      <ActionControl label="Reload interface" disabled={action.busy} {...feedback("reload")}
        onClick={() => action.run(async () => { await flushDrafts(); await window.dazedtl.reloadInterface(); }, "", "reload")} />
    </div>
  </section>;
}

/** Keep navigation and the application observer alive when an individual view fails. */
type Props = { label: string; children: ReactNode; resetKey?: string };
type State = { failed: boolean; resetKey?: string };
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };
  static getDerivedStateFromProps(props: Props, state: State) {
    return props.resetKey !== state.resetKey ? { failed: false, resetKey: props.resetKey } : null;
  }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { reportRendererFailure(error); }
  render() {
    return this.state.failed ? <Recovery label={this.props.label} retry={() => this.setState({ failed: false })} /> : this.props.children;
  }
}
