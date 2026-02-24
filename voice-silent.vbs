Dim fso, scriptDir, voicePath
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
voicePath = fso.BuildPath(scriptDir, "voice.py")

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python.exe """ & voicePath & """", 0, False
