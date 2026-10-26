/** The open project's languages for every view under it (languages.ts). */
import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { GameLanguages, Project } from "../api/contracts";
import { DEFAULT_LANGUAGES } from "./languages";

const Context = createContext<GameLanguages>(DEFAULT_LANGUAGES);

export function LanguagesProvider({
  project,
  children,
}: {
  project?: Project | null;
  children: ReactNode;
}) {
  const { source, target, characters } =
    project?.languages ?? DEFAULT_LANGUAGES;
  // One value per pair, so observations that keep it re-render nothing.
  const value = useMemo(
    () => ({ source, target, characters }),
    [source, target, characters],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** The open project's source and target language names. */
export function useLanguages(): GameLanguages {
  return useContext(Context);
}
