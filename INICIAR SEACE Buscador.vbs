Dim carpeta, bat, shell
carpeta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
bat = carpeta & "run_windows.bat"
Set shell = CreateObject("WScript.Shell")
shell.Run "cmd.exe /k """ & bat & """", 1, True
Set shell = Nothing
