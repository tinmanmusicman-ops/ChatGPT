console.log("HSST Control Tower UI Loaded (Phase B Skeleton)");

function callEndpoint(endpoint) {
    fetch(endpoint)
        .then(response => response.json())
        .then(data => console.log("Response:", data))
        .catch(err => console.error("Error:", err));
}

// JOB PIPELINE
document.getElementById("import-job").onclick = () =>
    callEndpoint("/tower/import-job");

document.getElementById("scam-check").onclick = () =>
    callEndpoint("/tower/scam-check");

document.getElementById("verify-company").onclick = () =>
    callEndpoint("/tower/verify-company");

document.getElementById("process-fax").onclick = () =>
    callEndpoint("/tower/fax-queue");

document.getElementById("facility-check").onclick = () =>
    callEndpoint("/tower/facility-check");

document.getElementById("json-config-btn").onclick = () =>
    callEndpoint("/tower/jason-configuration");

function updateLogPanel(text) {
    const logOutput = document.getElementById("log-output");
    if (!logOutput) {
        return;
    }

    const isAtBottom =
        logOutput.scrollHeight - logOutput.scrollTop <= logOutput.clientHeight + 5;

    const lines = text.split("\n");
    const html = lines
        .map(line => {
            let cls = "log-program";
            if (line.includes("STARTED")) {
                cls = "log-start";
            } else if (line.includes("FINISHED")) {
                cls = "log-end";
            } else if (/^\[stderr\]/i.test(line)) {
                cls = "log-stderr";
            } else if (/^\[INFO\]/.test(line) || /^INFO:/i.test(line)) {
                cls = "log-info";
            } else if (/ERR:|Failed|error|invalid_grant|Traceback|Exception/i.test(line)) {
                cls = "log-error";
            }

            const safeLine = line.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            return `<span class="${cls}">${safeLine}</span>`;
        })
        .join("<br>");

    logOutput.innerHTML = html;

    if (isAtBottom) {
        logOutput.scrollTop = logOutput.scrollHeight;
    }
}

function refreshLog() {
    fetch("/tower/read-log")
        .then(r => r.json())
        .then(data => updateLogPanel(data.text))
        .catch(err => console.error("Log refresh error:", err));
}

setInterval(refreshLog, 500);
refreshLog();

document.getElementById("clear-log-btn").onclick = () => {
    fetch("/tower/clear-log", { method: "POST" })
        .then(() => refreshLog())
        .catch(err => console.error("Log clear error:", err));
};

document.getElementById("copy-log-btn").onclick = () => {
    const logOutput = document.getElementById("log-output");
    if (!logOutput) {
        return;
    }

    const text = logOutput.textContent;

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(err =>
            console.error("Clipboard write failed:", err)
        );
        return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand("copy");
    } catch (err) {
        console.error("Fallback copy failed:", err);
    }
    document.body.removeChild(textarea);
};
