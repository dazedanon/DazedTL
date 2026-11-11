using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace SheepClickerTL
{
    /// <summary>
    /// Titles the game window with the exact text the project helper's
    /// `window-title` prints, "English Title v1.0.9 | TL: Name". Unity titles
    /// the window with the product name, which also names the save folder
    /// (persistentDataPath), so the product name stays and only the window's
    /// text changes: SetWindowTextW on this process's visible UnityWndClass
    /// window. The title is checked every second, so it lands once the window
    /// exists and returns if anything resets it. The checks run on a timer,
    /// not a Unity object: Labyrinth City Asylum's coroutines on BepInEx's
    /// manager object never ran, and a timer works the same in Mono and
    /// IL2CPP plugins. Call Keep from the plugin's Load or Awake.
    /// </summary>
    internal static class WindowTitle
    {
        // Replace with the project helper's `window-title` output at each delivery.
        internal const string Title = "English Title v1.0.0 | TL: Translator";

        private const string UnityWindowClass = "UnityWndClass";
        private const int ReportAfter = 10;
        private static Timer _timer;
        private static IntPtr _window = IntPtr.Zero;
        private static int _checks;
        private static bool _titled;

        internal static void Keep(string title = Title)
        {
            if (Environment.OSVersion.Platform != PlatformID.Win32NT || string.IsNullOrEmpty(title)) return;
            // One check at a time: the next starts a second after the last ends.
            _timer = new Timer(_ => Check(title), null, 0, Timeout.Infinite);
        }

        private static void Check(string title)
        {
            if (!Apply(title)) return;
            _checks++;
            if (_window == IntPtr.Zero && _checks == ReportAfter)
                Plugin.Log.LogWarning($"No Unity window after {ReportAfter} s; this process's windows: {Describe()}");
            _timer.Change(1000, Timeout.Infinite);
        }

        /// <summary>Sets the title if the window shows another; false when
        /// the Windows calls are unavailable, which ends the checks.</summary>
        private static bool Apply(string title)
        {
            try
            {
                if (_window == IntPtr.Zero || !IsWindow(_window)) _window = Find();
                if (_window == IntPtr.Zero || Text(_window) == title) return true;
                if (!SetWindowTextW(_window, title))
                    Plugin.Log.LogWarning($"Window title not set: error {Marshal.GetLastWin32Error()}.");
                else if (!_titled)
                {
                    _titled = true;
                    Plugin.Log.LogInfo($"Window titled \"{title}\".");
                }
                return true;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Window title not set: {e.Message}");
                return false;
            }
        }

        /// <summary>This process's visible Unity window, or zero before it exists.</summary>
        private static IntPtr Find()
        {
            IntPtr found = IntPtr.Zero;
            Each(window =>
            {
                if (!IsWindowVisible(window) || Class(window) != UnityWindowClass) return true;
                found = window;
                return false;
            });
            return found;
        }

        private static string Describe()
        {
            var rows = new List<string>();
            Each(window =>
            {
                rows.Add($"{Class(window)} \"{Text(window)}\" visible={IsWindowVisible(window)}");
                return true;
            });
            return rows.Count == 0 ? "none" : string.Join("; ", rows.ToArray());
        }

        /// <summary>Calls `visit` on each top-level window of this process
        /// until it returns false.</summary>
        private static void Each(Func<IntPtr, bool> visit)
        {
            uint process = GetCurrentProcessId();
            EnumWindowsProc callback = (window, _) =>
            {
                GetWindowThreadProcessId(window, out uint owner);
                return owner != process || visit(window);
            };
            EnumWindows(callback, IntPtr.Zero);
            GC.KeepAlive(callback);
        }

        private static string Class(IntPtr window)
        {
            var name = new StringBuilder(256);
            GetClassNameW(window, name, name.Capacity);
            return name.ToString();
        }

        private static string Text(IntPtr window)
        {
            var text = new StringBuilder(256);
            GetWindowTextW(window, text, text.Capacity);
            return text.ToString();
        }

        private delegate bool EnumWindowsProc(IntPtr window, IntPtr data);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr data);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);

        [DllImport("user32.dll")]
        private static extern bool IsWindow(IntPtr window);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr window);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetClassNameW(IntPtr window, StringBuilder name, int capacity);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowTextW(IntPtr window, StringBuilder text, int capacity);

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetWindowTextW(IntPtr window, string text);

        [DllImport("kernel32.dll")]
        private static extern uint GetCurrentProcessId();
    }
}
