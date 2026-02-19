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
global UpworkProjectDir := "C:\ChatGPT\ai-bots\UpWork"
global UpworkCaptureScript := UpworkProjectDir "\capture_visible_upwork_jobs.py"
global UpworkCaptureOutput := LogsDir "\upwork_capture_output.txt"
global UpworkEvalScript := UpworkProjectDir "\evaluate_upwork_capture.py"
global UpworkEvalProfile := UpworkProjectDir "\upwork_fit_profile.json"
global UpworkEvalOutput := LogsDir "\upwork_eval_output.txt"

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
^#u::CaptureVisibleUpworkJobs()
^#i::EvaluateLatestUpworkCapture()

CaptureAndEvaluate() {
    global TmpDir
    WriteLauncherLog("Hotkey flow started.")
    savedClipboard := ClipboardAll()
    A_Clipboard := ""
    ; Copy current selection only.
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
    ; Copy current selection only.
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
    } else {
        WriteLauncherLog("ERROR summarize succeeded but last_content_summary missing.")
        MsgBox "Summarization completed, but no summary output file was found.", "Content Summary", "Iconx"
    }
}

CaptureVisibleUpworkJobs() {
    global PythonExe, UpworkProjectDir, UpworkCaptureScript, UpworkCaptureOutput
    WriteLauncherLog("Upwork capture hotkey flow started.")
    ShowStatusTip("Upwork capture started (up to 25 pages).")

    if !FileExist(PythonExe) {
        WriteLauncherLog("ERROR Upwork capture Python executable missing: " PythonExe)
        MsgBox "FAIL-FAST: Python executable not found:`n" PythonExe, "Upwork Capture", "Iconx T8"
        return
    }
    if !DirExist(UpworkProjectDir) {
        WriteLauncherLog("ERROR Upwork capture project directory missing: " UpworkProjectDir)
        MsgBox "FAIL-FAST: Upwork project directory missing:`n" UpworkProjectDir, "Upwork Capture", "Iconx T8"
        return
    }
    if !FileExist(UpworkCaptureScript) {
        WriteLauncherLog("ERROR Upwork capture script missing: " UpworkCaptureScript)
        MsgBox "FAIL-FAST: Upwork capture script missing:`n" UpworkCaptureScript, "Upwork Capture", "Iconx T8"
        return
    }

    result := RunUpworkCaptureOnce()
    exitCode := result.exitCode
    outputText := result.outputText

    if (exitCode != 0) {
        WriteLauncherLog("ERROR Upwork capture failed: " outputText)
        MsgBox outputText, "Upwork Capture", "Iconx T10"
        return
    }

    WriteLauncherLog("Upwork capture success output=" outputText)
    A_Clipboard := outputText
    MsgBox outputText, "Upwork Capture", "Iconi T8"
}

EvaluateLatestUpworkCapture() {
    global PythonExe, UpworkProjectDir, UpworkEvalScript, UpworkEvalProfile
    WriteLauncherLog("Upwork evaluation hotkey flow started.")
    ShowStatusTip("Upwork evaluation started.")

    if !FileExist(PythonExe) {
        WriteLauncherLog("ERROR Upwork evaluation Python executable missing: " PythonExe)
        MsgBox "FAIL-FAST: Python executable not found:`n" PythonExe, "Upwork Evaluation", "Iconx T8"
        return
    }
    if !DirExist(UpworkProjectDir) {
        WriteLauncherLog("ERROR Upwork evaluation project directory missing: " UpworkProjectDir)
        MsgBox "FAIL-FAST: Upwork project directory missing:`n" UpworkProjectDir, "Upwork Evaluation", "Iconx T8"
        return
    }
    if !FileExist(UpworkEvalScript) {
        WriteLauncherLog("ERROR Upwork evaluation script missing: " UpworkEvalScript)
        MsgBox "FAIL-FAST: Upwork evaluation script missing:`n" UpworkEvalScript, "Upwork Evaluation", "Iconx T8"
        return
    }
    if !FileExist(UpworkEvalProfile) {
        WriteLauncherLog("ERROR Upwork evaluation profile missing: " UpworkEvalProfile)
        MsgBox "FAIL-FAST: Upwork evaluation profile missing:`n" UpworkEvalProfile, "Upwork Evaluation", "Iconx T8"
        return
    }

    result := RunUpworkEvaluationOnce()
    exitCode := result.exitCode
    outputText := result.outputText

    if (exitCode != 0) {
        WriteLauncherLog("ERROR Upwork evaluation failed: " outputText)
        MsgBox outputText, "Upwork Evaluation", "Iconx T10"
        return
    }

    WriteLauncherLog("Upwork evaluation success output=" outputText)
    A_Clipboard := outputText
    MsgBox outputText, "Upwork Evaluation", "Iconi T8"
}

