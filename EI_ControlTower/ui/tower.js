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
