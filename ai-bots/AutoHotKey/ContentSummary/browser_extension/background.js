const MENU_ID = "content-summary-selection";
const BRIDGE_URL = "http://127.0.0.1:8765/summarize";
const MAX_TEXT_CHARS = 15000;

function openErrorTab(message) {
  const text = `Content Summary failed.\n\n${message}\n\nStart bridge:\npython content_summary_bridge.py`;
  chrome.tabs.create({ url: `data:text/plain,${encodeURIComponent(text)}` });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ID,
      title: "Content Summary",
      contexts: ["all"],
    });
  });
});

async function getPageOrFocusedText(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: () => {
      try {
        const selected = (window.getSelection && String(window.getSelection())) || "";
        if (selected.trim()) {
          return selected;
        }

        const active = document.activeElement;
        if (active) {
          const tag = (active.tagName || "").toLowerCase();
          if (active.isContentEditable) {
            const text = active.innerText || active.textContent || "";
            if (text.trim()) {
              return text;
            }
          }
          if (tag === "textarea") {
            const text = active.value || "";
            if (text.trim()) {
              return text;
            }
          }
          if (tag === "input") {
            const t = (active.type || "").toLowerCase();
            if (["text", "search", "email", "url"].includes(t)) {
              const text = active.value || "";
              if (text.trim()) {
                return text;
              }
            }
          }
        }

        const bodyText = (document.body && document.body.innerText) || "";
        return bodyText || "";
      } catch (e) {
        return "";
      }
    },
  });

  if (!results || !results.length) {
    return "";
  }
  const text = (results[0].result || "").trim();
  return text;
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) {
    return;
  }
  let selectedText = (info.selectionText || "").trim();
  if (!selectedText && tab && typeof tab.id === "number") {
    try {
      selectedText = (await getPageOrFocusedText(tab.id)).trim();
    } catch (error) {
      openErrorTab(`Unable to read page content: ${error.message || String(error)}`);
      return;
    }
  }
  if (!selectedText) {
    openErrorTab("No text content found in the current page.");
    return;
  }
  if (selectedText.length > MAX_TEXT_CHARS) {
    selectedText = selectedText.slice(0, MAX_TEXT_CHARS);
  }

  try {
    const response = await fetch(BRIDGE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: selectedText }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    const targetUrl = `${data.url || "http://127.0.0.1:8765/last"}?ts=${Date.now()}`;
    chrome.tabs.create({ url: targetUrl });
  } catch (error) {
    openErrorTab(error && error.message ? error.message : String(error));
  }
});
