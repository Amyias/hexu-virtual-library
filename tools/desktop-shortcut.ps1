# Unicode Shell Link interfaces avoid WScript.Shell's ANSI path conversion.
$ErrorActionPreference = 'Stop'
$spec = Get-Content -LiteralPath $env:HEXU_SHORTCUT_SPEC -Raw -Encoding UTF8 | ConvertFrom-Json
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
namespace HexuShortcut {
 [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
 internal class ShellLink { }
 [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 internal interface IShellLinkW {
  void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, IntPtr data, uint flags);
  void GetIDList(out IntPtr list);
  void SetIDList(IntPtr list);
  void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int size);
  void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
  void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size);
  void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string path);
  void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int size);
  void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
  void GetHotkey(out short key);
  void SetHotkey(short key);
  void GetShowCmd(out int command);
  void SetShowCmd(int command);
  void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, out int index);
  void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
  void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
  void Resolve(IntPtr window, uint flags);
  void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
 }
 public class Info {
  public string Target;
  public string WorkingDirectory;
  public string Description;
  public string Icon;
 }
 public static class Links {
  [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
  static extern void SHChangeNotify(uint change, uint flags, string path, IntPtr other);
  public static void Refresh(string path) { SHChangeNotify(0x2000, 0x1005, path, IntPtr.Zero); }
  static Info Inspect(IShellLinkW link) {
   var target=new StringBuilder(32768); var directory=new StringBuilder(32768);
   var description=new StringBuilder(1024); var icon=new StringBuilder(32768); int index;
   link.GetPath(target,target.Capacity,IntPtr.Zero,4);
   link.GetWorkingDirectory(directory,directory.Capacity);
   link.GetDescription(description,description.Capacity);
   link.GetIconLocation(icon,icon.Capacity,out index);
   return new Info { Target=target.ToString(), WorkingDirectory=directory.ToString(),
    Description=description.ToString(), Icon=icon.ToString()+","+index };
  }
  public static Info Read(string file) {
   var link=(IShellLinkW)new ShellLink();
   try { ((IPersistFile)link).Load(file,0); return Inspect(link); }
   finally { Marshal.FinalReleaseComObject(link); }
  }
  public static void Write(string file,string target,string directory,string description,string icon) {
   var link=(IShellLinkW)new ShellLink();
   try {
    link.SetPath(target); link.SetWorkingDirectory(directory); link.SetDescription(description);
    link.SetIconLocation(icon,0); ((IPersistFile)link).Save(file,true);
   } finally { Marshal.FinalReleaseComObject(link); }
   Refresh(file);
  }
  public static bool UpdatePinned(string file,string target,string icon) {
   var link=(IShellLinkW)new ShellLink();
   try {
    ((IPersistFile)link).Load(file,0);
    if (!String.Equals(Inspect(link).Target,target,StringComparison.OrdinalIgnoreCase)) return false;
    link.SetIconLocation(icon,0); ((IPersistFile)link).Save(file,true);
   } finally { Marshal.FinalReleaseComObject(link); }
   Refresh(file);
   if (Read(file).Icon != icon+",0") throw new InvalidOperationException("Pinned icon readback mismatch");
   return true;
  }
 }
}
"@
$desktop = $spec.directory
if (-not $desktop) { $desktop = [Environment]::GetFolderPath('Desktop') }
if (-not (Test-Path -LiteralPath $spec.target -PathType Leaf)) { throw 'Shortcut target missing' }
if (-not (Test-Path -LiteralPath $spec.icon -PathType Leaf)) { throw 'Shortcut icon missing' }
$link = Join-Path $desktop ($spec.name + '.lnk')
[HexuShortcut.Links]::Write($link, $spec.target, $spec.workingDirectory, $spec.description, $spec.icon)
$check = [HexuShortcut.Links]::Read($link)
$pinned = $spec.pinnedDirectory
if (-not $pinned) { $pinned = Join-Path $env:APPDATA 'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar' }
$updatedPinned = 0
if (Test-Path -LiteralPath $pinned) {
 foreach ($pin in Get-ChildItem -LiteralPath $pinned -Filter '*.lnk' -File) {
  # An unreadable unrelated shortcut must not prevent the application's own shortcut creation.
  try { $existing = [HexuShortcut.Links]::Read($pin.FullName) } catch { continue }
  if ($existing.Target -eq $spec.target) {
   if ([HexuShortcut.Links]::UpdatePinned($pin.FullName, $spec.target, $spec.icon)) { $updatedPinned++ }
  }
 }
}
[HexuShortcut.Links]::Refresh($spec.target)
$report = [ordered]@{
 link = $link
 target = $check.Target
 icon = $check.Icon
 updatedPinned = $updatedPinned
 pinnedVerified = $true
 matches = ($check.Target -eq $spec.target) -and ($check.WorkingDirectory -eq $spec.workingDirectory) -and ($check.Description -eq $spec.description) -and ($check.Icon -eq ($spec.icon + ',0'))
 exists = (Test-Path -LiteralPath $link)
}
($report | ConvertTo-Json) | Out-File -LiteralPath $env:HEXU_SHORTCUT_REPORT -Encoding UTF8
