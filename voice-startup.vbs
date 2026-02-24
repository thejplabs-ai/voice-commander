Dim fso, scriptDir, voicePath
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
voicePath = fso.BuildPath(scriptDir, "voice.py")

Dim WShell
Set WShell = CreateObject("WScript.Shell")
WShell.Run "pythonw.exe """ & voicePath & """", 0, False
