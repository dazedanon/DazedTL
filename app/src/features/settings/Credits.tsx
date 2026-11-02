import { ActionList, ActionRow } from "../../ui/ActionList";
import { PageBody } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";

type Credit = { name: string; work: string };

const dazedtl: Credit[] = [
  {
    name: "Len",
    work: "Assistant-led's game-translation skills, the Forge in-game editor with serjura, and WolfDawn for Wolf RPG games.",
  },
  { name: "serjura", work: "The Forge in-game editor, with Len." },
  {
    name: "Kao_SSS",
    work: "TL Inspector, which shows where each line of a playtested game comes from.",
  },
  { name: "Sakura", work: "The idea for TL Inspector." },
  {
    name: "Sinflower",
    work: "RV2JSON, which reads VX Ace games, and UberWolf, which GameUpdate uses for Wolf RPG games.",
  },
];

const dazedmtltool: Credit[] = [
  {
    name: "Len",
    work: "Forge support, Mistral and Gemini support, adaptive rate limiting and Batch translation.",
  },
  {
    name: "Kao_SSS",
    work: "ImageTL, the semi-automatic image translation workflow.",
  },
  {
    name: "m5kro",
    work: "Other API providers, more target languages, line width settings and start scripts.",
  },
  {
    name: "Kryomaani",
    work: "Clearer errors and handling of empty lines.",
  },
  {
    name: "Retaliate7731",
    work: "Better support for models other than OpenAI's.",
  },
  { name: "xorxorrax", work: "Code cleanup." },
];

function Credits({ credits }: { credits: Credit[] }) {
  return (
    <ActionList>
      {credits.map(({ name, work }) => (
        <ActionRow key={name} title={name} description={work} />
      ))}
    </ActionList>
  );
}

/** The people who built DazedTL and the tool it grew from. */
export default function CreditsTab() {
  return (
    <PageBody>
      <p className="settings-intro">
        DazedTL is made by DazedAnon, with help from these people.
      </p>
      <Section title="DazedTL">
        <Credits credits={dazedtl} />
      </Section>
      <Section title="DazedMTLTool" hint="The tool DazedTL grew from">
        <Credits credits={dazedmtltool} />
      </Section>
    </PageBody>
  );
}
