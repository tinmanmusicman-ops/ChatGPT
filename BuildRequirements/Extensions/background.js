
chrome.action.onClicked.addListener(async (tab) => {
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      const copy = async (t) => {
        try {
          await navigator.clipboard.writeText(t);
          alert("✔ Job Description copied");
        } catch {
          alert("❌ Copy failed");
        }
      };

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

      if (!jd) {
        alert("❌ No job description found");
        return;
      }

      copy(jd);
    }
  });
});
