Option Explicit
Dim shell, fs, folder, link
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
Set link = shell.CreateShortcut(shell.SpecialFolders("Desktop") & "\Workdesk.lnk")
link.TargetPath = folder & "\Workdesk.exe"
link.WorkingDirectory = folder
link.IconLocation = folder & "\_internal\assets\workdesk.ico,0"
link.Description = "Workdesk"
link.Save
