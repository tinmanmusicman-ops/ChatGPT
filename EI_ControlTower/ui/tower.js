console.log("HSST Control Tower UI Loaded (Phase B Skeleton)");

function callEndpoint(endpoint) {
    fetch(endpoint)
        .then(response => response.json())
        .then(data => console.log("Response:", data))
        .catch(err => console.error("Error:", err));
}

// JOB PIPELINE
const ACTIVE_DURATION = 6000;

function activateButton(button) {
    button.classList.add("btn-active");

    if (button._activeTimer) {
        clearTimeout(button._activeTimer);
    }

    button._activeTimer = setTimeout(() => {
        button.classList.remove("btn-active");
        button._activeTimer = null;
    }, ACTIVE_DURATION);
}

const jobButtons = {
    "import-job": "/tower/import-job",
    "scam-check": "/tower/scam-check",
    "verify-company": "/tower/verify-company",
    "process-fax": "/tower/fax-queue",
    "facility-check": "/tower/facility-check",
    "targeted-resume": "/tower/targeted-resume",
    "yahoo-forwarder": "/tower/yahoo-forwarder"
};

Object.entries(jobButtons).forEach(([id, endpoint]) => {
    const button = document.getElementById(id);
    if (!button) {
        return;
    }

    button.addEventListener("click", () => {
        callEndpoint(endpoint);
        activateButton(button);
    });
});

document.getElementById("json-config-btn").onclick = () =>
    callEndpoint("/tower/jason-configuration");

const variantButton = document.getElementById("targeted-resume-variant-btn");
const variantSelect = document.getElementById("resume-variant-select");

if (variantButton && variantSelect) {
    variantButton.addEventListener("click", () => {
        const variant = variantSelect.value;
        callEndpoint(`/tower/targeted-resume/variant/${variant}`);
        activateButton(variantButton);
    });
}

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

            let rendered = line.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            let filesPayload = null;
            try {
                const parsed = JSON.parse(line.trim());
                if (parsed?.files && Array.isArray(parsed.files)) {
                    filesPayload = parsed.files;
                }
            } catch {
                // Not a JSON files payload
            }

            if (filesPayload) {
                const links = filesPayload
                    .map(file => `<a class="log-file-link" href="/view/${encodeURIComponent(file.name)}" target="_blank" rel="noreferrer">${file.label}</a>`)
                    .join(" | ");
                rendered = links;
            } else {
                const linkMatch = line.match(/^\[(PDF LINK|PDF COVER LETTER)\]\s+(.+)$/i);
                if (linkMatch) {
                    const tag = linkMatch[1].toUpperCase();
                    const url = linkMatch[2];
                    const label =
                        tag === "PDF COVER LETTER"
                            ? "View Tailored Cover Letter (PDF)"
                            : "View Tailored Resume (PDF)";
                    rendered = `<a class="log-file-link" href="${url}" target="_blank" rel="noreferrer">${label}</a>`;
                }
            }
            return `<span class="${cls}">${rendered}</span>`;
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

setInterval(checkBackendHealth, 10000);

async function checkBackendHealth() {
    const dot = document.getElementById("health-indicator");
    if (!dot) {
        return;
    }

    try {
        const response = await fetch("/health");
        dot.className = response.ok ? "health green" : "health yellow";
    } catch {
        dot.className = "health red";
    }
}

const flipUnits = {
    hours: {
        container: document.querySelector('[data-unit="hours"]'),
        value: null,
        timer: null
    },
    minutes: {
        container: document.querySelector('[data-unit="minutes"]'),
        value: null,
        timer: null
    },
    seconds: {
        container: document.querySelector('[data-unit="seconds"]'),
        value: null,
        timer: null
    }
};

let isFirstFlipUpdate = true;

function pad(value) {
    return value.toString().padStart(2, "0");
}

function setFlipValue(unitName, newValue, animate = true) {
    const unit = flipUnits[unitName];
    if (!unit?.container) {
        return;
    }

    const flip = unit.container.querySelector(".flip");
    const top = flip.querySelector(".top");
    const bottom = flip.querySelector(".bottom");

    if (unit.value === null || !animate) {
        top.textContent = newValue;
        bottom.textContent = newValue;
        unit.value = newValue;
        return;
    }

    if (unit.value === newValue) {
        return;
    }

    top.textContent = unit.value;
    bottom.textContent = newValue;

    flip.classList.add("animate");

    if (unit.timer) {
        clearTimeout(unit.timer);
    }

    unit.timer = setTimeout(() => {
        flip.classList.remove("animate");
        top.textContent = newValue;
        bottom.textContent = newValue;
        unit.timer = null;
    }, 700);

    unit.value = newValue;
}

function updateFlipClock() {
    const now = new Date();
    const timeParts = {
        hours: pad(now.getHours() % 12 || 12),
        minutes: pad(now.getMinutes()),
        seconds: pad(now.getSeconds())
    };

    const animate = !isFirstFlipUpdate;
    Object.entries(timeParts).forEach(([unit, value]) => {
        setFlipValue(unit, value, animate);
    });

    isFirstFlipUpdate = false;
}

function startFlipClock() {
    updateFlipClock();
    setInterval(updateFlipClock, 1000);
}

startFlipClock();
