const OFFSCREEN_DOCUMENT_PATH = "offscreen.html";
const OFFSCREEN_JUSTIFICATION = "Copy job descriptions into the clipboard.";

async function ensureOffscreenDocument() {
  if (!chrome.offscreen?.createDocument) return false;
  const hasDoc = await chrome.offscreen.hasDocument();
  if (!hasDoc) {
    await chrome.offscreen.createDocument({
      url: OFFSCREEN_DOCUMENT_PATH,
      reasons: [chrome.offscreen.Reason.CLIPBOARD],
      justification: OFFSCREEN_JUSTIFICATION,
    });
  }
  return true;
}

function sendMessage(payload) {
  return new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendMessage(payload, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        resolve(response);
      });
    } catch (err) {
      reject(err);
    }
  });
}

async function handleCopyRequest(rawText) {
  const text = typeof rawText === "string" ? rawText : "";
  if (!text.trim()) {
    return { ok: false, error: "No job description to copy." };
  }
  if (!(await ensureOffscreenDocument())) {
    return { ok: false, error: "Clipboard access is unavailable.", code: "OFFSCREEN_UNAVAILABLE" };
  }

  const response = await sendMessage({ type: "offscreenCopy", text });
  if (!response?.ok) {
    return { ok: false, error: response?.error || "Copy failed." };
  }
  return { ok: true };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message?.type) return;

  if (message.type === "extractJD") {
    const tabId = message.tabId;
    if (!tabId) {
      sendResponse({ ok: false, error: "No active tab." });
      return;
    }

    chrome.scripting
      .executeScript({
        target: { tabId },
        func: () => {
          const textContent = (selector) => document.querySelector(selector)?.innerText?.trim() || "";

          const detectClosedMessage = () => {
            const candidates = [
              textContent(".jobs-universal-actions__text"),
              textContent(".artdeco-empty-state__message"),
              textContent(".jobsearch-JobInfoHeader-subtitle"),
            ];
            const bodyText = document.body?.innerText || "";
            if (bodyText) candidates.push(bodyText.trim());
            const normalizedCandidates = candidates.filter(Boolean);
            if (!normalizedCandidates.length) return "";

            const patterns = [
              /no longer accepting applications?/i,
              /no longer available/i,
              /job is no longer/i,
              /position is no longer/i,
              /role is no longer/i,
            ];

            for (const text of normalizedCandidates) {
              for (const pattern of patterns) {
                const match = text.match(pattern);
                if (match) {
                  return match[0];
                }
              }
            }
            return "";
          };

          let jd = "";

          if (location.hostname.includes("linkedin.com")) {
            jd =
              textContent(".show-more-less-html__markup") ||
              textContent(".jobs-description__content") ||
              "";
          }

          if (!jd && location.hostname.includes("indeed.com")) {
            jd =
              textContent("#jobDescriptionText") ||
              textContent(".jobsearch-jobDescriptionText") ||
              "";
          }

          return { jd, closedMessage: detectClosedMessage() };
        },
      })
      .then((results) => {
        const payload = results?.[0]?.result || {};
        const jd = typeof payload?.jd === "string" ? payload.jd : "";
        const closedMessage = typeof payload?.closedMessage === "string" ? payload.closedMessage.trim() : "";

        if (closedMessage && closedMessage.toLowerCase().includes("no longer")) {
          sendResponse({
            ok: true,
            status: "closed",
            message: closedMessage,
          });
          return;
        }

        sendResponse({ ok: true, jd });
      })
      .catch(() => {
        sendResponse({ ok: false, error: "Unable to read job description." });
      });

    return true;
  }

  if (message.type === "copyText") {
    handleCopyRequest(message.text)
      .then((result) => sendResponse(result))
      .catch((err) => {
        sendResponse({ ok: false, error: err?.message || "Copy failed." });
      });
    return true;
  }
});
