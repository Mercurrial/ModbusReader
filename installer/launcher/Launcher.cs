// installer/launcher/Launcher.cs — ModbusReader.exe in the installation folder.
//
// An installed ModbusReader keeps every version in its own folder:
//
//     ModbusReader\ModbusReader.exe        this launcher (shortcuts, taskbar
//                                          pins and .mbproj files point here)
//     ModbusReader\app-26.10.3\…           a version (the PyInstaller folder)
//     ModbusReader\app-26.10.4\…           the next one, put there while the
//                                          old one was still running
//     ModbusReader\unins000.exe            the uninstaller
//
// The launcher starts the newest version whose installation finished (the
// installer writes ".installed" into the folder last) and passes its command
// line on. An update therefore never has to replace a file that is in use,
// and "restart to update" takes as long as starting the program.
//
// Built by tools/build_installer.py with the C# compiler every Windows has
// (.NET Framework 4: C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Forms;

static class Launcher
{
    const string Prefix = "app-";
    const string Program = "ModbusReader.exe";
    const string Marker = ".installed";

    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string dir = Newest(root);
        if (dir == null)
        {
            // Unattended runs (roll-out scripts, the tests) get the exit
            // code only — a message box would wait for somebody forever.
            if (Environment.GetEnvironmentVariable("MODBUSREADER_LAUNCHER_QUIET") == "1")
                return 2;
            bool ru = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "ru";
            MessageBox.Show(
                ru ? "Не найдена установленная версия программы. Переустановите ModbusReader."
                   : "No installed version of the program was found. Please reinstall ModbusReader.",
                "ModbusReader", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }
        var psi = new ProcessStartInfo(Path.Combine(dir, Program), JoinArgs(args));
        psi.UseShellExecute = false;
        psi.WorkingDirectory = dir;
        try
        {
            Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show(e.Message, "ModbusReader", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 3;
        }
        return 0;
    }

    // The folder of the highest version that finished installing.
    static string Newest(string root)
    {
        string best = null;
        Version bestVersion = null;
        string[] dirs;
        try
        {
            dirs = Directory.GetDirectories(root, Prefix + "*");
        }
        catch (Exception)
        {
            return null;
        }
        foreach (string d in dirs)
        {
            Version v;
            if (!Version.TryParse(Path.GetFileName(d).Substring(Prefix.Length), out v))
                continue;
            if (!File.Exists(Path.Combine(d, Program)) || !File.Exists(Path.Combine(d, Marker)))
                continue;
            if (bestVersion == null || v > bestVersion)
            {
                best = d;
                bestVersion = v;
            }
        }
        return best;
    }

    // The arguments back into one command line, quoted the way the C runtime
    // reads them (a path with spaces, a trailing backslash, embedded quotes).
    static string JoinArgs(string[] args)
    {
        var sb = new StringBuilder();
        foreach (string a in args)
        {
            if (sb.Length > 0)
                sb.Append(' ');
            sb.Append(Quote(a));
        }
        return sb.ToString();
    }

    static string Quote(string a)
    {
        if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            return a;
        var sb = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in a)
        {
            if (c == '\\')
            {
                slashes++;
                continue;
            }
            if (c == '"')
                sb.Append('\\', slashes * 2 + 1);
            else
                sb.Append('\\', slashes);
            slashes = 0;
            sb.Append(c);
        }
        sb.Append('\\', slashes * 2);
        sb.Append('"');
        return sb.ToString();
    }
}
