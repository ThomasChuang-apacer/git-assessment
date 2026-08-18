Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
folder = fileSystem.GetParentFolderName(WScript.ScriptFullName)
Set processEnvironment = shell.Environment("PROCESS")
processEnvironment("GIT_ASSESSMENT_HIDDEN") = "1"

port = processEnvironment("GIT_ASSESSMENT_PORT")
If Len(port) = 0 Then port = "8765"
url = "http://127.0.0.1:" & port & "/"

If IsGitAssessmentRunning(url) Then
  If processEnvironment("GIT_ASSESSMENT_NO_BROWSER") <> "1" Then
    shell.Run url, 1, False
  End If
  WScript.Quit 0
End If

If Not fileSystem.FileExists(folder & "\.venv\Scripts\python.exe") Then
  progressCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & folder & "\scripts\First Start Git Assessment.ps1" & Chr(34) & " -ProjectRoot " & Chr(34) & folder & Chr(34)
  shell.Run progressCommand, 1, False
  WScript.Quit
End If

command = shell.ExpandEnvironmentStrings("%ComSpec%") & " /d /c " & Chr(34) & Chr(34) & folder & "\scripts\start.bat" & Chr(34) & Chr(34)
shell.Run command, 0, False

Function IsGitAssessmentRunning(address)
  On Error Resume Next
  Set request = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  request.setTimeouts 300, 300, 500, 500
  request.Open "GET", address, False
  request.Send

  If Err.Number = 0 And request.Status = 200 Then
    IsGitAssessmentRunning = InStr(1, request.responseText, "name=""git-assessment-token""", vbTextCompare) > 0
  Else
    IsGitAssessmentRunning = False
  End If
  Err.Clear
  On Error GoTo 0
End Function
