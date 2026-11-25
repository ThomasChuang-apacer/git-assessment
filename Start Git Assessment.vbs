Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
folder = fileSystem.GetParentFolderName(WScript.ScriptFullName)
Set processEnvironment = shell.Environment("PROCESS")
processEnvironment("GIT_ASSESSMENT_HIDDEN") = "1"

port = processEnvironment("GIT_ASSESSMENT_PORT")
If Len(port) = 0 Then port = "8765"
url = "http://127.0.0.1:" & port & "/"
healthUrl = "http://127.0.0.1:" & port & "/api/health"

instanceState = CheckExistingInstance(healthUrl, url, folder)
If instanceState = "same" Then
  If processEnvironment("GIT_ASSESSMENT_NO_BROWSER") <> "1" Then
    shell.Run url, 1, False
  End If
  WScript.Quit 0
ElseIf instanceState = "other" Then
  MsgBox "Port " & port & " is already in use by another Git Assessment folder." & vbCrLf & vbCrLf & "Please close the running Git Assessment first, or set a different GIT_ASSESSMENT_PORT before starting.", vbExclamation, "Git Assessment"
  WScript.Quit 3
End If

If Not fileSystem.FileExists(folder & "\.venv\Scripts\python.exe") Then
  progressCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & folder & "\scripts\First Start Git Assessment.ps1" & Chr(34) & " -ProjectRoot " & Chr(34) & folder & Chr(34) & " -Mode FirstStart"
  shell.Run progressCommand, 1, False
  WScript.Quit 0
End If

If processEnvironment("GIT_ASSESSMENT_NO_BROWSER") <> "1" Then
  progressCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & folder & "\scripts\First Start Git Assessment.ps1" & Chr(34) & " -ProjectRoot " & Chr(34) & folder & Chr(34) & " -Mode Starting"
  shell.Run progressCommand, 1, False
  WScript.Quit 0
End If

command = shell.ExpandEnvironmentStrings("%ComSpec%") & " /d /c " & Chr(34) & Chr(34) & folder & "\scripts\start.bat" & Chr(34) & Chr(34)
shell.Run command, 0, False

Function NormalizePath(value)
  Dim cleaned
  cleaned = LCase(Trim(Replace(value, "/", "\")))
  Do While Len(cleaned) > 1 And Right(cleaned, 1) = "\"
    cleaned = Left(cleaned, Len(cleaned) - 1)
  Loop
  NormalizePath = cleaned
End Function

Function ExtractJsonString(text, key)
  Dim pattern, pos, startPos, idx, ch, escaped, raw, hexCode
  pattern = """" & key & """:"""
  pos = InStr(1, text, pattern, vbTextCompare)
  If pos = 0 Then
    pattern = """" & key & """: """
    pos = InStr(1, text, pattern, vbTextCompare)
  End If
  If pos = 0 Then
    ExtractJsonString = ""
    Exit Function
  End If
  startPos = pos + Len(pattern)
  raw = ""
  escaped = False
  idx = startPos
  Do While idx <= Len(text)
    ch = Mid(text, idx, 1)
    If escaped Then
      If ch = "u" And idx + 4 <= Len(text) Then
        hexCode = Mid(text, idx + 1, 4)
        raw = raw & ChrW(CLng("&H" & hexCode))
        idx = idx + 4
      Else
        raw = raw & ch
      End If
      escaped = False
    ElseIf ch = "\" Then
      escaped = True
    ElseIf ch = """" Then
      Exit Do
    Else
      raw = raw & ch
    End If
    idx = idx + 1
  Loop
  ExtractJsonString = raw
End Function

Function CheckExistingInstance(healthAddress, homeAddress, expectedFolder)
  On Error Resume Next
  Set request = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  request.setTimeouts 300, 300, 500, 500
  request.Open "GET", healthAddress, False
  request.Send

  If Err.Number = 0 And request.Status = 200 Then
    Dim body, runningRoot
    body = request.responseText
    runningRoot = ExtractJsonString(body, "project_root")
    If Len(runningRoot) > 0 Then
      If NormalizePath(runningRoot) = NormalizePath(expectedFolder) Then
        CheckExistingInstance = "same"
      Else
        CheckExistingInstance = "other"
      End If
      Err.Clear
      On Error GoTo 0
      Exit Function
    End If
  End If
  Err.Clear

  request.Open "GET", homeAddress, False
  request.Send
  If Err.Number = 0 And request.Status = 200 Then
    If InStr(1, request.responseText, "name=""git-assessment-token""", vbTextCompare) > 0 Then
      CheckExistingInstance = "other"
    Else
      CheckExistingInstance = "none"
    End If
  Else
    CheckExistingInstance = "none"
  End If
  Err.Clear
  On Error GoTo 0
End Function
