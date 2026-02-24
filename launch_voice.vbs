Dim fso, scriptDir, voicePath, pythonwPath
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
voicePath = fso.BuildPath(scriptDir, "voice.py")

' Tenta pythonw.exe do Python 3.13 (path classico), fallback para PATH
pythonwPath = "C:\Users\joaop\AppData\Local\Programs\Python\Python313\pythonw.exe"
If Not fso.FileExists(pythonwPath) Then
    pythonwPath = "pythonw.exe"
End If

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & pythonwPath & """ """ & voicePath & """", 0, False
