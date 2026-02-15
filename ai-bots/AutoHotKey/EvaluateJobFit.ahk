#Requires AutoHotkey v2.0
#SingleInstance Force

global ProjectDir := A_ScriptDir
global ContentSummaryDir := ProjectDir "\..\ContentSummary"
global PythonExe := ProjectDir "\.venv\Scripts\python.exe"
global EvaluatorScript := ProjectDir "\evaluate_job_fit.py"
global SummarizerScript := ContentSummaryDir "\summarize_content.py"
global ContentBridgeScript := ContentSummaryDir "\content_summary_bridge.py"
global TmpDir := ProjectDir "\tmp"
global LogsDir := ProjectDir "\logs"
global ContentTmpDir := ContentSummaryDir "\tmp"
global ContentLogsDir := ContentSummaryDir "\logs"
global LastResult := LogsDir "\last_result.txt"
global LastContentSummaryText := ContentLogsDir "\last_content_summary.txt"
global LastContentSummaryHtml := ContentLogsDir "\last_content_summary.html"
global LastContentSummaryError := ContentLogsDir "\last_content_summary_error.txt"
global LauncherLog := LogsDir "\launcher_debug.log"

DirCreate(LogsDir)
WriteLauncherLog("Launcher start. Args=" A_Args.Length)
EnsureContentSummaryBridge()

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
^#s::CaptureAndSummarize()

CaptureAndEvaluate() {
    global TmpDir
    WriteLauncherLog("Hotkey flow started.")
    savedClipboard := ClipboardAll()
    A_Clipboard := ""
    ; Auto-select current focused text region and copy.
    Send "^a"
    Sleep 120
    Send "^c"
    if !ClipWait(0.8) {
        A_Clipboard := savedClipboard
        WriteLauncherLog("ERROR auto-select clipboard capture timed out.")
        MsgBox "No selected text was captured. Highlight text first, then try again.", "Evaluate Job Fit", "Iconx"
        return
    }

    selectedText := Trim(A_Clipboard)
    A_Clipboard := savedClipboard
    if (selectedText = "") {
        WriteLauncherLog("ERROR auto-select clipboard capture returned empty text.")
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

CaptureAndSummarize() {
    global ContentTmpDir
    WriteLauncherLog("Summarize hotkey flow started.")
    savedClipboard := ClipboardAll()
    A_Clipboard := ""
    ; Auto-select current focused text region and copy.
    Send "^a"
    Sleep 120
    Send "^c"
    if !ClipWait(0.8) {
        A_Clipboard := savedClipboard
        WriteLauncherLog("ERROR summarize auto-select clipboard capture timed out.")
        MsgBox "No text selected to summarize.", "Content Summary", "Iconx"
        return
    }

    selectedText := Trim(A_Clipboard)
    A_Clipboard := savedClipboard
    if (selectedText = "") {
        WriteLauncherLog("ERROR summarize auto-select clipboard capture returned empty text.")
        MsgBox "No text selected to summarize.", "Content Summary", "Iconx"
        return
    }

    DirCreate(ContentTmpDir)
    tempPath := ContentTmpDir "\content.txt"
    if FileExist(tempPath) {
        FileDelete(tempPath)
    }
    FileAppend(selectedText, tempPath, "UTF-8")
    WriteLauncherLog("Summarize captured selection bytes=" StrLen(selectedText) " temp=" tempPath)
    RunSummary(tempPath)
}

RunSummary(inputPath) {
    global ContentSummaryDir, PythonExe, SummarizerScript, ContentLogsDir, LastContentSummaryText, LastContentSummaryHtml, LastContentSummaryError
    if !FileExist(PythonExe) {
        WriteLauncherLog("ERROR summarize Python venv executable missing: " PythonExe)
        MsgBox "Python venv executable not found:`n" PythonExe, "Content Summary", "Iconx"
        return
    }
    if !FileExist(SummarizerScript) {
        WriteLauncherLog("ERROR summarize script missing: " SummarizerScript)
        MsgBox "Summarizer script not found:`n" SummarizerScript, "Content Summary", "Iconx"
        return
    }

    DirCreate(ContentLogsDir)
    if FileExist(LastContentSummaryError) {
        FileDelete(LastContentSummaryError)
    }

    command := '"' PythonExe '" "' SummarizerScript '" "' inputPath '" --no-open'
    WriteLauncherLog("Summarize RunWait command=" command)
    exitCode := RunWait(command, ContentSummaryDir, "Hide")
    WriteLauncherLog("Summarize RunWait exitCode=" exitCode)
    if (exitCode != 0) {
        errorText := "Summarization failed."
        if FileExist(LastContentSummaryError) {
            loadedError := Trim(FileRead(LastContentSummaryError, "UTF-8"))
            if (loadedError != "") {
                errorText := loadedError
            }
        }
        WriteLauncherLog("ERROR summarize failed with non-zero exit.")
        MsgBox errorText, "Content Summary", "Iconx"
        return
    }

    if FileExist(LastContentSummaryHtml) {
        WriteLauncherLog("Summarize success. Opening HTML summary.")
        Run('"' LastContentSummaryHtml '"')
    } else if FileExist(LastContentSummaryText) {
        WriteLauncherLog("Summarize fallback: HTML missing, opening text summary.")
        Run('notepad.exe "' LastContentSummaryText '"')
    } else {
        WriteLauncherLog("ERROR summarize succeeded but last_content_summary missing.")
        MsgBox "Summarization completed, but no summary output file was found.", "Content Summary", "Iconx"
    }
}

WriteLauncherLog(message) {
    global LauncherLog
    timestamp := FormatTime(, "yyyy-MM-dd HH:mm:ss")
    FileAppend(timestamp " | " message "`n", LauncherLog, "UTF-8")
}

EnsureContentSummaryBridge() {
    global PythonExe, ContentBridgeScript, ContentSummaryDir
    if !FileExist(PythonExe) {
        WriteLauncherLog("Bridge skip: Python missing.")
        return
    }
    if !FileExist(ContentBridgeScript) {
        WriteLauncherLog("Bridge skip: bridge script missing.")
        return
    }
    command := '"' PythonExe '" "' ContentBridgeScript '" --host 127.0.0.1 --port 8765'
    Run(command, ContentSummaryDir, "Hide")
    WriteLauncherLog("Bridge launch requested.")
}
