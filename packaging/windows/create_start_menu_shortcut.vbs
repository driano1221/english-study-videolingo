Set Fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

ScriptDir = Fso.GetParentFolderName(WScript.ScriptFullName)
RepoDir = Fso.GetAbsolutePathName(Fso.BuildPath(ScriptDir, "..\.."))
WorkspaceDir = Fso.GetParentFolderName(RepoDir)
ExePath = Fso.BuildPath(WorkspaceDir, "dist\VideoLingo Simples.exe")
If Not Fso.FileExists(ExePath) Then
    ExePath = Fso.BuildPath(RepoDir, "dist\VideoLingo Simples.exe")
End If

If Not Fso.FileExists(ExePath) Then
    WScript.Echo "Executável não encontrado. Execute build.ps1 primeiro."
    WScript.Quit 1
End If

Set Shortcut = WshShell.CreateShortcut(WshShell.SpecialFolders("Programs") & "\VideoLingo Simples.lnk")
Shortcut.TargetPath = ExePath
Shortcut.WorkingDirectory = Fso.GetParentFolderName(ExePath)
Shortcut.IconLocation = ExePath
Shortcut.Description = "VideoLingo - legendas para estudo de inglês"
Shortcut.Save
