import { createContext, useContext } from "react";
import { Button } from "./Button";
import type { GuideSection } from "./guideSections";

/** Opens the Guide page at a section; the shell provides it. */
export const GuideOpener = createContext<(section: GuideSection) => void>(
  () => {},
);

/** A link from help beside a task to the guide's section on it. */
export function GuideLink({
  section,
  onOpen,
}: {
  section: GuideSection;
  /** Runs first, such as closing the popover the link sits in. */
  onOpen?: () => void;
}) {
  const open = useContext(GuideOpener);
  return (
    <Button
      variant="link"
      className="guide-link"
      onClick={() => {
        onOpen?.();
        open(section);
      }}
    >
      Learn more
    </Button>
  );
}
