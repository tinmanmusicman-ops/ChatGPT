#Requires AutoHotkey v2.0
#SingleInstance Force

global ProjectDir := A_ScriptDir
global PythonExe := ProjectDir "\.venv\Scripts\python.exe"
global EvaluatorScript := ProjectDir "\evaluate_job_fit.py"
global TmpDir := ProjectDir "\tmp"
global LogsDir := ProjectDir "\logs"
global LastResult := LogsDir "\last_result.txt"
global LauncherLog := LogsDir "\launcher_debug.log"

DirCreate(LogsDir)
WriteLauncherLog("Launcher start. Args=" A_Args.Length)

if (A_Args.Length >= 1) {
    inputPath := A_Args[1]
    WriteLauncherLog("File-mode input=" inputPath)
    if !FileExist(inputPath) {
        WriteLauncherLog("ERROR missing file: " inputPath)
        MsgBox "Selected file does not exist:`n" inputPath, "Evaluate Job Fit", "Iconx"
        ExitApp
    }
    RunEvaluation(inputPath)
    ExitApp
}

^#j::CaptureAndEvaluate()

CaptureAndEvaluate() {
    global TmpDir
    WriteLauncherLog("Hotkey flow started.")
    savedClipboard := ClipboardAll()
    A_Clipboard := ""
    Send "^c"
    if !ClipWait(1.5) {
        A_Clipboard := savedClipboard
        WriteLauncherLog("ERROR clipboard capture timed out.")
        MsgBox "No selected text was captured. Highlight text first, then try again.", "Evaluate Job Fit", "Iconx"
        return
    }

    selectedText := Trim(A_Clipboard)
    A_Clipboard := savedClipboard
    if (selectedText = "") {
        WriteLauncherLog("ERROR clipboard capture returned empty text.")
        MsgBox "No selected text was captured. Highlight text first, then try again.", "Evaluate Job Fit", "Iconx"
        return
    }

    DirCreate(TmpDir)
    tempPath := TmpDir "\job_selection.txt"
    if FileExist(tempPath) {
        FileDelete(tempPath)
    }
    FileAppend(selectedText, tempPath, "UTF-8")
    WriteLauncherLog("Captured selection bytes=" StrLen(selectedText) " temp=" tempPath)
    RunEvaluation(tempPath)
}

RunEvaluation(inputPath) {
    global ProjectDir, PythonExe, EvaluatorScript, LogsDir, LastResult
    if !FileExist(PythonExe) {
        WriteLauncherLog("ERROR Python venv executable missing: " PythonExe)
        MsgBox "Python venv executable not found:`n" PythonExe, "Evaluate Job Fit", "Iconx"
        return
    }
    if !FileExist(EvaluatorScript) {
        WriteLauncherLog("ERROR evaluator script missing: " EvaluatorScript)
        MsgBox "Evaluator script not found:`n" EvaluatorScript, "Evaluate Job Fit", "Iconx"
        return
    }

    DirCreate(LogsDir)
    command := '"' PythonExe '" "' EvaluatorScript '" "' inputPath '"'
    WriteLauncherLog("RunWait command=" command)
    exitCode := RunWait(command, ProjectDir, "Hide")
    WriteLauncherLog("RunWait exitCode=" exitCode)
    if (exitCode != 0) {
        WriteLauncherLog("ERROR evaluator failed with non-zero exit.")
        MsgBox "Evaluation failed. Check the terminal output or logs for details.", "Evaluate Job Fit", "Iconx"
        return
    }

    if FileExist(LastResult) {
        WriteLauncherLog("Success. Skipping old text viewer.")
    } else {
        WriteLauncherLog("ERROR evaluation succeeded but last_result missing.")
        MsgBox "Evaluation completed, but last_result.txt was not found.", "Evaluate Job Fit", "Iconx"
    }
}

WriteLauncherLog(message) {
    global LauncherLog
    timestamp := FormatTime(, "yyyy-MM-dd HH:mm:ss")
    FileAppend(timestamp " | " message "`n", LauncherLog, "UTF-8")
}
