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
