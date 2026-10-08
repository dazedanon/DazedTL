import protocol from "../../../backend/dazedtl/api/protocol.json";
import type { RpcContract } from "./contracts";
import { ApiError, type ErrorCode, messageOf } from "./errors";
import type { RendererFailure } from "./errors";

type Method = keyof RpcContract;
type AssertNever<T extends never> = T;
// Compile-time drift checks against the manifest used by Electron and Python.
type MissingClientMethods = AssertNever<
  Exclude<keyof typeof protocol.methods, Method>
>;
type MissingManifestMethods = AssertNever<
  Exclude<Method, keyof typeof protocol.methods>
>;
export type ProtocolCoverage = [MissingClientMethods, MissingManifestMethods];
type Envelope =
  | { version: string; ok: true; value: unknown }
  | {
      version: string;
      ok: false;
      error: { code: ErrorCode; message: string; details?: unknown };
    };
/** What the update controller in the main process reports. */
export type UpdateState = {
  /** A Git checkout updates through Git, never through the app. */
  git: boolean;
  version: string;
  channel: "stable" | "beta";
  status: "idle" | "checking" | "downloading" | "ready" | "error";
  /** Download progress in percent, or -1 while the size is unknown. */
  progress: number;
  /** The newest release newer than this install, if a check found one. */
  latest: string;
  /** A downloaded release the next start installs. */
  staged: string;
  /** "Go back" was requested; the next start restores `previous`. */
  revert: boolean;
  /** The version before the last update, which "Go back" restores. */
  previous: string;
  /** A version the user went back from; automatic checks leave it alone. */
  skipped: string;
  checkedAt: string;
  error: string;
  /** How the last install at startup went, reported once. */
  outcome: {
    ok: boolean;
    version: string;
    from: string;
    message: string;
  } | null;
};
declare global {
  interface Window {
    dazedtl: {
      /** The user's home folder, for showing paths home-relative. */
      home: string;
      call(version: string, method: string, params: object): Promise<Envelope>;
      ready(): Promise<void>;
      copyDiagnostics(): Promise<void>;
      reportRendererError(failure: RendererFailure): Promise<void>;
      reloadInterface(): Promise<void>;
      copyText(text: string): Promise<void>;
      chooseFolder(): Promise<string | null>;
      chooseEditor(): Promise<string | null>;
      openFolder(
        kind:
          "project" | "workspace" | "projectWorkspace" | "output" | "backup",
        path?: string,
      ): Promise<void>;
      onClose(handler: () => Promise<void>, cancelled: () => void): () => void;
      onStopped(handler: (message: string) => void): () => void;
      updates: {
        state(): Promise<UpdateState>;
        check(): Promise<UpdateState>;
        channel(channel: UpdateState["channel"]): Promise<UpdateState>;
        revert(): Promise<UpdateState>;
        keep(): Promise<UpdateState>;
        restart(): Promise<void>;
        onState(handler: (state: UpdateState) => void): () => void;
      };
    };
  }
}
const observers = new Set<(phase: "begin" | "end") => void>();
export function onMutation(observer: (phase: "begin" | "end") => void) {
  observers.add(observer);
  return () => {
    observers.delete(observer);
  };
}
function notify(phase: "begin" | "end") {
  for (const observer of observers) observer(phase);
}
export async function request<M extends Method>(
  method: M,
  params: RpcContract[M]["request"],
): Promise<RpcContract[M]["response"]> {
  const refresh = protocol.methods[method].refresh;
  if (refresh) notify("begin");
  try {
    const reply = await window.dazedtl.call(protocol.version, method, params);
    if (
      !reply ||
      reply.version !== protocol.version ||
      typeof reply.ok !== "boolean"
    )
      throw new ApiError(
        "protocol",
        "The application and backend versions do not match. Restart after updating.",
      );
    if (!reply.ok) {
      if (!reply.error || typeof reply.error.message !== "string")
        throw new ApiError(
          "protocol",
          "The backend returned an invalid error response.",
        );
      throw new ApiError(
        reply.error.code,
        reply.error.message,
        reply.error.details,
      );
    }
    if (!("value" in reply))
      throw new ApiError(
        "protocol",
        "The backend returned an incomplete response.",
      );
    return reply.value as RpcContract[M]["response"];
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("unavailable", messageOf(error));
  } finally {
    if (refresh) notify("end");
  }
}
