' 珉鸟桌宠 启动器 / silent launcher
' 双击即可启动，不会弹出黑色命令行窗口。
Option Explicit

Dim sh, fso, here, cmd, exePath, scriptPath, pyw, candidates, i, found

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

' 1) packaged exe (preferred)
exePath = here & "\MinBirdPet.exe"
If Not fso.FileExists(exePath) Then exePath = here & "\dist\MinBirdPet.exe"

If fso.FileExists(exePath) Then
  cmd = """" & exePath & """"
Else
  ' 2) fall back to running the python source with pythonw
  scriptPath = here & "\minbird_pet.py"
  If Not fso.FileExists(scriptPath) Then
    MsgBox "找不到 MinBirdPet.exe 或 minbird_pet.py", 16, "珉鸟桌宠"
    WScript.Quit 1
  End If

  candidates = Array( _
    here & "\.venv\Scripts\pythonw.exe", _
    "pythonw.exe")

  found = ""
  For i = 0 To UBound(candidates)
    If InStr(candidates(i), "\") > 0 Then
      If fso.FileExists(candidates(i)) Then
        found = candidates(i)
        Exit For
      End If
    Else
      found = candidates(i)
      Exit For
    End If
  Next

  cmd = """" & found & """ """ & scriptPath & """"
End If

sh.Run cmd, 0, False