RunUpworkCaptureOnce() {
    global PythonExe, UpworkProjectDir, UpworkCaptureScript, UpworkCaptureOutput
    if FileExist(UpworkCaptureOutput) {
        FileDelete(UpworkCaptureOutput)
    }
    command := '"' A_ComSpec '" /c "set NODE_NO_WARNINGS=1 && set UPWORK_MAX_PAGES=25 && "' PythonExe '" "' UpworkCaptureScript '" > "' UpworkCaptureOutput '" 2>&1"'
    WriteLauncherLog("Upwork RunWait command=" command)
    exitCode := RunWait(command, UpworkProjectDir, "Hide")
    WriteLauncherLog("Upwork RunWait exitCode=" exitCode)

    outputText := ""
    if FileExist(UpworkCaptureOutput) {
        outputText := Trim(FileRead(UpworkCaptureOutput, "UTF-8"))
    }
    if (outputText = "") {
        outputText := "FAIL-FAST: Upwork capture returned no output."
    }
    outputText := NormalizeUpworkCaptureOutput(outputText)
    return { exitCode: exitCode, outputText: outputText }
}

RunUpworkEvaluationOnce() {
    global PythonExe, UpworkProjectDir, UpworkEvalScript, UpworkEvalProfile, UpworkEvalOutput
    if FileExist(UpworkEvalOutput) {
        FileDelete(UpworkEvalOutput)
    }
    command := '"' A_ComSpec '" /c "set NODE_NO_WARNINGS=1 && "' PythonExe '" "' UpworkEvalScript '" --profile "' UpworkEvalProfile '" > "' UpworkEvalOutput '" 2>&1"'
    WriteLauncherLog("Upwork Eval RunWait command=" command)
    exitCode := RunWait(command, UpworkProjectDir, "Hide")
    WriteLauncherLog("Upwork Eval RunWait exitCode=" exitCode)

    outputText := ""
    if FileExist(UpworkEvalOutput) {
        outputText := Trim(FileRead(UpworkEvalOutput, "UTF-8"))
    }
    if (outputText = "") {
        outputText := "FAIL-FAST: Upwork evaluation returned no output."
    }
    outputText := NormalizeUpworkCaptureOutput(outputText)
    return { exitCode: exitCode, outputText: outputText }
}

NormalizeUpworkCaptureOutput(rawText) {
    lines := StrSplit(StrReplace(rawText, "`r", ""), "`n")
    kept := []
    for line in lines {
        clean := Trim(line)
        if (clean = "") {
            continue
        }
        if RegExMatch(clean, "i)^\(node:\d+\)\s+\[DEP\d+\]\s+DeprecationWarning:") {
            continue
        }
        if InStr(clean, "Use the WHATWG URL API instead.") {
            continue
        }
        if InStr(clean, "node --trace-deprecation") {
            continue
        }
        if InStr(clean, "DEP0169") {
            continue
        }
        if InStr(clean, "url.parse()") {
            continue
        }
        kept.Push(clean)
    }
    if (kept.Length = 0) {
        return "FAIL-FAST: Upwork capture returned no usable output."
    }
    out := ""
    for idx, item in kept {
        if (idx > 1) {
            out .= "`n"
        }
        out .= item
    }
    return out
}

WriteLauncherLog(message) {
    global LauncherLog
    timestamp := FormatTime(, "yyyy-MM-dd HH:mm:ss")
    FileAppend(timestamp " | " message "`n", LauncherLog, "UTF-8")
}

ShowStatusTip(message, durationMs := 2500) {
    ToolTip message
    SetTimer () => ToolTip(), -durationMs
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
