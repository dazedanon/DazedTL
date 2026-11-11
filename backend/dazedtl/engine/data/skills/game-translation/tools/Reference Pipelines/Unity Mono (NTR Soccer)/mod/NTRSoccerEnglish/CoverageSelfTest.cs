using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace NTRSoccerEnglish
{
    /// <summary>
    /// Answers DazedTL's coverage probes, which packaging waits for. The
    /// project helper's `hook-probes` writes every exported line as the game
    /// shows it, each placeholder the code fills already filled, into the
    /// game's DazedTL work folder, which no patch carries and no player has.
    /// When that list exists at startup, each probe goes through the same
    /// store lookup the text hooks use, and what the game would show is
    /// written for `hook-probes --check`, which judges it: a miss, Japanese,
    /// a carriage return or a lost filled value holds the patch.
    ///
    /// A lookup of the unfilled line proves nothing: a whole-string key for
    /// "報酬{0}ゴールド" hits it while the game shows "報酬1000ゴールド",
    /// which only a pattern matches.
    /// </summary>
    internal static class CoverageSelfTest
    {
        internal const string ProbeList = ".dazedtl/len-method/work/hook-probes.jsonl";
        internal const string ResultList = ".dazedtl/len-method/work/hook-results.jsonl";

        /// <summary>Call once the store has loaded, with the game's folder.</summary>
        public static void Run(string gameRoot)
        {
            var probes = Path.Combine(gameRoot, ProbeList);
            if (!File.Exists(probes)) return;
            try
            {
                var bytes = File.ReadAllBytes(probes);
                var sb = new StringBuilder();
                // names the list it answers, so answers to an older one refuse
                sb.Append("{\"probes\":").Append(Quote(Sha256(bytes))).Append("}\n");
                int answered = 0, missed = 0;
                foreach (var line in Encoding.UTF8.GetString(bytes).Split('\n'))
                {
                    if (line.Trim().Length == 0) continue;
                    string id = null, text = null;
                    foreach (var kv in JsonFlat.Parse(line))
                    {
                        if (kv.Key == "id") id = kv.Value;
                        else if (kv.Key == "text") text = kv.Value;
                    }
                    if (id == null || text == null) continue;
                    sb.Append("{\"id\":").Append(Quote(id));
                    if (TranslationStore.TryGet(text, out var shown))
                    {
                        sb.Append(",\"shown\":").Append(Quote(shown));
                        answered++;
                    }
                    else missed++;
                    sb.Append("}\n");
                }
                var results = Path.Combine(gameRoot, ResultList);
                var temporary = results + ".tmp";
                File.WriteAllText(temporary, sb.ToString(), new UTF8Encoding(false));
                if (File.Exists(results)) File.Delete(results);
                File.Move(temporary, results);
                Plugin.Log.LogInfo(
                    $"coverage self-test: {answered} answered, {missed} missed; run hook-probes --check");
            }
            catch (Exception e)
            {
                // the self-test must never stop the game
                Plugin.Log.LogError($"coverage self-test failed: {e.Message}");
            }
        }

        private static string Sha256(byte[] bytes)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }

        private static string Quote(string s)
        {
            var sb = new StringBuilder(s.Length + 2);
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }
    }
}
