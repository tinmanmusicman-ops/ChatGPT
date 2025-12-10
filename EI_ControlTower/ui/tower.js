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

document.getElementById("enrich-company").onclick = () =>
    callEndpoint("/tower/enrich-company");

document.getElementById("push-ss").onclick = () =>
    callEndpoint("/tower/push-ss");


// FACILITY PANEL
document.getElementById("read-thermostat").onclick = () =>
    callEndpoint("/tower/read-thermostat");

document.getElementById("open-dashboard").onclick = () =>
    callEndpoint("/tower/open-dashboard");

document.getElementById("weather-sync").onclick = () =>
    callEndpoint("/tower/weather-sync");


// FAX ENGINE
document.getElementById("fax-queue").onclick = () =>
    callEndpoint("/tower/fax-queue");

document.getElementById("fax-retry").onclick = () =>
    callEndpoint("/tower/fax-retry");

document.getElementById("fax-log").onclick = () =>
    callEndpoint("/tower/fax-log");


// SECURITY
document.getElementById("security-notify").onclick = () =>
    callEndpoint("/tower/security-notify");

document.getElementById("security-log").onclick = () =>
    callEndpoint("/tower/security-log");


// CONFIG
document.getElementById("config-load").onclick = () =>
    callEndpoint("/tower/config-load");

document.getElementById("config-edit").onclick = () =>
    callEndpoint("/tower/config-edit");

document.getElementById("config-refresh").onclick = () =>
    callEndpoint("/tower/config-refresh");


// STINKY STATUS
document.getElementById("stinky-bath").onclick = () =>
    callEndpoint("/tower/stinky-bath");
