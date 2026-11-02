import { PageBody } from "../../ui/PageLayout";

/** What one person did: V2 is DazedTL, V1 is DazedMTLTool. */
type Credit = { name: string; v2?: string; v1?: string };

const credits: Credit[] = [
  {
    name: "Len",
    v2: "Assistant-led's game-translation skills, the Forge in-game editor with serjura, and WolfDawn for Wolf RPG games.",
    v1: "Forge support, Mistral and Gemini support, adaptive rate limiting and Batch translation.",
  },
  { name: "serjura", v2: "The Forge in-game editor, with Len." },
  {
    name: "Kao_SSS",
    v2: "TL Inspector, which shows where each line of a playtested game comes from.",
    v1: "ImageTL, the semi-automatic image translation workflow.",
  },
  { name: "Sakura", v2: "The idea for TL Inspector." },
  {
    name: "Sinflower",
    v2: "RV2JSON, which reads VX Ace games, and UberWolf, which GameUpdate uses for Wolf RPG games.",
  },
  {
    name: "m5kro",
    v1: "Other API providers, more target languages, line width settings and start scripts.",
  },
  { name: "Kryomaani", v1: "Clearer errors and handling of empty lines." },
  {
    name: "Retaliate7731",
    v1: "Better support for models other than OpenAI's.",
  },
  { name: "xorxorrax", v1: "Code cleanup." },
];

/** The people who built DazedTL and the tool it grew from, each once. */
export default function CreditsTab() {
  return (
    <PageBody>
      <p className="settings-intro">
        DazedTL is made by <strong>DazedAnon</strong>, with help from these
        people. V2 marks work on DazedTL, and V1 work on DazedMTLTool, the tool
        it grew from.
      </p>
      <dl className="credits">
        {credits.map(({ name, v2, v1 }) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>
              {(["V2", "V1"] as const).map((version) => {
                const work = version === "V2" ? v2 : v1;
                return (
                  work && (
                    <div key={version}>
                      <span className="badge">{version}</span>
                      {work}
                    </div>
                  )
                );
              })}
            </dd>
          </div>
        ))}
      </dl>
    </PageBody>
  );
}
