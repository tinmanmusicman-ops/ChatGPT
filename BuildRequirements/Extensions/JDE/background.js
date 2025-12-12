chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "extractJD") return;
  const tabId = message.tabId;
  if (!tabId) {
    sendResponse({ ok: false, error: "No active tab." });
    return;
  }

  chrome.scripting
    .executeScript({
      target: { tabId },
      func: () => {
        let jd = "";

        if (location.hostname.includes("linkedin.com")) {
          jd =
            document.querySelector(".show-more-less-html__markup")?.innerText?.trim() ||
            document.querySelector(".jobs-description__content")?.innerText?.trim() ||
            "";
        }

        if (!jd && location.hostname.includes("indeed.com")) {
          jd =
            document.querySelector("#jobDescriptionText")?.innerText?.trim() ||
            document.querySelector(".jobsearch-jobDescriptionText")?.innerText?.trim() ||
            "";
        }

        return jd;
      },
    })
    .then((results) => {
      const jd = results?.[0]?.result || "";
      sendResponse({ ok: true, jd });
    })
    .catch(() => {
      sendResponse({ ok: false, error: "Unable to read job description." });
    });

  return true;
});

