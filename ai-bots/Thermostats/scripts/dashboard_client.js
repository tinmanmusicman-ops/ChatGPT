(() => {
  //  Bootstrap: log once and capture the embedded JSON payload.
  console.log("Starting Javascript")
  const dataEl = document.getElementById("dashboard-data-inline");
  const parseInlineData = () => {
    if (!dataEl) {
      return null;
    }
    try {
      return JSON.parse(dataEl.textContent || "");
    } catch (warning) {
      console.warn("Failed to parse inline dashboard data; falling back to fetch.", warning);
      return null;
    }
  };

  let dashboardData = parseInlineData() || {};
  let currentArchiveSlug = dashboardData.generatedDateSlug || "";
  const scriptEl = document.getElementById("dashboard-client");
  const archivePathRaw = scriptEl?.dataset.archivePath || "chart hist";
  const archivePathHref = encodeURI(archivePathRaw);
  const buildArchiveJsonUrl = (slug) =>
    slug ? `${archivePathHref}/${slug}.json?v=${Date.now()}` : null;
  const logEl = document.getElementById("js-log");
  // Logging helper that writes to the console and the hidden dashboard log area.
  const logMessage = (message, level = "log") => {
    if (logEl) {
      logEl.style.display = "block";
      logEl.textContent += `${message}\n`;
      logEl.scrollTop = logEl.scrollHeight;
    }
    console[level](message);
  };

  // Embedded help chat (client-side; operator manual only).
  const helpChatToggle = document.getElementById("help-chat-toggle");
  const helpChatPanel = document.getElementById("help-chat-panel");
  const helpChatClose = document.getElementById("help-chat-close");
  const helpChatMessages = document.getElementById("help-chat-messages");
  const helpChatStatus = document.getElementById("help-chat-status");
  const helpChatForm = document.getElementById("help-chat-form");
  const helpChatInput = document.getElementById("help-chat-input");
  const helpChatClear = document.getElementById("help-chat-clear");
  const helpChatTagToggle = document.getElementById("help-chat-tag-toggle");
  const helpChatSend = document.getElementById("help-chat-send");
  let helpChatBusy = false;
  let helpChatMarkdownConfigured = false;
  const HELP_CHAT_NO_MATCH = "No documentation matches that term.";
  let helpChatManualText = null;
  let helpChatManualSections = null;
  let helpChatManualLoadPromise = null;
  const defaultHelpChatStatusText = helpChatStatus?.textContent || "";
  const clearHelpChatMessages = () => {
    if (helpChatMessages) {
      helpChatMessages.innerHTML = "";
    }
    if (helpChatStatus) {
      helpChatStatus.textContent = defaultHelpChatStatusText;
    }
    if (helpChatInput) {
      helpChatInput.value = "";
      helpChatInput.focus();
    }
    syncTagToggle();
  };

  const wrapTagLines = (container) => {
    if (!container || container.dataset.tagsWrapped === "1") {
      return;
    }
    Array.from(container.querySelectorAll("p")).forEach((p) => {
      const text = (p.textContent || "").trim();
      if (text.toLowerCase().startsWith("[tags:")) {
        const wrapper = document.createElement("div");
        wrapper.className = "tag-line";
        wrapper.textContent = text;
        p.replaceWith(wrapper);
      }
    });
    container.dataset.tagsWrapped = "1";
  };
  const syncTagToggle = () => {
    if (!helpChatPanel || !helpChatTagToggle) {
      return;
    }
    helpChatPanel.classList.toggle("hide-tags", helpChatTagToggle.checked);
  };
  // Remove tag-line text before the chatbot renders so the checkbox controls actual content flow.
  const filterTagLines = (text) => {
    if (!helpChatTagToggle?.checked) {
      return text;
    }
    return String(text || "")
      .split("\n")
      .filter((line) => !line.trim().toLowerCase().startsWith("[tags:"))
      .join("\n");
  };

  const enhanceHelpChatDocSections = (container) => {
    if (!container || container.dataset.docEnhanced === "1") {
      return;
    }
    const wrapHeadingSections = (
      root,
      headingTag,
      detailClass,
      summaryClass,
      bodyClass
    ) => {
      const headings = Array.from(root.querySelectorAll(headingTag));
      headings.forEach((heading) => {
        if (!heading.parentNode) {
          return;
        }
        if (heading.closest(`.${detailClass}`)) {
          return;
        }
        const titleText = String(heading.textContent || "").trim();
        if (!titleText) {
          return;
        }
        const details = document.createElement("details");
        details.className = detailClass;
        const summary = document.createElement("summary");
        summary.className = summaryClass;
        summary.textContent = titleText;
        const body = document.createElement("div");
        body.className = bodyClass;

        details.appendChild(summary);
        details.appendChild(body);
        heading.parentNode.insertBefore(details, heading);

        let node = heading.nextSibling;
        while (node) {
          const next = node.nextSibling;
          if (node.nodeType === 1 && node.tagName === headingTag) {
            break;
          }
          body.appendChild(node);
          node = next;
        }

        heading.remove();
      });
    };
    const headers = Array.from(container.querySelectorAll("h2"));
    if (!headers.length) {
      return;
    }

    headers.forEach((h2) => {
      if (!h2.parentNode) {
        return;
      }
      if (h2.closest(".doc-section")) {
        return;
      }
      const titleText = String(h2.textContent || "").trim();
      if (!titleText) {
        return;
      }

      const details = document.createElement("details");
      details.className = "doc-section";
      const summary = document.createElement("summary");
      summary.className = "doc-section-summary";
      summary.textContent = titleText;
      const body = document.createElement("div");
      body.className = "doc-section-body";

      details.appendChild(summary);
      details.appendChild(body);
      h2.parentNode.insertBefore(details, h2);

      let node = h2.nextSibling;
      while (node) {
        const next = node.nextSibling;
        if (node.nodeType === 1 && node.tagName === "H2") {
          break;
        }
        body.appendChild(node);
        node = next;
      }

      h2.remove();
    });

    wrapHeadingSections(
      container,
      "H3",
      "doc-subsection",
      "doc-subsection-summary",
      "doc-subsection-body"
    );

    container.dataset.docEnhanced = "1";
  };

  const tokenizeHelpQuery = (text) => {
    const raw = String(text || "")
      .toLowerCase()
      .match(/[a-z0-9][a-z0-9'-]+/g);
    return raw ? raw.map((t) => (t.length > 3 && t.endsWith("s") ? t.slice(0, -1) : t)) : [];
  };

  const parseHelpManualSections = (manualText) => {
    const text = String(manualText || "").replace(/\r\n?/g, "\n");
    const lines = text.split("\n");
    const sections = [];
    let current = null;

    const flush = () => {
      if (!current) return;
      const body = current.bodyLines.join("\n").trim();
      if (body) {
        sections.push({
          title: current.title,
          tags: (current.tags || []).map((t) => String(t).trim().toLowerCase()).filter(Boolean),
          body,
        });
      }
      current = null;
    };

    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      if (line.startsWith("## ")) {
        flush();
        current = { title: line.trim(), tags: [], bodyLines: [line.replace(/\s+$/, "")] };

        let j = i + 1;
        while (j < lines.length && !lines[j].trim()) {
          current.bodyLines.push(lines[j].replace(/\s+$/, ""));
          j += 1;
        }
        if (j < lines.length && lines[j].trim().toLowerCase().startsWith("[tags:")) {
          const tagLine = lines[j].trim();
          current.bodyLines.push(lines[j].replace(/\s+$/, ""));
          const payload = tagLine.replace(/^\[tags:\s*/i, "").replace(/\]\s*$/, "").trim();
          current.tags = payload
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean);
          i = j;
        }
        continue;
      }
      if (current) {
        current.bodyLines.push(line.replace(/\s+$/, ""));
      }
    }
    flush();
    return sections;
  };

  const loadHelpManual = async (forceReload = false) => {
    if (!forceReload && helpChatManualText && helpChatManualSections) {
      return;
    }
    if (helpChatManualLoadPromise) {
      await helpChatManualLoadPromise;
      return;
    }

    const inlineEl = document.getElementById("help-chat-manual-inline");
    if (!forceReload && inlineEl) {
      try {
        const payload = JSON.parse(inlineEl.textContent || "{}");
        const inlineText = typeof payload?.text === "string" ? payload.text : "";
        if (inlineText.trim()) {
          helpChatManualText = inlineText;
          helpChatManualSections = parseHelpManualSections(inlineText);
          return;
        }
      } catch (err) {
        // Fall back to fetching the manual URL.
      }
    }

    helpChatManualText = null;
    helpChatManualSections = null;

    const manualUrlRaw = helpChatPanel?.dataset?.manualUrl || "dashboard_operator_manual.md";
    const manualUrl = new URL(manualUrlRaw, window.location.href).toString();
    helpChatManualLoadPromise = (async () => {
      const resp = await fetch(manualUrl, { cache: "no-store" });
      if (!resp.ok) {
        throw new Error(`manual fetch failed (HTTP ${resp.status})`);
      }
      const text = await resp.text();
      helpChatManualText = text;
      helpChatManualSections = parseHelpManualSections(text);
    })();

    try {
      await helpChatManualLoadPromise;
    } finally {
      helpChatManualLoadPromise = null;
    }
  };

  const keywordLookupHelp = (query) => {
    const rawNormalized = String(query || "")
      .toLowerCase()
      .replace(/[^\w\s]/g, " ")
      .trim();
    const rawWords = rawNormalized.split(/\s+/).filter(Boolean);
    if (!rawWords.length) {
      return null;
    }
    if (!helpChatManualSections || !helpChatManualSections.length) {
      return null;
    }

    const tagVocabulary = new Set();
    for (const section of helpChatManualSections) {
      if (!Array.isArray(section.tags)) {
        continue;
      }
      section.tags.forEach((tag) => {
        const normalizedTag = String(tag || "").toLowerCase().trim();
        if (normalizedTag) {
          tagVocabulary.add(normalizedTag);
        }
      });
    }
    if (!tagVocabulary.size) {
      return null;
    }

    const levenshteinDistance = (a, b) => {
      const rows = a.length + 1;
      const cols = b.length + 1;
      const dist = Array.from({ length: rows }, () => Array(cols).fill(0));
      for (let i = 0; i < rows; i += 1) {
        dist[i][0] = i;
      }
      for (let j = 0; j < cols; j += 1) {
        dist[0][j] = j;
      }
      for (let i = 1; i < rows; i += 1) {
        for (let j = 1; j < cols; j += 1) {
          const cost = a[i - 1] === b[j - 1] ? 0 : 1;
          dist[i][j] = Math.min(
            dist[i - 1][j] + 1,
            dist[i][j - 1] + 1,
            dist[i - 1][j - 1] + cost
          );
        }
      }
      return dist[rows - 1][cols - 1];
    };

    const similarity = (a, b) => {
      const maxLength = Math.max(a.length, b.length);
      if (maxLength === 0) {
        return 1;
      }
      const distance = levenshteinDistance(a, b);
      return 1 - distance / maxLength;
    };

    const tagList = Array.from(tagVocabulary);
    const correctedWords = rawWords.map((word) => {
      if (tagVocabulary.has(word)) {
        return word;
      }
      let bestMatch = word;
      let bestScore = 0;
      for (const candidate of tagList) {
        const score = similarity(word, candidate);
        if (score > bestScore) {
          bestScore = score;
          bestMatch = candidate;
        }
      }
      return bestScore >= 0.8 ? bestMatch : word;
    });

    const correctedQuery = correctedWords.join(" ");
    const tokens = correctedQuery.split(/\s+/).filter(Boolean);
    if (!tokens.length) {
      return null;
    }

    const keywords = tokens.filter((token) => tagVocabulary.has(token));
    if (!keywords.length) {
      return null;
    }

    const matches = helpChatManualSections.filter((section) => {
      const tags = new Set(
        (section.tags || [])
          .map((t) => String(t || "").toLowerCase().trim())
          .filter(Boolean)
      );
      if (!tags.size) {
        return false;
      }
      if (keywords.length === 1) {
        return tags.has(keywords[0]);
      }
      return keywords.every((keyword) => tags.has(keyword));
    });

    if (!matches.length) {
      return null;
    }

    const picked = matches.slice(0, 3).map((section) => section.body).filter(Boolean);
    return picked.length ? picked.join("\n\n---\n\n") : null;
  };

  const configureHelpChatMarkdown = () => {
    if (helpChatMarkdownConfigured) {
      return;
    }
    if (typeof window.marked !== "undefined" && window.marked?.setOptions) {
      window.marked.setOptions({
        gfm: true,
        breaks: true,
        headerIds: false,
        mangle: false,
      });
    }
    helpChatMarkdownConfigured = true;
  };

  const setHelpChatMessageContent = (el, role, text) => {
    if (!el) {
      return;
    }
    const messageText = filterTagLines(String(text ?? ""));

    if (
      role === "assistant" &&
      typeof window.marked !== "undefined" &&
      typeof window.DOMPurify !== "undefined" &&
      window.marked?.parse &&
      window.DOMPurify?.sanitize
    ) {
      configureHelpChatMarkdown();
      const rendered = window.marked.parse(messageText);
      const sanitized = window.DOMPurify.sanitize(rendered, { USE_PROFILES: { html: true } });
      el.innerHTML = sanitized || "";
      el.querySelectorAll("a[href]").forEach((a) => {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      });
      enhanceHelpChatDocSections(el);
      wrapTagLines(el);
      if (!el.innerHTML) {
        el.textContent = messageText;
      }
      return;
    }

    el.textContent = messageText;
  };

  const appendHelpChatMessage = (role, text) => {
    if (!helpChatMessages) {
      return null;
    }
    const msg = document.createElement("div");
    msg.className = `help-msg ${role || ""}`.trim();
    setHelpChatMessageContent(msg, role, text);
    helpChatMessages.appendChild(msg);
    helpChatMessages.scrollTop = helpChatMessages.scrollHeight;
    return msg;
  };
  const setHelpChatOpen = (open) => {
    if (!helpChatPanel) {
      return;
    }
    helpChatPanel.classList.toggle("hidden", !open);
    if (open) {
      loadHelpManual(true).catch(() => {});
      syncTagToggle();
    }
    if (open && helpChatInput) {
      setTimeout(() => helpChatInput.focus(), 0);
    }
  };

  const chartHistory = document.getElementById("chart-history");
  const chartHistoryList = document.getElementById("chart-history-list");
  const chartHistoryToggle = document.getElementById("chart-history-toggle");
  const chartHistoryStatus = document.getElementById("chart-history-status");
  const transportHistoryStatus = document.getElementById("transport-history-status");
  const transportHistoryMonth = document.getElementById("transport-history-month");
  const transportHistoryDay = document.getElementById("transport-history-day");
  const transportStepMonth = document.getElementById("transport-step-month");
  const transportStepDay = document.getElementById("transport-step-day");
  const tvControls = document.getElementById("tv-controls");
  const tvControlsLabel = document.getElementById("tv-controls-label");
if (tvControlsLabel) {
  tvControlsLabel.textContent = "";
  tvControlsLabel.style.display = "none";
}

  const tvControlsSwap = document.getElementById("tv-controls-swap");
  const tvArchivePrevButton = document.getElementById("tv-archive-prev");
  const tvArchiveNextButton = document.getElementById("tv-archive-next");
  const chartStepPrevButton = document.getElementById("chart-step-prev");
  const chartStepNextButton = document.getElementById("chart-step-next");
  const chartStepValueEl = document.getElementById("chart-step-value");
  const tvHistorySlot = document.getElementById("tv-history-slot");
  const tvFileSelect = document.getElementById("tv-file-select");
  const tvHistoryStatus = document.getElementById("tv-history-status");
  const tvHistoryMonth = document.getElementById("tv-history-month");
  const tvHistoryDay = document.getElementById("tv-history-day");
  const tvHistoryHour = document.getElementById("tv-history-hour");
  const tvStepMonth = document.getElementById("tv-step-month");
  const tvStepDay = document.getElementById("tv-step-day");
  const tvStepHour = document.getElementById("tv-step-hour");
  const tvStepValue = document.getElementById("tv-step-value");
  const tvStepMonthValue = document.getElementById("tv-step-month-value");
  const tvStepDayValue = document.getElementById("tv-step-day-value");
  const tvStepTimeValue = document.getElementById("tv-step-time-value");
  const setTvStepReadout = (monthText, dayText, timeText) => {
    if (tvStepMonthValue) tvStepMonthValue.textContent = monthText || "";
    if (tvStepDayValue) tvStepDayValue.textContent = dayText || "";
    if (tvStepTimeValue) tvStepTimeValue.textContent = timeText || "";
    return Boolean(tvStepMonthValue || tvStepDayValue || tvStepTimeValue);
  };
  const isChartHistoryUiHidden = () =>
    document.body && document.body.classList.contains("hide-chart-history");
  const chartArea = document.getElementById("history");
  const autoplayToggle = document.getElementById("autoplay-toggle");
  const AUTOPLAY_IDLE_MS = 60_000;
  const AUTOPLAY_TARGET_MS = 30_000; // target duration for a full autoplay cycle
  const AUTOPLAY_MIN_STEP_MS = 400; // fastest we'll cycle points
  const AUTOPLAY_SEQUENCE = [
    { modes: ["setpoint"] },
    { modes: ["actual"] },
    { modes: ["outside"] },
    { modes: ["cooling"] },
    { modes: ["fan"] },
    { pauseMs: 10_000 }, // show hands/logo for 10s with chart hidden
    { modes: ["actual", "outside"] },           // options 2 + 3
    { modes: ["actual", "outside", "cooling"] }, // then add option 4
  ];
  let autoplayEnabled = true;
  let autoplayTimer = null;
  let autoplayIdleTimer = null;
  let autoplayIndex = 0;
  let autoplaySegmentIndex = 0;
  let autoplayStepMs = 3_000;
  let savedModesBeforeAutoplay = null;
  let chartHistoryMonthPicker = null;
  let chartHistoryMonthList = null;
  let chartHistoryListsRow = null;
  let chartHistoryListColumn = null;
  let chartHistoryHoverBound = false;
  let chartHistoryListHoverBound = false;
  let chartPointPickerBound = false;
  let historyExpanded = false;
  const setHistoryExpanded = (open) => {
    historyExpanded = Boolean(open);
    if (chartHistory) {
      chartHistory.classList.toggle("expanded", historyExpanded);
    }
    if (chartHistoryList) {
      chartHistoryList.classList.toggle("hidden", !historyExpanded);
    }
    if (chartHistoryToggle) {
      chartHistoryToggle.classList.toggle("history-visible", historyExpanded);
    }
    if (chartHistoryListColumn) {
      chartHistoryListColumn.classList.toggle("expanded", historyExpanded);
    }
    if (chartHistoryListsRow) {
      chartHistoryListsRow.classList.toggle("expanded", historyExpanded);
    }
  };
  const showHistoryFiles = () => setHistoryExpanded(true);
  const hideHistoryFiles = () => setHistoryExpanded(false);
  let currentMonthKey =
    (dashboardData.generatedDateSlug || "").slice(0, 7) || "";
  // Reference chart controls, canvas, and state flags used throughout the script.
  const archiveLabelMap = new Map();
  const chartControlButtons = document.querySelectorAll(".chart-control");
  const canvas = document.getElementById("history-chart");
  const ctx = canvas ? canvas.getContext("2d") : null;
  const toggleHistoryBtn = document.getElementById("toggle-history");
  const handsLogoTop = document.querySelector(".hands-logo-top");
  const timestampDisplay = document.getElementById("dashboard-timestamp");
  const usageSlotCanvas = document.getElementById("usage-slot-chart");
  const usageSlotCtx = usageSlotCanvas ? usageSlotCanvas.getContext("2d") : null;
  const usageSlotCanvasSlot = document.getElementById("usage-slot-canvas-slot");
  const historyChartCanvasSlot = document.getElementById("history-chart-canvas-slot");
  let chart = null;
  let usageSlotChart = null;
  let cardsInitialized = false;
  let hoverPointIndex = null;
  let pinnedPointIndex = null;
  let suppressHoverUntilMouseLeave = false;
  const suppressHoverUntilLeave = () => {
    suppressHoverUntilMouseLeave = true;
  };
  let selectionIndicatorEl = null;
  let clearPinButtonEl = null;
  let hourPickerEl = null;
  let prevDayButtonEl = null;
  let nextDayButtonEl = null;
  let usageSlotBound = false;
  let chartSwapBound = false;
  let chartsSwapped = false;
  const usageSlotEl = document.getElementById("usage-slot");
  const usageHeaderEl = document.querySelector("#usage-slot .usage-header");
  const usagePipEl = document.getElementById("usage-pip");
  let usageRangeKey = "year"; // 7d | month | year

  let tvStepMode = (() => {
    if (tvStepMonth?.checked) return "month";
    if (tvStepHour?.checked) return "hour";
    return "day";
  })(); // month | day | hour

  let transportStepMode = (() => {
    if (transportStepMonth?.checked) return "month";
    return "day";
  })(); // month | day

  // When stepping across the first/last point, we can load the adjacent day and
  // re-pin to the opposite edge to create a continuous "scrolling" feel.
  let pendingPinnedIndexAfterArchiveLoad = null;

  const DECK_SPIN_DEFAULT_MS = 4_000;
  const DECK_SPIN_FAST_MS = 1_000; // forward one day
  const DECK_REWIND_MIN_MS = 700; // quick rewind effect for small jumps
  const DECK_REWIND_BASE_MONTH_MS = 1_500; // 30 days back
  const DECK_REWIND_PER_MONTH_MS = 500; // add per additional 30 days
  const DECK_REWIND_MAX_MS = 5_000; // cap rewind duration
  const DECK_PLAY_AFTER_MOVE_MS = 1_000; // brief "play" after a long move
  let deckSpinTimerId = null;
  let pendingArchiveLoadTimerId = null;
  let pendingArchivePhaseTimerId = null;
  let pendingArchiveSlug = null;
  let pendingSelectedArchiveSlug = null;
  const triggerDeckSpin = (
    durationMs = DECK_SPIN_DEFAULT_MS,
    { direction = "normal", spinSpeedSeconds = "1.35s" } = {}
  ) => {
    const decks = [
      document.getElementById("transport-deck"),
      document.getElementById("tv-transport-deck"),
    ].filter(Boolean);
    if (!decks.length) {
      return;
    }
    decks.forEach((deck) => {
      deck.style.setProperty("--deck-spin-direction", direction);
      deck.style.setProperty("--deck-spin-duration", spinSpeedSeconds);
      deck.classList.add("playing");
    });
    if (deckSpinTimerId) {
      clearTimeout(deckSpinTimerId);
    }
    deckSpinTimerId = setTimeout(() => {
      decks.forEach((deck) => deck.classList.remove("playing"));
      deckSpinTimerId = null;
    }, durationMs);
  };

  const computeTapeMoveDurationMs = (absDays) => {
    const days = Math.max(0, Math.floor(Number(absDays || 0)));
    const months = Math.floor(days / 30);
    if (months <= 0) {
      return DECK_REWIND_MIN_MS;
    }
    return Math.min(
      DECK_REWIND_MAX_MS,
      DECK_REWIND_BASE_MONTH_MS + DECK_REWIND_PER_MONTH_MS * Math.max(0, months - 1)
    );
  };

  const computeArchiveDeltaDays = (fromSlug, toSlug) => {
    const fromDate = parseSlugDateUtc(fromSlug);
    const toDate = parseSlugDateUtc(toSlug);
    if (!fromDate || !toDate) {
      return null;
    }
    const msPerDay = 24 * 60 * 60 * 1000;
    return Math.round((toDate - fromDate) / msPerDay);
  };

  const scheduleArchiveLoadAfterSpin = (
    slug,
    pinIndexAfterLoad = null,
    durationMs = DECK_SPIN_DEFAULT_MS,
    spinOptions = null
  ) => {
    if (!slug) {
      return false;
    }
    pendingSelectedArchiveSlug = null;
    pendingArchiveSlug = slug;
    if (pendingArchiveLoadTimerId) {
      clearTimeout(pendingArchiveLoadTimerId);
      pendingArchiveLoadTimerId = null;
    }
    if (pendingArchivePhaseTimerId) {
      clearTimeout(pendingArchivePhaseTimerId);
      pendingArchivePhaseTimerId = null;
    }
    triggerDeckSpin(durationMs, spinOptions || undefined);
    pendingArchiveLoadTimerId = setTimeout(() => {
      pendingArchiveLoadTimerId = null;
      pendingArchiveSlug = null;
      if (pinIndexAfterLoad !== null && pinIndexAfterLoad !== undefined) {
        pendingPinnedIndexAfterArchiveLoad = Number.isFinite(Number(pinIndexAfterLoad))
          ? Math.floor(Number(pinIndexAfterLoad))
          : null;
      }
      updateHistoryStatus(slug);
      currentArchiveSlug = slug;
      loadDashboardData(slug);
    }, durationMs);
    return true;
  };

  const scheduleArchiveLoadAfterFastForwardPlay = (slug, pinIndexAfterLoad = null) => {
    if (!slug) {
      return false;
    }
    const fromSlug = pendingArchiveSlug || currentArchiveSlug || dashboardData.generatedDateSlug || "";
    const deltaDays = computeArchiveDeltaDays(fromSlug, slug);
    const absDays = deltaDays === null ? 0 : Math.abs(deltaDays);
    const fastForwardMs = computeTapeMoveDurationMs(absDays);

    pendingSelectedArchiveSlug = null;
    pendingArchiveSlug = slug;
    if (pendingArchiveLoadTimerId) {
      clearTimeout(pendingArchiveLoadTimerId);
      pendingArchiveLoadTimerId = null;
    }
    if (pendingArchivePhaseTimerId) {
      clearTimeout(pendingArchivePhaseTimerId);
      pendingArchivePhaseTimerId = null;
    }
    // Fast-forward (forward), then briefly play forward, then load.
    triggerDeckSpin(fastForwardMs, { direction: "normal", spinSpeedSeconds: "0.35s" });
    pendingArchivePhaseTimerId = setTimeout(() => {
      pendingArchivePhaseTimerId = null;
      triggerDeckSpin(DECK_PLAY_AFTER_MOVE_MS, { direction: "normal", spinSpeedSeconds: "1.35s" });
    }, fastForwardMs);
    pendingArchiveLoadTimerId = setTimeout(() => {
      pendingArchiveLoadTimerId = null;
      pendingArchiveSlug = null;
      if (pinIndexAfterLoad !== null && pinIndexAfterLoad !== undefined) {
        pendingPinnedIndexAfterArchiveLoad = Number.isFinite(Number(pinIndexAfterLoad))
          ? Math.floor(Number(pinIndexAfterLoad))
          : null;
      }
      updateHistoryStatus(slug);
      currentArchiveSlug = slug;
      loadDashboardData(slug);
    }, fastForwardMs + DECK_PLAY_AFTER_MOVE_MS);
    return true;
  };

  const scheduleArchiveLoadAfterRewindPlay = (slug, pinIndexAfterLoad = null) => {
    if (!slug) {
      return false;
    }
    const fromSlug = pendingArchiveSlug || currentArchiveSlug || dashboardData.generatedDateSlug || "";
    const deltaDays = computeArchiveDeltaDays(fromSlug, slug);
    const absDays = deltaDays === null ? 0 : Math.abs(deltaDays);
    const rewindMs = computeTapeMoveDurationMs(absDays);
    pendingSelectedArchiveSlug = null;
    pendingArchiveSlug = slug;
    if (pendingArchiveLoadTimerId) {
      clearTimeout(pendingArchiveLoadTimerId);
      pendingArchiveLoadTimerId = null;
    }
    if (pendingArchivePhaseTimerId) {
      clearTimeout(pendingArchivePhaseTimerId);
      pendingArchivePhaseTimerId = null;
    }
    // Rewind fast (reverse), then briefly play forward, then load.
    triggerDeckSpin(rewindMs, { direction: "reverse", spinSpeedSeconds: "0.35s" });
    pendingArchivePhaseTimerId = setTimeout(() => {
      pendingArchivePhaseTimerId = null;
      triggerDeckSpin(DECK_PLAY_AFTER_MOVE_MS, { direction: "normal", spinSpeedSeconds: "1.35s" });
    }, rewindMs);
    pendingArchiveLoadTimerId = setTimeout(() => {
      pendingArchiveLoadTimerId = null;
      pendingArchiveSlug = null;
      if (pinIndexAfterLoad !== null && pinIndexAfterLoad !== undefined) {
        pendingPinnedIndexAfterArchiveLoad = Number.isFinite(Number(pinIndexAfterLoad))
          ? Math.floor(Number(pinIndexAfterLoad))
          : null;
      }
      updateHistoryStatus(slug);
      currentArchiveSlug = slug;
      loadDashboardData(slug);
    }, rewindMs + DECK_PLAY_AFTER_MOVE_MS);
    return true;
  };

  const scheduleArchiveLoadWithTapeRules = (slug, pinIndexAfterLoad = null) => {
    if (!slug) {
      return false;
    }
    const fromSlug = pendingArchiveSlug || currentArchiveSlug || dashboardData.generatedDateSlug || "";
    const deltaDays = computeArchiveDeltaDays(fromSlug, slug);
    if (deltaDays === null) {
      return scheduleArchiveLoadAfterSpin(slug, pinIndexAfterLoad, DECK_SPIN_DEFAULT_MS);
    }
    if (deltaDays === 1) {
      // Special-case: "next day" is quick.
      return scheduleArchiveLoadAfterSpin(slug, pinIndexAfterLoad, DECK_SPIN_FAST_MS);
    }
    if (deltaDays > 1) {
      return scheduleArchiveLoadAfterFastForwardPlay(slug, pinIndexAfterLoad);
    }
    // deltaDays <= 0
    return scheduleArchiveLoadAfterRewindPlay(slug, pinIndexAfterLoad);
  };

  const HOLD_REPEAT_DELAY_MS = 1000;
  const HOLD_REPEAT_INTERVAL_MS = 160;
  const holdRepeatSuppressClickUntil = new WeakMap();
  const holdRepeatTimers = new WeakMap(); // el -> { timeoutId, intervalId }

  const clearHoldRepeatTimers = (el) => {
    const entry = holdRepeatTimers.get(el);
    if (!entry) {
      return;
    }
    if (entry.timeoutId) {
      clearTimeout(entry.timeoutId);
    }
    if (entry.intervalId) {
      clearInterval(entry.intervalId);
    }
    holdRepeatTimers.delete(el);
  };

  const bindHoldRepeat = (el, action) => {
    if (!el || typeof action !== "function" || el.dataset.boundHoldRepeat === "1") {
      return;
    }
    el.dataset.boundHoldRepeat = "1";

    const stop = () => clearHoldRepeatTimers(el);

    const start = (event) => {
      // Only primary button for mouse; always allow touch/pen.
      if (event && event.type === "pointerdown") {
        const btn = Number(event.button);
        if (Number.isFinite(btn) && btn !== 0) {
          return;
        }
      }
      stop();
      // Fire immediately, then begin repeating after a delay.
      action();
      holdRepeatSuppressClickUntil.set(el, Date.now() + 500);
      const timeoutId = setTimeout(() => {
        const intervalId = setInterval(() => action(), HOLD_REPEAT_INTERVAL_MS);
        const current = holdRepeatTimers.get(el) || {};
        holdRepeatTimers.set(el, { ...current, intervalId });
      }, HOLD_REPEAT_DELAY_MS);
      holdRepeatTimers.set(el, { timeoutId, intervalId: null });
    };

    el.addEventListener("pointerdown", (event) => {
      try {
        el.setPointerCapture?.(event.pointerId);
      } catch (err) {
        // ignore
      }
      start(event);
    });
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointercancel", stop);
    el.addEventListener("pointerleave", stop);
    window.addEventListener("blur", stop);

    // Keyboard hold on focused button (Space/Enter).
    el.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      start(event);
    });
    el.addEventListener("keyup", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      stop();
    });
  };

  const setTvStepMode = (mode) => {
    const normalized = mode === "month" || mode === "hour" ? mode : "day";
    tvStepMode = normalized;
    if (tvStepMonth) tvStepMonth.checked = normalized === "month";
    if (tvStepDay) tvStepDay.checked = normalized === "day";
    if (tvStepHour) tvStepHour.checked = normalized === "hour";
    syncArchiveNavButtons();
    // Refresh the displayed value between the arrows.
    updateHistoryStatus(currentArchiveSlug || dashboardData.generatedDateSlug || "");
    updateTimestampFromSelection();
  };

  const setTransportStepMode = (mode) => {
    const normalized = mode === "month" ? "month" : "day";
    transportStepMode = normalized;
    if (transportStepMonth) transportStepMonth.checked = normalized === "month";
    if (transportStepDay) transportStepDay.checked = normalized === "day";
    syncArchiveNavButtons();
    updateHistoryStatus(currentArchiveSlug || dashboardData.generatedDateSlug || "");
  };

  const STORAGE_KEY = "thermostatDashboard.ui.v1";
  let savedUiState = null;
  const updateSwapLabels = () => {
    const mainLabel = chartsSwapped ? "Usage Chart" : "History Chart";
    if (tvControlsLabel) {
      tvControlsLabel.textContent = `Click here to swap chart (now showing: ${mainLabel})`;
    }
  };

  const getDashboardData = () => dashboardData || {};
  const getDashboardValue = (key, fallback) => getDashboardData()[key] || fallback;
  // Quick accessor helpers so downstream logic can stay declarative.
  const getChartLabels = () => getDashboardValue("chartLabels", []);
  const getSetpointSeries = () => getDashboardValue("setpoint", []);
  const getActualSeries = () => getDashboardValue("actual", []);
  const getOutsideSeries = () => getDashboardValue("outside", []);
  const getFanSeries = () => getDashboardValue("fan", []);
  const getCoolingSeries = () => getDashboardValue("cooling", []);
  const getOutsideFlags = () => getDashboardValue("outsideFlags", []);
  const getOutsideFlagDayChars = () => getDashboardValue("outsideFlagDayChars", []);
  const getSetpointLabel = () => getDashboardData().setpointLabel || "Target Temperature";
  const getActualLabel = () => getDashboardData().actualLabel || "Building Temperature";
  const getOutsideLabel = () => getDashboardData().outsideLabel || "Outside Temp";
  const getCoolingLabel = () => getDashboardData().coolingLabel || "Cooling Status";
  const getClimateSettingSeries = () => getDashboardValue("climateSetting", []);
  const getTypeSeries = () => getDashboardValue("typeSeries", []);
  const getStudioSeries = () => getDashboardValue("studioSeries", []);
  const getRequestExpiresSeries = () => getDashboardValue("requestExpiresLocalSeries", []);

  const usageSummaryCache = new Map(); // slug -> { runtimeMinutes }

  const parseSlugDateUtc = (slug) => {
    if (!slug || typeof slug !== "string") {
      return null;
    }
    const m = slug.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) {
      return null;
    }
    const y = Number(m[1]);
    const mo = Number(m[2]) - 1;
    const d = Number(m[3]);
    if (!Number.isFinite(y) || !Number.isFinite(mo) || !Number.isFinite(d)) {
      return null;
    }
    return new Date(Date.UTC(y, mo, d, 0, 0, 0));
  };

  const formatSlugShort = (slug) => {
    const d = parseSlugDateUtc(slug);
    if (!d) {
      return String(slug || "");
    }
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    return `${mm}/${dd}`;
  };

  const MONTH_LABELS_SHORT = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];

  const getAvailableArchiveSlugs = () => {
    const dates = getArchiveDates();
    if (!Array.isArray(dates)) {
      return [];
    }
    return dates.map((d) => d?.slug).filter(Boolean);
  };

  const getSortedArchiveSlugs = () => getAvailableArchiveSlugs().slice().sort();

  const getCurrentArchiveIndex = (sortedSlugs) => {
    const slugs = Array.isArray(sortedSlugs) ? sortedSlugs : getSortedArchiveSlugs();
    if (!slugs.length) {
      return -1;
    }
    const current = pendingArchiveSlug || currentArchiveSlug || dashboardData.generatedDateSlug || "";
    const idx = current ? slugs.indexOf(current) : -1;
    return idx >= 0 ? idx : slugs.length - 1;
  };

  const syncArchiveNavButtons = () => {
    const hasInlineNav = Boolean(prevDayButtonEl && nextDayButtonEl);
    const hasTvNav = Boolean(tvArchivePrevButton && tvArchiveNextButton);
    if (!hasInlineNav && !hasTvNav) {
      return;
    }
    const slugs = getSortedArchiveSlugs();
    const idx = getCurrentArchiveIndex(slugs);
    const baseHasPrevDay = idx > 0;
    const baseHasNextDay = idx >= 0 && idx < slugs.length - 1;

    const computeMonthAvailability = (slug) => {
      const currentDate = parseSlugDateUtc(slug);
      if (!currentDate) {
        return { hasPrev: baseHasPrevDay, hasNext: baseHasNextDay };
      }
      const currentMonthIndex = currentDate.getUTCFullYear() * 12 + currentDate.getUTCMonth();
      const availableMonthIndexes = new Set();
      getAvailableArchiveSlugs().forEach((availableSlug) => {
        const d = parseSlugDateUtc(availableSlug);
        if (!d) return;
        availableMonthIndexes.add(d.getUTCFullYear() * 12 + d.getUTCMonth());
      });
      return {
        hasPrev: availableMonthIndexes.has(currentMonthIndex - 1),
        hasNext: availableMonthIndexes.has(currentMonthIndex + 1),
      };
    };

    const tvAvailability = (() => {
      if (!hasTvNav) {
        return { hasPrev: baseHasPrevDay, hasNext: baseHasNextDay };
      }
      if (tvStepMode === "hour") {
        const labels = getChartLabels();
        const length = Array.isArray(labels) ? labels.length : 0;
        const currentPoint =
          clampIndex(pinnedPointIndex, length) ?? clampIndex(hoverPointIndex, length);
        if (currentPoint === null || length <= 0) {
          return { hasPrev: baseHasPrevDay, hasNext: baseHasNextDay };
        }
        return {
          hasPrev: currentPoint > 0 || (currentPoint <= 0 && baseHasPrevDay),
          hasNext: currentPoint < length - 1 || (currentPoint >= length - 1 && baseHasNextDay),
        };
      }
      if (tvStepMode === "month") {
        const currentSlug = currentArchiveSlug || dashboardData.generatedDateSlug || "";
        return computeMonthAvailability(currentSlug);
      }
      return { hasPrev: baseHasPrevDay, hasNext: baseHasNextDay };
    })();

    const inlineAvailability = (() => {
      if (!hasInlineNav) {
        return { hasPrev: baseHasPrevDay, hasNext: baseHasNextDay };
      }
      const stepModeForInline = transportStepMode || "day";
      if (stepModeForInline === "month") {
        const currentSlug = currentArchiveSlug || dashboardData.generatedDateSlug || "";
        return computeMonthAvailability(currentSlug);
      }
      return { hasPrev: baseHasPrevDay, hasNext: baseHasNextDay };
    })();

    if (hasInlineNav) {
      prevDayButtonEl.disabled = !inlineAvailability.hasPrev;
      nextDayButtonEl.disabled = !inlineAvailability.hasNext;
      prevDayButtonEl.style.opacity = inlineAvailability.hasPrev ? "1" : "0.5";
      nextDayButtonEl.style.opacity = inlineAvailability.hasNext ? "1" : "0.5";
    }
    if (hasTvNav) {
      tvArchivePrevButton.disabled = !tvAvailability.hasPrev;
      tvArchiveNextButton.disabled = !tvAvailability.hasNext;
      tvArchivePrevButton.style.opacity = tvAvailability.hasPrev ? "1" : "0.5";
      tvArchiveNextButton.style.opacity = tvAvailability.hasNext ? "1" : "0.5";
    }
  };

  const navigateArchiveByDays = (delta) => {
    const slugs = getSortedArchiveSlugs();
    const idx = getCurrentArchiveIndex(slugs);
    if (idx < 0) {
      return;
    }
    const nextIdx = idx + Number(delta || 0);
    if (nextIdx < 0 || nextIdx >= slugs.length) {
      return;
    }
    const slug = slugs[nextIdx];
    if (!slug) {
      return;
    }
    const normalizedDelta = Number(delta || 0);
    if (normalizedDelta < 0) {
      scheduleArchiveLoadAfterRewindPlay(slug);
      return;
    }
    // Next day is always quick (1s).
    scheduleArchiveLoadAfterSpin(slug, null, DECK_SPIN_FAST_MS);
  };

  const navigateArchiveByDaysWithPinnedIndex = (delta, pinIndexAfterLoad) => {
    const slugs = getSortedArchiveSlugs();
    const idx = getCurrentArchiveIndex(slugs);
    if (idx < 0) {
      return false;
    }
    const nextIdx = idx + Number(delta || 0);
    if (nextIdx < 0 || nextIdx >= slugs.length) {
      return false;
    }
    const slug = slugs[nextIdx];
    if (!slug) {
      return false;
    }
    const normalizedDelta = Number(delta || 0);
    if (normalizedDelta < 0) {
      return scheduleArchiveLoadAfterRewindPlay(slug, pinIndexAfterLoad);
    }
    // Next day is always quick (1s).
    return scheduleArchiveLoadAfterSpin(slug, pinIndexAfterLoad, DECK_SPIN_FAST_MS);
  };

  const navigateArchiveByMonths = (delta) => {
    const current = pendingArchiveSlug || currentArchiveSlug || dashboardData.generatedDateSlug || "";
    const currentDate = parseSlugDateUtc(current);
    if (!currentDate) {
      return;
    }
    const months = Number(delta || 0);
    if (!Number.isFinite(months) || months === 0) {
      return;
    }

    const desiredMonthIndex =
      currentDate.getUTCFullYear() * 12 + currentDate.getUTCMonth() + months;

    const candidates = [];
    getAvailableArchiveSlugs().forEach((slug) => {
      const d = parseSlugDateUtc(slug);
      if (!d) return;
      const idx = d.getUTCFullYear() * 12 + d.getUTCMonth();
      if (idx === desiredMonthIndex) {
        candidates.push(slug);
      }
    });

    if (!candidates.length) {
      return;
    }
    candidates.sort();
    const slug = candidates[candidates.length - 1]; // latest day in that month
    scheduleArchiveLoadWithTapeRules(slug);
  };

  let tvChartHistoryHomeParent = null;
  let tvChartHistoryHomeNextSibling = null;
  const mountTvHistory = () => {
    if (!tvHistorySlot || !chartHistory) {
      return;
    }
    if (tvHistorySlot.contains(chartHistory)) {
      return;
    }
    tvChartHistoryHomeParent = chartHistory.parentElement;
    tvChartHistoryHomeNextSibling = chartHistory.nextSibling;
    tvHistorySlot.appendChild(chartHistory);
  };

  const unmountTvHistory = () => {
    if (!chartHistory || !tvChartHistoryHomeParent) {
      return;
    }
    const parent = tvChartHistoryHomeParent;
    const next = tvChartHistoryHomeNextSibling;
    if (next && next.parentNode === parent) {
      parent.insertBefore(chartHistory, next);
    } else {
      parent.appendChild(chartHistory);
    }
    tvChartHistoryHomeParent = null;
    tvChartHistoryHomeNextSibling = null;
  };

  let tvHistoryToggleBound = false;
  const bindTvHistoryToggle = () => {
    if (!tvFileSelect || tvHistoryToggleBound) {
      return;
    }
    tvHistoryToggleBound = true;
    tvFileSelect.addEventListener("click", (event) => {
      const target = event.target;
      if (target && target.closest && target.closest("button,select,a,input,textarea")) {
        return;
      }
      event.preventDefault();
      toggleHistoryList();
    });
  };

  let archiveKeyHandlerBound = false;
  const isEditableTarget = (target) => {
    const el = target;
    if (!el) return false;
    if (el.isContentEditable) return true;
    const tag = String(el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select";
  };
  const bindArchiveKeyboardShortcuts = () => {
    if (archiveKeyHandlerBound) {
      return;
    }
    archiveKeyHandlerBound = true;
    window.addEventListener("keydown", (event) => {
      if (event.defaultPrevented) {
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey) {
        return;
      }
      if (isEditableTarget(event.target)) {
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        if (tvModeActive) {
          showTvControlsHint(6000);
        }
        if (tvStepMode === "hour") {
          stepPinnedPoint(-1);
        } else if (tvStepMode === "month") {
          navigateArchiveByMonths(-1);
        } else {
          navigateArchiveByDays(-1);
        }
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        if (tvModeActive) {
          showTvControlsHint(6000);
        }
        if (tvStepMode === "hour") {
          stepPinnedPoint(1);
        } else if (tvStepMode === "month") {
          navigateArchiveByMonths(1);
        } else {
          navigateArchiveByDays(1);
        }
      }
    });
  };

  const buildUsageRangeSlugs = (rangeKey) => {
    const endSlug = currentArchiveSlug || dashboardData.generatedDateSlug || "";
    const end = parseSlugDateUtc(endSlug) || new Date();
    const available = new Set(getAvailableArchiveSlugs());
    const slugs = [];

    if (rangeKey === "year") {
      const targetYear = end.getUTCFullYear();
      getAvailableArchiveSlugs().forEach((slug) => {
        const d = parseSlugDateUtc(slug);
        if (!d) {
          return;
        }
        if (d.getUTCFullYear() === targetYear) {
          slugs.push(slug);
        }
      });
      return slugs.sort();
    }

    if (rangeKey === "month") {
      const targetMonth = end.getUTCMonth();
      const targetYear = end.getUTCFullYear();
      getAvailableArchiveSlugs().forEach((slug) => {
        const d = parseSlugDateUtc(slug);
        if (!d) {
          return;
        }
        if (d.getUTCFullYear() === targetYear && d.getUTCMonth() === targetMonth) {
          slugs.push(slug);
        }
      });
      return slugs.sort();
    }

    for (let i = 6; i >= 0; i -= 1) {
      const d = new Date(end.getTime());
      d.setUTCDate(d.getUTCDate() - i);
      const slug = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
      if (available.has(slug)) {
        slugs.push(slug);
      }
    }
    return slugs;
  };

  const computeRuntimeMinutesFromPayload = (payload) => {
    const perHour = payload?.condenserMinutes;
    if (Array.isArray(perHour)) {
      return perHour.reduce(
        (acc, v) => acc + (Number.isFinite(Number(v)) ? Number(v) : 0),
        0
      );
    }
    if (Number.isFinite(Number(payload?.totalCondenserMinutesValue))) {
      return Number(payload.totalCondenserMinutesValue);
    }
    return 0;
  };

  const fetchUsageSummaryForDay = async (slug) => {
    if (!slug) {
      return null;
    }
    if (usageSummaryCache.has(slug)) {
      return usageSummaryCache.get(slug);
    }
    const url = buildArchiveJsonUrl(slug);
    if (!url) {
      return null;
    }
    try {
      const resp = await fetch(url, { cache: "no-store" });
      if (!resp.ok) {
        return null;
      }
      const payload = await resp.json();
      const runtimeMinutes = computeRuntimeMinutesFromPayload(payload);
      const costPerMinute = Number(payload?.condenserCostPerMinute) || 0.05;
      const cost = runtimeMinutes * costPerMinute;
      const summary = { runtimeMinutes, cost };
      usageSummaryCache.set(slug, summary);
      return summary;
    } catch (err) {
      return null;
    }
  };

  const destroyUsageSlotChart = () => {
    if (!usageSlotChart) {
      return;
    }
    try {
      usageSlotChart.destroy();
    } catch (err) {
      // ignore
    } finally {
      usageSlotChart = null;
    }
  };

  const renderUsageSlotChart = async () => {
    if (!usageSlotCtx || typeof Chart === "undefined") {
      return;
    }

    const slugs = buildUsageRangeSlugs(usageRangeKey);
    const rows = await Promise.all(
      slugs.map(async (slug) => ({ slug, summary: await fetchUsageSummaryForDay(slug) }))
    );
    const filtered = rows.filter((r) => r.summary && Number.isFinite(Number(r.summary.runtimeMinutes)));

    let labels = [];
    let minutes = [];
    let clickSlugs = [];
    let tooltipTitles = [];
    let costByIndex = [];

    if (usageRangeKey === "year") {
      const endSlug = currentArchiveSlug || dashboardData.generatedDateSlug || "";
      const end = parseSlugDateUtc(endSlug) || new Date();
      const targetYear = end.getUTCFullYear();
      const byMonth = new Map();

      filtered.forEach((row) => {
        const d = parseSlugDateUtc(row.slug);
        if (!d || d.getUTCFullYear() !== targetYear) {
          return;
        }
        const monthIdx = d.getUTCMonth();
        const entry = byMonth.get(monthIdx) || { minutes: 0, cost: 0, lastSlug: row.slug };
        entry.minutes += Number(row.summary.runtimeMinutes) || 0;
        entry.cost += Number(row.summary.cost) || 0;
        // Prefer the latest day slug for click-through.
        if (String(row.slug) > String(entry.lastSlug)) {
          entry.lastSlug = row.slug;
        }
        byMonth.set(monthIdx, entry);
      });

      labels = MONTH_LABELS_SHORT.slice();
      minutes = labels.map((_, monthIdx) =>
        byMonth.has(monthIdx) ? Math.round(byMonth.get(monthIdx).minutes) : null
      );
      costByIndex = labels.map((_, monthIdx) => (byMonth.has(monthIdx) ? byMonth.get(monthIdx).cost : 0));
      clickSlugs = labels.map((_, monthIdx) => (byMonth.has(monthIdx) ? byMonth.get(monthIdx).lastSlug : ""));
      tooltipTitles = labels.map((label) => `${label} ${targetYear}`);
    } else {
      labels = filtered.map((r) => formatSlugShort(r.slug));
      minutes = filtered.map((r) => Number(r.summary.runtimeMinutes) || 0);
      costByIndex = filtered.map((r) => Number(r.summary.cost) || 0);
      clickSlugs = filtered.map((r) => r.slug || "");
      tooltipTitles = filtered.map((r) => r.slug || "");
    }

    const definedMinutes = minutes.filter((v) => Number.isFinite(Number(v)));
    const totalMinutes = definedMinutes.reduce((a, b) => a + Number(b), 0);
    const avgMinutes = definedMinutes.length ? totalMinutes / definedMinutes.length : 0;
    let maxIdx = -1;
    let maxVal = -1;
    minutes.forEach((value, index) => {
      const v = Number(value);
      if (Number.isFinite(v) && v > maxVal) {
        maxVal = v;
        maxIdx = index;
      }
    });
    const totalCost = costByIndex.reduce((acc, v) => acc + (Number(v) || 0), 0);

    const setStat = (id, text) => {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = text;
      }
    };
    setStat("usage-stat-total", `${Math.round(totalMinutes)}m`);
    setStat("usage-stat-avg", `${Math.round(avgMinutes)}m`);
    setStat(
      "usage-stat-max",
      maxIdx >= 0 ? `${labels[maxIdx]} ${Math.round(maxVal)}m` : "—"
    );
    setStat("usage-stat-cost", `$${totalCost.toFixed(2)}`);

    destroyUsageSlotChart();
    const monthTickStep =
      usageRangeKey === "month" ? Math.max(1, Math.ceil(labels.length / 8)) : 1;
    const usageOnBigScreen = Boolean(chartsSwapped);
    usageSlotChart = new Chart(usageSlotCtx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: minutes,
            backgroundColor: "#ad5858",
            borderColor: "#ad5858",
            borderWidth: 1,
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => {
                const idx = items?.[0]?.dataIndex ?? null;
                if (idx === null) return "";
                return tooltipTitles[idx] || "";
              },
              label: (ctxBar) => `Runtime: ${Math.round(Number(ctxBar.raw) || 0)} min`,
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: "rgba(244,246,255,0.6)",
              maxRotation: usageRangeKey === "month" || usageRangeKey === "year" ? 90 : 0,
              minRotation: usageRangeKey === "month" || usageRangeKey === "year" ? 90 : 0,
              font: { size: usageOnBigScreen ? 14 : 11 },
              padding: usageOnBigScreen ? 8 : 4,
              autoSkip: false,
              callback(value, index) {
                if (usageRangeKey !== "month") {
                  return this.getLabelForValue(value);
                }
                const last = labels.length - 1;
                if (index === 0 || index === last) {
                  return this.getLabelForValue(value);
                }
                if (monthTickStep > 1 && index % monthTickStep !== 0) {
                  return "";
                }
                return this.getLabelForValue(value);
              },
            },
            grid: { display: false },
          },
          y: {
            ticks: { color: "rgba(244,246,255,0.6)", font: { size: usageOnBigScreen ? 12 : 10 } },
            grid: { color: "rgba(255,255,255,0.08)" },
            beginAtZero: true,
          },
        },
        onClick: (evt, elements) => {
          if (!elements || !elements.length) {
            return;
          }
          const idx = elements[0].index;
          const slug = clickSlugs[idx] || "";
          if (slug) {
            loadDashboardData(slug);
          }
        },
      },
    });
  };

  const applyChartSwap = (nextSwapped) => {
    if (!canvas || !usageSlotCanvas || !usageSlotCanvasSlot || !historyChartCanvasSlot) {
      return;
    }
    const next = Boolean(nextSwapped);
    if (chartsSwapped === next) {
      return;
    }
    if (next) {
      historyChartCanvasSlot.appendChild(usageSlotCanvas);
      usageSlotCanvasSlot.appendChild(canvas);
      document.body.classList.add("charts-swapped");
      if (usagePipEl && usageHeaderEl) {
        usagePipEl.appendChild(usageHeaderEl);
        usagePipEl.setAttribute("aria-hidden", "false");
      }
    } else {
      historyChartCanvasSlot.appendChild(canvas);
      usageSlotCanvasSlot.appendChild(usageSlotCanvas);
      document.body.classList.remove("charts-swapped");
      if (usageSlotEl && usageHeaderEl) {
        usageSlotEl.insertBefore(usageHeaderEl, usageSlotEl.firstChild);
      }
      if (usagePipEl) {
        usagePipEl.setAttribute("aria-hidden", "true");
      }
    }
    chartsSwapped = next;
    updateSwapLabels();
    // Let layout settle, then fully refresh both charts so Chart.js re-measures its new parent.
    const refreshAfterSwap = async () => {
      try {
        destroyUsageSlotChart();
      } catch (err) {
        // ignore
      }
      await renderUsageSlotChart();
      try {
        destroyChart();
      } catch (err) {
        // ignore
      }
      try {
        createChart();
      } catch (err) {
        // ignore
      }
      try {
        showChart();
      } catch (err) {
        // ignore
      }
    };
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        void refreshAfterSwap();
      });
    });
  };

  const isTvHidden = () =>
    document.body && document.body.classList.contains("hide-big-chart");

  let tvModeActive = false;
  let tvPrevHideBig = true;
  let tvPrevSwapped = false;
  let tvKeyHandlerBound = false;
  let tvMouseHintBound = false;
  let tvControlsAutoHideTimer = null;

  const showTvControlsHint = (hideAfterMs = 30000) => {
    if (!tvControlsSwap) {
      return;
    }
    tvControlsSwap.classList.remove("auto-hidden");
    if (tvControlsAutoHideTimer) {
      clearTimeout(tvControlsAutoHideTimer);
      tvControlsAutoHideTimer = null;
    }
    tvControlsAutoHideTimer = setTimeout(() => {
      if (!tvModeActive || !tvControlsSwap) {
        return;
      }
      tvControlsSwap.classList.add("auto-hidden");
    }, hideAfterMs);
  };

  const enterTvMode = () => {
    if (!document.body || tvModeActive) {
      return;
    }
    tvPrevHideBig = isTvHidden();
    tvPrevSwapped = chartsSwapped;

    // Reveal the TV frame and move the currently visible small chart into it.
    document.body.classList.remove("hide-big-chart");
    // Default TV mode to the thermostat/history chart (usage remains available via swap).
    if (chartsSwapped) {
      applyChartSwap(false);
    }

    document.body.classList.add("tv-mode");
    tvModeActive = true;
    updateSwapLabels();
    showTvControlsHint(10000);
    mountTvHistory();
    bindTvHistoryToggle();

    if (!tvKeyHandlerBound) {
      tvKeyHandlerBound = true;
      window.addEventListener("keydown", (event) => {
        if (!tvModeActive) {
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          exitTvMode();
        }
      });
    }

    if (!tvMouseHintBound) {
      tvMouseHintBound = true;
      window.addEventListener("mousemove", (event) => {
        if (!tvModeActive) {
          return;
        }
        const y = Number(event?.clientY);
        if (!Number.isFinite(y)) {
          return;
        }
        if (y > window.innerHeight - 140) {
          showTvControlsHint(6000);
        }
      });
    }
  };

  const exitTvMode = () => {
    if (!document.body || !tvModeActive) {
      return;
    }
    document.body.classList.remove("tv-mode");
    tvModeActive = false;
    unmountTvHistory();
    if (tvControlsSwap) {
      tvControlsSwap.classList.remove("auto-hidden");
    }
    if (tvControlsAutoHideTimer) {
      clearTimeout(tvControlsAutoHideTimer);
      tvControlsAutoHideTimer = null;
    }

    if (chartsSwapped !== tvPrevSwapped) {
      applyChartSwap(tvPrevSwapped);
    }
    if (tvPrevHideBig) {
      document.body.classList.add("hide-big-chart");
    } else {
      document.body.classList.remove("hide-big-chart");
    }
  };

  const bindChartSwapControls = () => {
    if (chartSwapBound) {
      return;
    }
    if (!canvas || !usageSlotCanvas) {
      return;
    }
    chartSwapBound = true;

    const usageTitle = document.querySelector("#usage-slot .title");
    if (usageTitle) {
      usageTitle.title = "Swap charts";
      usageTitle.addEventListener("click", () => applyChartSwap(!chartsSwapped));
    }

    // Double-click behaviour:
    // - When TV is hidden: enter full-screen TV mode using the current small view.
    // - When in TV mode: exit back to the dashboard.
    // - Otherwise: swap charts.
    canvas.addEventListener("dblclick", () => {
      if (tvModeActive) {
        exitTvMode();
        return;
      }
      enterTvMode();
    });
    usageSlotCanvas.addEventListener("dblclick", () => {
      if (tvModeActive) {
        exitTvMode();
        return;
      }
      enterTvMode();
    });

    // In TV mode, clicking the X-axis label area swaps charts.
    if (usageSlotCanvas.dataset.boundAxisSwap !== "1") {
      usageSlotCanvas.dataset.boundAxisSwap = "1";
      usageSlotCanvas.addEventListener("click", (event) => {
        if (!usageSlotChart) {
          return;
        }
        const y = Number(event?.offsetY);
        if (!Number.isFinite(y)) {
          return;
        }
        const bottom = usageSlotChart?.chartArea?.bottom;
        if (!Number.isFinite(Number(bottom))) {
          return;
        }
        if (y < Number(bottom)) {
          return;
        }
        event.preventDefault();
        if (tvModeActive) {
          showTvControlsHint(6000);
        }
        applyChartSwap(!chartsSwapped);
      });
    }
  };

  const bindTvControls = () => {
    if (tvControlsSwap && tvControlsSwap.dataset.boundClick !== "1") {
      tvControlsSwap.dataset.boundClick = "1";
      const activate = () => {
        if (!tvModeActive) {
          return;
        }
        showTvControlsHint(6000);
        applyChartSwap(!chartsSwapped);
      };
      tvControlsSwap.addEventListener("click", (event) => {
        event.preventDefault();
        activate();
      });
      tvControlsSwap.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
    }

    if (tvArchivePrevButton && tvArchivePrevButton.dataset.boundClick !== "1") {
      tvArchivePrevButton.dataset.boundClick = "1";
      const action = () => {
        if (tvModeActive) {
          showTvControlsHint(6000);
        }
        if (tvStepMode === "hour") {
          stepPinnedPoint(-1);
        } else if (tvStepMode === "month") {
          navigateArchiveByMonths(-1);
        } else {
          navigateArchiveByDays(-1);
        }
      };
      tvArchivePrevButton.addEventListener("click", (event) => {
        const until = holdRepeatSuppressClickUntil.get(tvArchivePrevButton) || 0;
        if (until > Date.now()) {
          event.preventDefault();
          return;
        }
        action();
      });
      bindHoldRepeat(tvArchivePrevButton, action);
    }
    if (tvArchiveNextButton && tvArchiveNextButton.dataset.boundClick !== "1") {
      tvArchiveNextButton.dataset.boundClick = "1";
      const action = () => {
        if (tvModeActive) {
          showTvControlsHint(6000);
        }
        if (tvStepMode === "hour") {
          stepPinnedPoint(1);
        } else if (tvStepMode === "month") {
          navigateArchiveByMonths(1);
        } else {
          navigateArchiveByDays(1);
        }
      };
      tvArchiveNextButton.addEventListener("click", (event) => {
        const until = holdRepeatSuppressClickUntil.get(tvArchiveNextButton) || 0;
        if (until > Date.now()) {
          event.preventDefault();
          return;
        }
        action();
      });
      bindHoldRepeat(tvArchiveNextButton, action);
    }
  };


  const bindUsageSlotControls = () => {
    if (usageSlotBound) {
      return;
    }
    const slot = document.getElementById("usage-slot");
    if (!slot) {
      return;
    }
    const buttons = Array.from(slot.querySelectorAll(".usage-control"));
    if (!buttons.length) {
      return;
    }
    usageSlotBound = true;
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const range = btn.dataset.range;
        if (!range || !["7d", "month", "year"].includes(range)) {
          return;
        }
        usageRangeKey = range;
        buttons.forEach((b) => b.classList.toggle("active", b.dataset.range === range));
        renderUsageSlotChart();
      });
    });
  };
  const getLatestRowValueByHeader = (predicate) => {
    const headers = getDashboardData().headers;
    const row = getDashboardData().latestRow;
    if (!Array.isArray(headers) || !Array.isArray(row)) {
      return null;
    }
    for (let i = 0; i < headers.length; i += 1) {
      const header = headers[i];
      if (!header) {
        continue;
      }
      if (predicate(String(header))) {
        return i < row.length ? row[i] : null;
      }
    }
    return null;
  };

  const setCardValueByLabel = (labelText, value) => {
    const cards = document.querySelectorAll(".metric-card");
    if (!cards) {
      return;
    }
    const target = String(labelText || "").trim().toLowerCase();
    if (!target) {
      return;
    }
    cards.forEach((card) => {
      const labelEl = card.querySelector(".label");
      if (!labelEl) {
        return;
      }
      const label = String(labelEl.textContent || "").trim().toLowerCase();
      if (!label) {
        return;
      }
      if (label === target) {
        setCardValue(card, value);
      }
    });
  };

  const updateRequestMetadataCards = () => {
    const idx = getSelectedIndex();
    const typeSeriesValue = valueAt(getTypeSeries(), idx, null);
    const typeValue =
      typeSeriesValue !== null && typeSeriesValue !== undefined && String(typeSeriesValue).trim() !== ""
        ? typeSeriesValue
        : getLatestRowValueByHeader((h) => h.toLowerCase() === "type");
    if (typeValue !== null && typeValue !== undefined) {
      const typeCard = document.querySelector('.metric-card[data-metric="type"]');
      if (typeCard) {
        setCardValue(typeCard, String(typeValue).trim() || "—");
      } else {
        setCardValueByLabel("Type", String(typeValue).trim() || "—");
      }
    }

    const studioSeriesValue = valueAt(getStudioSeries(), idx, null);
    const studioValue =
      studioSeriesValue !== null && studioSeriesValue !== undefined
        ? studioSeriesValue
        : getLatestRowValueByHeader((h) => h.toLowerCase().includes("studio"));
    if (studioValue !== null && studioValue !== undefined) {
      setCardValueByLabel("Studio", String(studioValue).trim() || "—");
    }

    const expiresSeriesValue = valueAt(getRequestExpiresSeries(), idx, null);
    const expiresValue =
      expiresSeriesValue !== null && expiresSeriesValue !== undefined
        ? expiresSeriesValue
        : getLatestRowValueByHeader((h) => h.toLowerCase().includes("request expires"));
    if (expiresValue !== null && expiresValue !== undefined) {
      setCardValueByLabel("Request Expires (local time)", String(expiresValue).trim() || "—");
    }
  };
  const getFanLegend = () => getDashboardValue("fanLegend", ["On", "Circulate", "Auto"]);
  const getCoolingLegend = () => getDashboardValue("coolingLegend", ["Idle", "Cooling"]);
  const abbreviateFanLabel = (label) => {
    const raw = String(label || "").trim();
    if (!raw) return "";
    const key = raw.toLowerCase();
    if (key === "circulate" || key === "circulation") return "Cir.";
    if (key === "auto" || key === "automatic") return "Aut";
    if (key === "on") return "On";
    if (key === "off") return "Off";
    return raw.length <= 4 ? raw : `${raw.slice(0, 3)}.`;
  };
  const abbreviateCoolingLabel = (label) => {
    const raw = String(label || "").trim();
    if (!raw) return "";
    const key = raw.toLowerCase();
    if (key === "cooling" || key === "cool") return "Cool";
    if (key === "idle") return "Idle";
    if (key === "off") return "Off";
    return raw.length <= 4 ? raw : raw.slice(0, 4);
  };
  const getCondenserMinutes = () => getDashboardValue("condenserMinutes", []);
  const getTotalCondenserMinutesValue = () => getDashboardValue("totalCondenserMinutesValue", null);
  const getTotalCondenserMinutesDisplay = () => getDashboardValue("totalCondenserMinutes", "");
  const getTotalCondenserCostValue = () => getDashboardValue("totalCondenserCostValue", null);
  const getTotalCondenserCostDisplay = () => getDashboardValue("totalCondenserCost", "");
  const getCondenserCostPerMinute = () => getDashboardValue("condenserCostPerMinute", 0.05);

  const fanStateLabels = {
    A: "Auto",
    C: "Circulate",
    O: "On",
  };
  const fanStateToNumeric = {
    A: 0,
    C: 1,
    O: 2,
  };
  const normalizeFanState = (value) => {
    if (typeof value === "string") {
      return value.trim().toUpperCase();
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      if (value === 1) {
        return "C";
      }
      if (value === 2) {
        return "O";
      }
    }
    return "A";
  };
  const fanLabelForValue = (value) => {
    const normalized = normalizeFanState(value);
    return fanStateLabels[normalized] || String(value);
  };
  const findLastNumber = (arr) => {
    if (!arr) {
      return undefined;
    }
    for (let idx = arr.length - 1; idx >= 0; idx -= 1) {
      const value = arr[idx];
      if (typeof value === "number" && !Number.isNaN(value)) {
        return value;
      }
    }
    return undefined;
  };
  const getFanSeriesNumeric = () =>
    getFanSeries().map((value) => fanStateToNumeric[normalizeFanState(value)] ?? 0);
  const getLatestActualValue = () =>
    getDashboardData().latestActual ?? findLastNumber(getActualSeries()) ?? 50;
  const getLatestSetpointValue = () =>
    getDashboardData().latestSetpoint ?? findLastNumber(getSetpointSeries()) ?? 50;
  const getLatestOutsideValue = () =>
    getDashboardData().latestOutside ?? findLastNumber(getOutsideSeries()) ?? 50;
  const getLatestOutsideRaw = () => (getDashboardData().latestOutsideRaw || "").trim().toUpperCase();
  const getOutsideFlag = () => {
    const raw = getLatestOutsideRaw();
    return raw ? raw.charAt(0) : "";
  };
  const getOutsideFlagDayChar = () => {
    const raw = getLatestOutsideRaw();
    return raw && raw.length > 1 ? raw.charAt(1) : "D";
  };
  const getOutsideDaylight = () =>
    typeof getDashboardData().latestOutsideDaylight === "boolean"
      ? getDashboardData().latestOutsideDaylight
      : getOutsideFlagDayChar() !== "N";
  const getLatestFanRaw = () => getDashboardData().latestFan;
  const getLatestFanValue = () =>
    fanStateToNumeric[normalizeFanState(getLatestFanRaw())] ??
    findLastNumber(getFanSeriesNumeric()) ??
    0;
  const getLatestCoolingValue = () =>
    getDashboardData().latestCooling ?? findLastNumber(getCoolingSeries()) ?? 0;
  const getLatestCondenserState = () =>
    (getDashboardData().latestCondenserState || "").trim();

  const clampIndex = (idx, length) => {
    if (idx === null || idx === undefined) {
      return null;
    }
    const numeric = Number(idx);
    if (!Number.isFinite(numeric)) {
      return null;
    }
    const intIdx = Math.floor(numeric);
    if (!Number.isFinite(length) || length <= 0) {
      return null;
    }
    if (intIdx < 0 || intIdx >= length) {
      return null;
    }
    return intIdx;
  };

  const getDefaultSelectedIndex = () => {
    const labels = getChartLabels();
    if (Array.isArray(labels) && labels.length) {
      return labels.length - 1;
    }
    const actual = getActualSeries();
    if (Array.isArray(actual) && actual.length) {
      return actual.length - 1;
    }
    return 0;
  };

  const getSelectedIndex = () => {
    const labels = getChartLabels();
    const length = Array.isArray(labels) ? labels.length : 0;
    const pinned = clampIndex(pinnedPointIndex, length);
    if (pinned !== null) {
      return pinned;
    }
    const hovered = clampIndex(hoverPointIndex, length);
    if (hovered !== null) {
      return hovered;
    }
    return getDefaultSelectedIndex();
  };

  const valueAt = (arr, idx, fallback = undefined) => {
    if (!Array.isArray(arr)) {
      return fallback;
    }
    const clamped = clampIndex(idx, arr.length);
    if (clamped === null) {
      return fallback;
    }
    const value = arr[clamped];
    return value === undefined ? fallback : value;
  };
  const formatMinutesValue = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return null;
    }
    const numeric = Number(value);
    if (Number.isInteger(numeric)) {
      return `${numeric} min`;
    }
    return `${numeric.toFixed(1)} min`;
  };
  const gradientColorFor = (value) => {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return "#999";
    }
    const ratio = Math.max(0, Math.min((value - 45) / 55, 1));
    const start = [50, 130, 255];
    const end = [255, 40, 40];
    const rgb = start.map((component, idx) =>
      Math.round(component + (end[idx] - component) * ratio)
    );
    return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  };
  const colorForPoint = (value) => gradientColorFor(value ?? 50);
  const gradientColorForOutside = (value) => {
    const numeric = typeof value === "number" ? value : parseFloat(value);
    const clamped = Number.isNaN(numeric) ? 50 : Math.max(45, Math.min(numeric, 100));
    const ratio = Math.max(0, Math.min((clamped - 45) / 55, 1));
    const start = [0, 0, 0];
    const end = [255, 214, 0];
    const rgb = start.map((component, idx) =>
      Math.round(component + (end[idx] - component) * ratio)
    );
    return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  };
  const getContrastColor = (color) => {
    const match = color && color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (!match) {
      return "#f5f7ff";
    }
    const [, r, g, b] = match;
    const brightness = (Number(r) * 299 + Number(g) * 587 + Number(b) * 114) / 1000;
    return brightness > 186 ? "#000" : "#fff";
  };
  const applyCardColor = (card, color, forcedTextColor = null, setBackground = true) => {
    if (!card || !color) {
      return;
    }
    if (setBackground) {
      card.style.background = color;
      card.style.borderColor = color;
    } else {
      card.style.background = "transparent";
      card.style.borderColor = "transparent";
    }
    const textColor = forcedTextColor || getContrastColor(color);
    card.style.color = textColor;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = textColor;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = textColor;
    }
  };
  const setCardValue = (card, text) => {
    if (!card) {
      return;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.textContent = text;
    }
  };
  const formatTemperatureValue = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "";
    }
    const numeric = Number(value);
    if (Number.isInteger(numeric)) {
      return String(Math.round(numeric));
    }
    return numeric.toFixed(1);
  };
  const formatOutsideDisplay = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "";
    }
    const numeric = Number(value);
    if (Number.isInteger(numeric)) {
      return String(Math.round(numeric));
    }
    return numeric.toFixed(1);
  };

  const TOOLTIP_TEXT_COLOR = "rgba(255,255,255,0.5)";
  const TOOLTIP_BADGE_FALLBACK = "#fff5c7";
  const outsideFlagColors = {
    S: "#ffd000",
    P: "#ffb347",
    O: "#b4b4b4",
    R: "#5da9f7",
    N: "#0b1b3a",
  };
  const weatherGraphicPaths = {
    S: "../../../Images/sunny.png",
    "P-day": "../../../Images/PartlySunny.png",
    "P-night": "../../../Images/Night.png",
    "O-day": "../../../Images/cloudy.png",
    "O-night": "../../../Images/cloudynight.png",
    "R-day": "../../../Images/RainyDay.png",
    "R-night": "../../../Images/RainyNight.png",
    N: "../../../Images/clearnight.png",
  };
  const weatherGraphicImages = {};
  Object.entries(weatherGraphicPaths).forEach(([key, src]) => {
    const img = new Image();
    img.src = src;
    weatherGraphicImages[key] = img;
  });
  const getWeatherGraphicKey = (flag, dayChar) => {
    const normalizedFlag = (flag || "").toUpperCase();
    const normalizedDayChar = (dayChar || "D").toUpperCase();
    const isNight = normalizedDayChar === "N" || normalizedDayChar === "M";
    const isDay = !isNight;
    if (normalizedFlag === "P") {
      return isDay ? "P-day" : "P-night";
    }
    if (normalizedFlag === "O") {
      return isDay ? "O-day" : "O-night";
    }
    if (normalizedFlag === "R") {
      return isDay ? "R-day" : "R-night";
    }
    if (normalizedFlag === "N") {
      return "N";
    }
    return "S";
  };

  const fanStyleMap = {
    auto: {
      background: "#b4b4b4",
      border: "#8c8c8c",
      text: "#1a1a1a",
    },
    circulate: {
      background: "#e8d6ae",
      border: "#c47f00",
      text: "#000000",
    },
    on: {
      background: "#059c15",
      border: "#03660d",
      text: "#ffffff",
    },
  };
  const fanStateMap = {
    0: "auto",
    1: "circulate",
    2: "on",
  };
  // Apply themed styles specifically for the fan card so it matches the legend.
  const applyFanCardStyle = (card, fanValue) => {
    if (!card) {
      return;
    }
    const state = fanStateMap[fanValue] || "auto";
    const style = fanStyleMap[state];
    if (!style) {
      return;
    }
    card.style.background = style.background;
    card.style.borderColor = style.border;
    card.style.color = style.text;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = style.text;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = style.text;
    }
  };

  const coolingStyleMap = {
    idle: {
      background: "#93a5c9 30%",
      border: "#b0b4ba",
      text: "#1a1a1a",
    },
    cooling: {
      background: "#059c15",
      border: "#03660d",
      text: "#ffffff",
    },
  };
  const coolingStateMap = {
    0: "idle",
    1: "cooling",
  };
  // Same for cooling card; ensures Idle vs Cooling gets different colors.
  const applyCoolingCardStyle = (card, coolingValue) => {
    if (!card) {
      return;
    }
    const state = coolingStateMap[coolingValue] || "idle";
    const style = coolingStyleMap[state];
    if (!style) {
      return;
    }
    card.style.background = style.background;
    card.style.borderColor = style.border;
    card.style.color = style.text;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = style.text;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = style.text;
    }
  };
  // Mirror the condenser card colors to match cooling card palette when running.
  const applyCondenserCardStyle = (card, stateValue) => {
    if (!card) {
      return;
    }
    const text = (stateValue || "").trim().toLowerCase();
    const isOn = text.includes("on");
    const style = isOn ? coolingStyleMap.cooling : coolingStyleMap.idle;
    console.log("[condenser card] state:", stateValue, "isOn:", isOn, "style:", style);
    card.style.background = style.background;
    card.style.borderColor = style.border;
    card.style.color = style.text;
    const labelEl = card.querySelector(".label");
    if (labelEl) {
      labelEl.style.color = style.text;
    }
    const valueEl = card.querySelector(".value");
    if (valueEl) {
      valueEl.style.color = style.text;
    }
  };

  const gradientColorForCooling = (value) => {
    const ratio = Math.max(0, Math.min(value ?? 0, 1));
    const start = [211, 211, 211];
    const end = [0, 128, 64];
    const rgb = start.map((component, idx) =>
      Math.round(component + (end[idx] - component) * ratio)
    );
    return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  };
  const buildSegmentGradient = (ctxSegment, startValue, endValue) => {
    const start = startValue ?? endValue ?? 50;
    const end = endValue ?? startValue ?? 50;
    if (!ctxSegment || !ctxSegment.chart || !ctxSegment.chart.ctx || !ctxSegment.p0 || !ctxSegment.p1) {
      return colorForPoint(end);
    }
    const gradient = ctxSegment.chart.ctx.createLinearGradient(
      ctxSegment.p0.x,
      ctxSegment.p0.y,
      ctxSegment.p1.x,
      ctxSegment.p1.y
    );
    gradient.addColorStop(0, colorForPoint(start));
    gradient.addColorStop(1, colorForPoint(end));
    return gradient;
  };
  const segmentColor = (ctxSegment) => {
    const startValue = ctxSegment.p0?.parsed.y ?? ctxSegment.parsed.y ?? 50;
    const endValue = ctxSegment.p1?.parsed.y ?? ctxSegment.parsed.y ?? startValue;
    return buildSegmentGradient(ctxSegment, startValue, endValue);
  };
  const buildCoolingGradient = (ctxSegment, startValue, endValue) => {
    const start = startValue ?? endValue ?? 0;
    const end = endValue ?? startValue ?? start;
    if (!ctxSegment || !ctxSegment.chart || !ctxSegment.chart.ctx || !ctxSegment.p0 || !ctxSegment.p1) {
      return gradientColorForCooling(end);
    }
    const gradient = ctxSegment.chart.ctx.createLinearGradient(
      ctxSegment.p0.x,
      ctxSegment.p0.y,
      ctxSegment.p1.x,
      ctxSegment.p1.y
    );
    gradient.addColorStop(0, gradientColorForCooling(start));
    gradient.addColorStop(1, gradientColorForCooling(end));
    return gradient;
  };
  const coolingSegmentColor = (ctxSegment) => {
    const startValue = ctxSegment.p0?.parsed.y ?? ctxSegment.parsed.y ?? 0;
    const endValue = ctxSegment.p1?.parsed.y ?? ctxSegment.parsed.y ?? startValue;
    return buildCoolingGradient(ctxSegment, startValue, endValue);
  };
  const fanColorMap = {
    auto: "#b4b4b4",
    circulate: "#a86c59",
    on: "#00ff7f",
  };
  const fanColorForValue = (value) => {
    const normalized = normalizeFanState(value);
    if (normalized === "C") {
      return fanColorMap.circulate;
    }
    if (normalized === "O") {
      return fanColorMap.on;
    }
    return fanColorMap.auto;
  };
  const buildFanGradient = (ctxSegment, startValue, endValue) => {
    if (!ctxSegment || !ctxSegment.chart || !ctxSegment.chart.ctx || !ctxSegment.p0 || !ctxSegment.p1) {
      return fanColorForValue(endValue);
    }
    const gradient = ctxSegment.chart.ctx.createLinearGradient(
      ctxSegment.p0.x,
      ctxSegment.p0.y,
      ctxSegment.p1.x,
      ctxSegment.p1.y
    );
    gradient.addColorStop(0, fanColorForValue(startValue));
    gradient.addColorStop(1, fanColorForValue(endValue));
    return gradient;
  };
  const fanSegmentColor = (ctxSegment) => {
    const startValue =
      ctxSegment.p0?.parsed?.y ??
      ctxSegment.p0?.parsed ??
      ctxSegment.parsed?.y ??
      ctxSegment.parsed ??
      0;
    const endValue =
      ctxSegment.p1?.parsed?.y ??
      ctxSegment.p1?.parsed ??
      ctxSegment.parsed?.y ??
      ctxSegment.parsed ??
      startValue;
    if (fanColorForValue(startValue) === fanColorForValue(endValue)) {
      return fanColorForValue(endValue);
    }
    return buildFanGradient(ctxSegment, startValue, endValue);
  };
  const fanSegmentDash = (ctxSegment) => {
    const value =
      ctxSegment.p1?.parsed?.y ??
      ctxSegment.p1?.parsed ??
      ctxSegment.p0?.parsed?.y ??
      ctxSegment.p0?.parsed ??
      ctxSegment.parsed?.y ??
      ctxSegment.parsed ??
      0;
    const numeric = fanStateToNumeric[normalizeFanState(value)] ?? 0;
    return numeric >= 2 ? [] : [4, 4];
  };

  const legendSwatchColors = {
    setpoint: "#66b3ff",
    actual: "#4b4078",
    outside: "#bfd0dd",
    cooling: "#9dcfb2",
    fan: "#bfa887",
  };
  const actualPointColor = "#ffd166";
  const datasetTooltipColorMap = new Map();

  const getTooltipRawValue = (context) =>
    context?.parsed?.y ??
    context?.parsed ??
    context?.raw ??
    context?.dataset?.data?.[context.dataIndex];

  const getMonthKeyFromSlug = (slug) => {
    if (!slug) {
      return "";
    }
    if (slug.includes("-")) {
      const parts = slug.split("-");
      if (parts.length >= 2) {
        return `${parts[0]}-${parts[1]}`;
      }
    }
    return "";
  };
  const getMonthKeyFromLabel = (label) => {
    if (!label) {
      return "";
    }
    const parsed = new Date(label);
    if (!Number.isNaN(parsed)) {
      return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}`;
    }
    return "";
  };
  const getMonthLabel = (key) => {
    if (!key || !key.includes("-")) {
      return "History";
    }
    const [year, month] = key.split("-");
    const date = new Date(Number(year), Number(month) - 1, 1);
    return date.toLocaleString("default", { month: "long", year: "numeric" });
  };

  const formatTooltipValue = (rawValue) => {
    if (rawValue === null || rawValue === undefined) {
      return "Unknown";
    }
    const numericValue = Number(rawValue);
    if (!Number.isNaN(numericValue)) {
      if (Number.isInteger(numericValue)) {
        return String(Math.round(numericValue));
      }
      return numericValue.toFixed(1);
    }
    return String(rawValue).trim();
  };

  const tooltipBadgeColor = (context) => {
    const defaultColor = TOOLTIP_BADGE_FALLBACK;
    const datasetIndex = context?.datasetIndex ?? -1;
    const dataset = context?.dataset || {};
    const candidateColor =
      datasetTooltipColorMap.get(datasetIndex) ??
      dataset.legendColor ??
      dataset.borderColor ??
      dataset.backgroundColor ??
      dataset.pointBackgroundColor;
    const color =
      candidateColor && candidateColor !== "transparent"
        ? candidateColor
        : defaultColor;
    return { borderColor: color, backgroundColor: color };
  };
  const tooltipTextColor = () => TOOLTIP_TEXT_COLOR;

  const tooltipTopCenterPositioner = function () {
    const chartArea = this.chart.chartArea || {};
    const center =
      typeof chartArea.left === "number" && typeof chartArea.right === "number"
        ? Math.round((chartArea.left + chartArea.right) / 2)
        : Math.round(this.chart.width / 2);
    const top = typeof chartArea.top === "number" ? chartArea.top : 0;
    const inch = 96; // approximate pixel for 1 inch
    const extraShift = Math.round(inch * 0.75);
    const verticalOffset = Math.round(inch * 1.5); // 1.5 inches above
    // Shift left by roughly 1 inch versus the prior placement.
    return { x: center + extraShift, y: top + 18 - verticalOffset };
  };

  if (Chart?.Tooltip && Chart.Tooltip.positioners) {
    Chart.Tooltip.positioners.customTopCenter = tooltipTopCenterPositioner;
  }

  const outsideWeatherIconPlugin = {
    id: "outsideWeatherIcon",
    afterDatasetsDraw: (chartInstance) => {
      const datasetIndex = 2;
      const meta = chartInstance.getDatasetMeta(datasetIndex);
      if (!meta || meta.hidden) {
        return;
      }
      if (!meta.data.length) {
        return;
      }
      const ctxChart = chartInstance.ctx;
      const flags = getOutsideFlags();
      const flagDays = getOutsideFlagDayChars();
      meta.data.forEach((point, idx) => {
        const flag = flags[idx];
        if (!flag || flagDays.length <= idx) {
          return;
        }
        const dayChar = flagDays[idx];
        const key = getWeatherGraphicKey(flag, dayChar);
        const img = weatherGraphicImages[key];
        if (!img || !img.complete) {
          return;
        }
        const chartHeight = chartInstance.height || 1;
        const size = Math.min(32, Math.max(24, Math.round((chartHeight / 420) * 30)));
        ctxChart.save();
        ctxChart.globalAlpha = 0.9;
        ctxChart.translate(point.x, point.y);
        ctxChart.beginPath();
        ctxChart.arc(0, 0, size / 2, 0, Math.PI * 2);
        ctxChart.clip();
        const gradient = ctxChart.createRadialGradient(0, 0, size * 0.05, 0, 0, size / 2);
        gradient.addColorStop(0, "rgba(255,255,255,0.9)");
        gradient.addColorStop(1, "rgba(255,255,255,0.0)");
        ctxChart.fillStyle = gradient;
        ctxChart.fillRect(-size / 2, -size / 2, size, size);
        ctxChart.globalAlpha = 1;
        ctxChart.drawImage(img, -size / 2, -size / 2, size, size);
        ctxChart.restore();
      });
    },
  };

  const destroyChart = () => {
    if (!chart) {
      return;
    }
    try {
      chart.destroy();
    } catch (err) {
      console.warn("Unable to destroy existing chart", err);
    } finally {
      chart = null;
    }
  };
  const updateLegendImage = () => {
    if (!chart || !chart.legend) {
      return;
    }
    const legendBox = chart.legend;
    let { left, top, width, height } = legendBox;
    if (!width || !height) {
      return;
    }
    try {
      height -= 275;
      width -= 20;
    } catch (error) {
      console.warn("Legend box adjustment error:", error);
    }
    if (!width || !height) {
      return;
    }
    const legendCanvas = document.createElement("canvas");
    legendCanvas.width = width;
    legendCanvas.height = height;
    const legendCtx = legendCanvas.getContext("2d");
    if (!legendCtx) {
      return;
    }
    legendCtx.drawImage(
      chart.canvas,
      left,
      top,
      width,
      height,
      0,
      0,
      width,
      height
    );
    const dataUrl = legendCanvas.toDataURL("image/png");
    const legendImg = document.getElementById("legend-image");
    if (legendImg && dataUrl) {
      legendImg.src = dataUrl;
    }
  };

  // Create the history chart with five datasets and custom scale/tooltip behavior.
  const createChart = () => {
    if (chart || !ctx) {
      return;
    }
    canvas.style.display = "block";

    const selectionMarkerPlugin = {
      id: "selectionMarker",
      afterDatasetsDraw: (chartInstance) => {
        const labels = getChartLabels();
        const length = Array.isArray(labels) ? labels.length : 0;
        const pinned = clampIndex(pinnedPointIndex, length);
        const hovered = clampIndex(hoverPointIndex, length);
        const idx = pinned !== null ? pinned : hovered;
        if (idx === null) {
          return;
        }

        const meta = chartInstance.getDatasetMeta(1); // actual temp dataset
        const point = meta?.data?.[idx];
        if (!point) {
          return;
        }

        const { top, bottom } = chartInstance.chartArea || {};
        if (typeof top !== "number" || typeof bottom !== "number") {
          return;
        }

        const ctxChart = chartInstance.ctx;
        const isPinned = pinned !== null;
        const stroke = isPinned ? "rgba(255,179,71,0.95)" : "rgba(255,179,71,0.45)";
        const width = isPinned ? 2 : 1;
        const radius = isPinned ? 6 : 4;

        ctxChart.save();
        ctxChart.beginPath();
        ctxChart.lineWidth = width;
        ctxChart.strokeStyle = stroke;
        ctxChart.moveTo(point.x, top);
        ctxChart.lineTo(point.x, bottom);
        ctxChart.stroke();

        ctxChart.beginPath();
        ctxChart.fillStyle = stroke;
        ctxChart.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctxChart.fill();
        ctxChart.lineWidth = 2;
        ctxChart.strokeStyle = "#000";
        ctxChart.stroke();
        ctxChart.restore();
      },
    };
    const dataset = {
      labels: getChartLabels(),
      datasets: [
        {
          label: getSetpointLabel(),
          data: getSetpointSeries(),
          segment: {
            borderColor: legendSwatchColors.setpoint,
          },
          backgroundColor: "rgba(102,179,255,0.18)",
          borderColor: legendSwatchColors.setpoint,
          pointBackgroundColor: legendSwatchColors.setpoint,
          pointBorderColor: legendSwatchColors.setpoint,
          legendColor: legendSwatchColors.setpoint,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointBorderWidth: 2,
          spanGaps: true,
        },
        {
          label: getActualLabel(),
          data: getActualSeries(),
          segment: {
            borderColor: segmentColor,
          },
          backgroundColor: "rgba(125,164,255,0.2)",
          borderColor: legendSwatchColors.actual,
          pointBackgroundColor: actualPointColor,
          pointBorderColor: actualPointColor,
          pointHoverBackgroundColor: actualPointColor,
          pointHoverBorderColor: actualPointColor,
          legendColor: legendSwatchColors.actual,
          pointRadius: 0,
          pointHoverRadius: 6,
          pointBorderWidth: 2,
          spanGaps: true,
        },
        {
          label: getOutsideLabel(),
          data: getOutsideSeries(),
          showLine: false,
          pointRadius: 0,
          borderColor: legendSwatchColors.outside,
          pointBackgroundColor: legendSwatchColors.outside,
          pointBorderColor: legendSwatchColors.outside,
          legendColor: legendSwatchColors.outside,
          spanGaps: true,
        },
        {
          label: getCoolingLabel(),
          data: getCoolingSeries(),
          segment: {
            borderColor: coolingSegmentColor,
          },
          backgroundColor: "rgba(255,107,107,0.2)",
          yAxisID: "cooling",
          borderColor: legendSwatchColors.cooling,
          pointBackgroundColor: legendSwatchColors.cooling,
          pointBorderColor: legendSwatchColors.cooling,
          legendColor: legendSwatchColors.cooling,
          spanGaps: true,
          pointRadius: 0,
        },
        {
          label: "Fan Mode",
          data: getFanSeriesNumeric(),
          segment: {
            borderColor: fanSegmentColor,
          },
          backgroundColor: "rgba(255,165,0,0.3)",
          yAxisID: "fan",
          borderColor: legendSwatchColors.fan,
          pointBackgroundColor: legendSwatchColors.fan,
          pointBorderColor: legendSwatchColors.fan,
          legendColor: legendSwatchColors.fan,
          spanGaps: true,
          pointRadius: 0,
        },
      ],
    };
    datasetTooltipColorMap.clear();
    datasetTooltipColorMap.set(0, legendSwatchColors.setpoint);
    datasetTooltipColorMap.set(1, legendSwatchColors.actual);
    datasetTooltipColorMap.set(2, legendSwatchColors.outside);
    datasetTooltipColorMap.set(3, legendSwatchColors.cooling);
    datasetTooltipColorMap.set(4, legendSwatchColors.fan);
    chart = new Chart(ctx, {
      type: "line",
      data: dataset,
      plugins: [outsideWeatherIconPlugin, selectionMarkerPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
          padding: {
            right: 0,
          },
        },
        animation: {
          duration: 1400,
          easing: "easeOutQuart",
          onComplete: () => {
            reapplyVisibility();
            if (chart) {
              chart.update("none");
            }
          },
        },
        animations: {
          tension: {
            duration: 1000,
            easing: "easeOutBounce",
            from: 1,
            to: 0,
            loop: false,
          },
          y: {
            easing: "easeInOutElastic",
            duration: 800,
          },
        },
        scales: {
          y: {
            beginAtZero: false,
            min: 45,
            max: 100,
            ticks: {
              color: (ctxValue) => colorForPoint(ctxValue.tick.value),
            },
            grid: {
              color: "rgba(255,255,255,0.1)",
            },
          },
          fan: {
            type: "linear",
            position: "right",
            min: -1,
            max: 2,
            ticks: {
              stepSize: 1,
              callback: (value) => abbreviateFanLabel(getFanLegend()[Math.round(value)] || ""),
              color: (ctxValue) => {
                const tickValue = ctxValue.tick?.value ?? ctxValue.parsed ?? null;
                return fanColorForValue(tickValue);
              },
            },
            grid: {
              drawOnChartArea: false,
              color: "rgba(255,255,255,0.08)",
            },
          },
          cooling: {
            type: "linear",
            position: "right",
            offset: false,
            min: -1,
            max: 2,
            ticks: {
              stepSize: 1,
              callback: (value) => abbreviateCoolingLabel(getCoolingLegend()[Math.round(value)] || ""),
              color: (ctxValue) => {
                const numeric = Number(ctxValue.tick.value);
                return Number.isNaN(numeric) || numeric <= 0 ? "#ffd000" : "#32d15c";
              },
            },
            grid: {
              drawOnChartArea: true,
              color: "rgba(50,209,92,0.15)",
            },
          },
           x: {
             ticks: {
               // Lower label opacity for the X-axis coordinates (more subtle than the lines).
               color: "rgba(244,246,255,0.4)",
               callback: function (value) {
                 const raw = this && typeof this.getLabelForValue === "function" ? this.getLabelForValue(value) : value;
          //       return formatXAxisTimeLabel(raw);
           
                 return formatXAxisTimeLabel(" ");
               },
               maxRotation: 0,
               minRotation: 90,
               padding: 8,
             },
             grid: {
              color: "rgba(255,255,255,0.08)",
            },
          },
        },
        interaction: {
          mode: "nearest",
          intersect: false,
          axis: "x",
          includeInvisible: true,
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (context) => {
                const label = context.dataset.label || "";
                const seriesIndex = context.dataIndex;
                const minutes = getCondenserMinutes()[seriesIndex];
                const minuteLabel = formatMinutesValue(minutes);
                const rawValue = getTooltipRawValue(context);
                if (context.dataset.yAxisID === "fan") {
                  return `${label}: ${fanLabelForValue(rawValue) || "Unknown"}`;
                }
                if (context.dataset.yAxisID === "cooling") {
                  const numeric = Number(rawValue);
                  const value = Number.isNaN(numeric) ? 0 : numeric;
                  const statusLine = `${label}: ${getCoolingLegend()[Math.round(value)] || "Unknown"}`;
                  if (minuteLabel) {
                    return [statusLine, `     Runtime: ${minuteLabel}`];
                  }
                  return statusLine;
                }
                const formattedValue = formatTooltipValue(rawValue);
                return `${label}: ${formattedValue}`;
              },
            },
            displayColors: true,
            labelColor: tooltipBadgeColor,
            labelTextColor: tooltipTextColor,
            titleColor: tooltipTextColor,
            bodyColor: tooltipTextColor,
            position: "customTopCenter",
            yAlign: "top",
            xAlign: "center",
            caretSize: 0,
          },
        },
      },
    });
    updateLegendImage();
    bindChartPointPicker();
  };

  const setSelectedPoint = (nextHoverIdx, nextPinnedIdx = null, persist = false) => {
    hoverPointIndex = nextHoverIdx;
    pinnedPointIndex = nextPinnedIdx;
    updateMetricCards();
    updateTimestampFromSelection();
    updateSelectionIndicator();
    if (persist) {
      saveUiState();
    }
  };

  const bindChartPointPicker = () => {
    if (chartPointPickerBound || !canvas) {
      return;
    }
    chartPointPickerBound = true;

    const isXAxisClickForSwap = (event) => {
      if (!chart) {
        return false;
      }
      const y = Number(event?.offsetY);
      if (!Number.isFinite(y)) {
        return false;
      }
      const bottom = chart?.chartArea?.bottom;
      if (!Number.isFinite(Number(bottom))) {
        return false;
      }
      return y >= Number(bottom);
    };

    const pickIndexFromEvent = (event) => {
      if (!chart) {
        return null;
      }
      try {
        const points = chart.getElementsAtEventForMode(
          event,
          "nearest",
          { intersect: false },
          true
        );
        if (!points || points.length === 0) {
          return null;
        }
        const idx = points[0]?.index;
        return Number.isFinite(Number(idx)) ? Number(idx) : null;
      } catch (err) {
        return null;
      }
    };

    canvas.addEventListener("mousemove", (event) => {
      if (pinnedPointIndex !== null) {
        return;
      }
      if (suppressHoverUntilMouseLeave) {
        return;
      }
      const idx = pickIndexFromEvent(event);
      if (idx === null) {
        return;
      }
      if (hoverPointIndex === idx) {
        return;
      }
      setSelectedPoint(idx, null, false);
    });

    canvas.addEventListener("mouseleave", () => {
      suppressHoverUntilMouseLeave = false;
      if (pinnedPointIndex !== null) {
        return;
      }
      if (hoverPointIndex === null) {
        return;
      }
      setSelectedPoint(null, null, false);
    });

    canvas.addEventListener("click", (event) => {
      if (isXAxisClickForSwap(event)) {
        event.preventDefault();
        if (tvModeActive) {
          showTvControlsHint(6000);
        }
        applyChartSwap(!chartsSwapped);
        return;
      }
      const idx = pickIndexFromEvent(event);
      if (idx === null) {
        setSelectedPoint(null, null, true);
        suppressHoverUntilLeave();
        return;
      }
      if (pinnedPointIndex === idx) {
        setSelectedPoint(idx, null, true);
      } else {
        setSelectedPoint(idx, idx, true);
      }
    });

    ensureSelectionUi();
    // Note: Clear Pin click binding happens in ensureSelectionUi() so it remains
    // stable even if the chart picker is initialized before the button exists.

    if (hourPickerEl) {
      hourPickerEl.addEventListener("change", () => {
        const raw = String(hourPickerEl.value || "").trim();
        if (!raw) {
          setSelectedPoint(null, null, true);
          suppressHoverUntilLeave();
          hourPickerEl.style.color = "#ffb347";
          return;
        }
        if (!raw.startsWith("H")) {
          return;
        }
        const hour24 = Number(raw.slice(1));
        if (!Number.isFinite(hour24)) {
          return;
        }
        hourPickerEl.style.color = "#f4f6ff";
        const labels = getChartLabels();
        if (!Array.isArray(labels) || labels.length === 0) {
          return;
        }
        let chosenIdx = null;
        for (let i = 0; i < labels.length; i += 1) {
          const h = roundedUpHour24FromLabel(labels[i]);
          if (h === hour24) {
            chosenIdx = i; // keep last match
          }
        }
        if (chosenIdx === null) {
          setSelectedPoint(null, null, true);
          suppressHoverUntilLeave();
          return;
        }
        setSelectedPoint(chosenIdx, chosenIdx, true);
      });
    }
  };

  if (chartStepPrevButton && chartStepPrevButton.dataset.boundClick !== "1") {
    chartStepPrevButton.dataset.boundClick = "1";
    const action = () => stepPinnedPoint(-1);
    chartStepPrevButton.addEventListener("click", (event) => {
      const until = holdRepeatSuppressClickUntil.get(chartStepPrevButton) || 0;
      if (until > Date.now()) {
        event.preventDefault();
        return;
      }
      action();
    });
    bindHoldRepeat(chartStepPrevButton, action);
  }
  if (chartStepNextButton && chartStepNextButton.dataset.boundClick !== "1") {
    chartStepNextButton.dataset.boundClick = "1";
    const action = () => stepPinnedPoint(1);
    chartStepNextButton.addEventListener("click", (event) => {
      const until = holdRepeatSuppressClickUntil.get(chartStepNextButton) || 0;
      if (until > Date.now()) {
        event.preventDefault();
        return;
      }
      action();
    });
    bindHoldRepeat(chartStepNextButton, action);
  }
  const bindTvStepMode = (el, mode) => {
    if (!el || el.dataset.boundChange === "1") {
      return;
    }
    el.dataset.boundChange = "1";
    el.addEventListener("change", () => {
      if (el.checked) {
        setTvStepMode(mode);
      } else if (tvStepMode === mode) {
        setTvStepMode("day");
      }
    });
  };
  bindTvStepMode(tvStepMonth, "month");
  bindTvStepMode(tvStepDay, "day");
  bindTvStepMode(tvStepHour, "hour");

  const bindTransportStepMode = (el, mode) => {
    if (!el || el.dataset.boundChange === "1") {
      return;
    }
    el.dataset.boundChange = "1";
    el.addEventListener("change", () => {
      if (el.checked) {
        setTransportStepMode(mode);
      } else if (transportStepMode === mode) {
        setTransportStepMode("day");
      }
    });
  };
  bindTransportStepMode(transportStepMonth, "month");
  bindTransportStepMode(transportStepDay, "day");

  // Re-render all front-panel cards when the data changes (actual, fan, condenser, etc.).
  const updateMetricCards = () => {
    const idx = getSelectedIndex();
    updateRequestMetadataCards();
    const timestampCard = document.querySelector('.metric-card[data-metric="timestamp"]');
    if (timestampCard) {
      const label = valueAt(getChartLabels(), idx, null);
      if (label) {
        setCardValue(timestampCard, String(label));
      }
    }
    const climateSettingCard = document.querySelector('.metric-card[data-metric="climate-setting"]');
    if (climateSettingCard) {
      // The facility is always configured for cooling only.
      setCardValue(climateSettingCard, "Cool");
    }
    const actualValue = valueAt(getActualSeries(), idx, getLatestActualValue());
    const setpointValue = valueAt(getSetpointSeries(), idx, getLatestSetpointValue());
    const outsideValue = valueAt(getOutsideSeries(), idx, getLatestOutsideValue());
    const outsideFlag = valueAt(getOutsideFlags(), idx, getOutsideFlag());
    const outsideDayChar = valueAt(getOutsideFlagDayChars(), idx, getOutsideFlagDayChar());
    const outsideDaylight =
      typeof outsideDayChar === "string"
        ? outsideDayChar.trim().toUpperCase() !== "N"
        : getOutsideDaylight();
    const outsideFlagColor = outsideFlagColors[outsideFlag] || null;
    const outsideCard = document.querySelector('.metric-card[data-metric="outside"]');
    const outsideText = formatOutsideDisplay(outsideValue);
    setCardValue(outsideCard, outsideText);
    applyCardColor(
      outsideCard,
      outsideFlagColor || gradientColorForOutside(outsideValue),
      outsideFlag === "N" ? "#fff" : null,
      outsideFlag === "S"
    );
    if (outsideCard) {
      let graphic = outsideCard.querySelector(".sunny-graphic");
      if (!graphic) {
        graphic = document.createElement("div");
        graphic.className = "sunny-graphic";
        outsideCard.appendChild(graphic);
      }
      let pathKey = outsideFlag;
      if (outsideFlag === "P") {
        pathKey = outsideDaylight ? "P-day" : "P-night";
      } else if (outsideFlag === "O") {
        pathKey = outsideDaylight ? "O-day" : "O-night";
      } else if (outsideFlag === "R") {
        pathKey = outsideDaylight ? "R-day" : "R-night";
      } else if (outsideFlag === "N") {
        pathKey = "N";
      }
      const path = weatherGraphicPaths[pathKey];
      if (path) {
        graphic.style.backgroundImage = `url("${path}")`;
        outsideCard.classList.add("sunny-image");
      } else {
        graphic.style.backgroundImage = "";
        outsideCard.classList.remove("sunny-image");
      }
    }
    const actualCard = document.querySelector('.metric-card[data-metric="actual"]');
    setCardValue(actualCard, formatTemperatureValue(actualValue));
    const actualNumeric = Number(actualValue);
    const actualCardColor = Number.isFinite(actualNumeric)
      ? colorForPoint(actualNumeric)
      : legendSwatchColors.actual;
    applyCardColor(actualCard, actualCardColor);
    const setpointCard = document.querySelector('.metric-card[data-metric="setpoint"]');
    setCardValue(setpointCard, formatTemperatureValue(setpointValue));
    // Match the setpoint line color in the chart for visual consistency.
    applyCardColor(setpointCard, legendSwatchColors.setpoint, "#000");

    const fanCard = document.querySelector('.metric-card[data-metric="fan"]');
    const fanLabelRaw = valueAt(getFanSeries(), idx, getLatestFanRaw());
    const fanNorm = normalizeFanState(fanLabelRaw);
    const fanText = fanStateLabels[fanNorm] || (fanLabelRaw ? String(fanLabelRaw).trim() : "Auto");
    setCardValue(fanCard, fanText);
    applyFanCardStyle(fanCard, fanStateToNumeric[fanNorm] ?? getLatestFanValue());

    const coolingCard = document.querySelector('.metric-card[data-metric="cooling"]');
    const coolingValue = valueAt(getCoolingSeries(), idx, getLatestCoolingValue());
    setCardValue(coolingCard, getCoolingLegend()[Math.round(coolingValue)] || "Idle");
    applyCoolingCardStyle(coolingCard, coolingValue);
    const condenserCard = document.querySelector('.metric-card[data-metric="condenser-state"]');
    const condenserMinutesSeries = getCondenserMinutes();
    const minutesThisHour = valueAt(condenserMinutesSeries, idx, null);
    const condenserStateValue =
      Number(minutesThisHour) > 0 || Number(coolingValue) > 0
        ? "On"
        : "Off";
    if (condenserCard) {
      setCardValue(condenserCard, condenserStateValue || "Unknown");
      applyCondenserCardStyle(condenserCard, condenserStateValue);
    }

    const condenserMinutesCard = document.querySelector('.metric-card[data-metric="condenser-minutes"]');
    if (condenserMinutesCard) {
      const minutesLabel = formatMinutesValue(minutesThisHour);
      setCardValue(condenserMinutesCard, minutesLabel || "0 min");
    }
    updateCondenserRuntimeSummary();
  };

  const datasetIndexByMode = {
    setpoint: 0,
    actual: 1,
    outside: 2,
    cooling: 3,
    fan: 4,
  };
  const enabledModes = new Set(Object.keys(datasetIndexByMode));
  const updateAxesVisibility = () => {
    if (!chart) {
      return;
    }
    const showTemp =
      enabledModes.has("setpoint") ||
      enabledModes.has("actual") ||
      enabledModes.has("outside");
    const showFan = enabledModes.has("fan");
    const showCooling = enabledModes.has("cooling");
    chart.options.scales.y.display = showTemp;
    chart.options.scales.y.ticks.display = showTemp;
    chart.options.scales.fan.display = showFan;
    chart.options.scales.cooling.display = showCooling;
    chart.options.scales.fan.ticks.display = showFan;
    chart.options.scales.cooling.ticks.display = showCooling;
  };
  const updateButtonStates = () => {
    if (!chartControlButtons) {
      return;
    }
    const allModesEnabled = Object.keys(datasetIndexByMode).every((mode) =>
      enabledModes.has(mode)
    );
    chartControlButtons.forEach((btn) => {
      const mode = btn.dataset.mode;
      if (mode === "both") {
        btn.classList.toggle("active", allModesEnabled);
      } else {
        btn.classList.toggle("active", enabledModes.has(mode));
      }
    });
  };
  const updateChartVisibility = () => {
    if (!chart) {
      return;
    }
    Object.entries(datasetIndexByMode).forEach(([mode, idx]) => {
      const dataset = chart.data.datasets[idx];
      if (!dataset) {
        return;
      }
      const nextHidden = !enabledModes.has(mode);
      dataset.hidden = nextHidden;
      const meta = chart.getDatasetMeta(idx);
      if (meta) {
        meta.hidden = nextHidden;
      }
    });
  };

  // Force a repaint of dataset segments by temporarily enabling all modes.
  const reapplyVisibility = () => {
    if (!chart) {
      return;
    }
    const currentModes = new Set(enabledModes);
    Object.keys(datasetIndexByMode).forEach((m) => enabledModes.add(m));
    updateChartVisibility();
    updateAxesVisibility();
    chart.update();
    enabledModes.clear();
    currentModes.forEach((m) => enabledModes.add(m));
    updateChartVisibility();
    updateAxesVisibility();
    updateButtonStates();
    chart.update();
  };

  const setModeSet = (modes, animate = false) => {
    enabledModes.clear();
    modes.forEach((m) => enabledModes.add(m));
    updateChartVisibility();
    updateAxesVisibility();
    updateButtonStates();
    if (chart) {
      chart.update(animate ? undefined : "none");
    }
  };

  const applySavedModes = () => {
    savedUiState = savedUiState || loadUiState();
    const rawModes = savedUiState?.modes;
    if (!Array.isArray(rawModes) || rawModes.length === 0) {
      return;
    }
    const allowed = new Set(Object.keys(datasetIndexByMode));
    const filtered = rawModes.filter((m) => allowed.has(m));
    if (filtered.length === 0) {
      return;
    }
    setModeSet(filtered, false);
  };

  applySavedModes();
  const toggleMode = (mode) => {
    if (mode === "both") {
      const allEnabled = Object.keys(datasetIndexByMode).every((m) =>
        enabledModes.has(m)
      );
      if (allEnabled) {
        enabledModes.clear();
      } else {
        Object.keys(datasetIndexByMode).forEach((m) => enabledModes.add(m));
      }
    } else if (mode) {
      if (enabledModes.has(mode)) {
        enabledModes.delete(mode);
      } else {
        enabledModes.add(mode);
      }
    }
    if (!chart) {
      createChart();
    }
    updateChartVisibility();
    updateAxesVisibility();
    updateButtonStates();
    if (chart) {
      chart.update();
    }
    saveUiState();
  };

  const showChart = () => {
    if (!chart) {
      createChart();
    }
    updateChartVisibility();
    updateAxesVisibility();
    updateButtonStates();
    if (canvas) {
      canvas.style.display = "block";
    }
    if (toggleHistoryBtn) {
      toggleHistoryBtn.textContent = "Hide History Chart";
      toggleHistoryBtn.classList.add("history-visible");
    }
    if (handsLogoTop) {
      handsLogoTop.classList.remove("hidden");
    }
    scheduleAutoplay();
  };

  const hideChart = () => {
    if (canvas) {
      canvas.style.display = "none";
    }
    if (toggleHistoryBtn) {
      toggleHistoryBtn.textContent = "Show History Chart";
      toggleHistoryBtn.classList.remove("history-visible");
    }
    if (handsLogoTop) {
      handsLogoTop.classList.add("hidden");
    }
    stopAutoplay();
  };

  const stopAutoplay = (preserveModes = false) => {
    if (autoplayTimer) {
      clearInterval(autoplayTimer);
      autoplayTimer = null;
    }
    if (autoplayIdleTimer) {
      clearTimeout(autoplayIdleTimer);
      autoplayIdleTimer = null;
    }
    if (chart) {
      chart.setActiveElements([]);
      chart.tooltip.setActiveElements([]);
      chart.update("none");
    }
    if (!preserveModes && savedModesBeforeAutoplay) {
      setModeSet(Array.from(savedModesBeforeAutoplay));
    }
    if (!preserveModes) {
      savedModesBeforeAutoplay = null;
      autoplaySegmentIndex = 0;
    }
  };

  const highlightPoint = (index) => {
    if (!chart || !chart.data || !chart.data.labels) {
      return;
    }
    const pointIndex = index % chart.data.labels.length;
    const active = [];
    chart.data.datasets.forEach((ds, datasetIndex) => {
      const meta = chart.getDatasetMeta(datasetIndex);
      const visible = ds && meta && !ds.hidden && !meta.hidden;
      if (visible) {
        active.push({ datasetIndex, index: pointIndex });
      }
    });
    chart.setActiveElements(active);
    chart.tooltip.setActiveElements(active);
    chart.update("none");
  };

  const startAutoplay = (immediate = false) => {
    if (!autoplayEnabled || !chart || !chart.data || !chart.data.labels?.length) {
      return;
    }
    if (!savedModesBeforeAutoplay) {
      savedModesBeforeAutoplay = new Set(enabledModes);
    }
    if (autoplayTimer) {
      clearInterval(autoplayTimer);
    }
    const labelsLen = chart.data.labels.length || 1;
    const activeSegmentsCount = AUTOPLAY_SEQUENCE.filter((seg) => seg.modes)?.length || 1;
    const totalSteps = labelsLen * activeSegmentsCount;
    autoplayStepMs = Math.max(
      AUTOPLAY_MIN_STEP_MS,
      Math.round(AUTOPLAY_TARGET_MS / totalSteps)
    );
    const applyCurrentSegment = () => {
      const segment = AUTOPLAY_SEQUENCE[autoplaySegmentIndex % AUTOPLAY_SEQUENCE.length];
      if (!segment) {
        return;
      }
      if (segment.pauseMs) {
        if (autoplayTimer) {
          clearInterval(autoplayTimer);
          autoplayTimer = null;
        }
        hideChart();
        if (handsLogoTop) {
          handsLogoTop.classList.remove("hidden");
        }
        setTimeout(() => {
          // Move to next segment after pause
          autoplaySegmentIndex = (autoplaySegmentIndex + 1) % AUTOPLAY_SEQUENCE.length;
          showChart();
          setModeSet(AUTOPLAY_SEQUENCE[autoplaySegmentIndex % AUTOPLAY_SEQUENCE.length].modes || [], true);
          autoplayIndex = 0;
          startAutoplay(true);
        }, segment.pauseMs);
        return false;
      }
      setModeSet(segment.modes || [], true);
      return true;
    };

    autoplayIndex = 0;
    const ready = applyCurrentSegment();
    if (!ready) {
      return;
    }
    if (immediate) {
      highlightPoint(autoplayIndex);
    }
    autoplayTimer = setInterval(() => {
      autoplayIndex = (autoplayIndex + 1) % chart.data.labels.length;
      if (autoplayIndex === 0) {
        autoplaySegmentIndex = (autoplaySegmentIndex + 1) % AUTOPLAY_SEQUENCE.length;
        const readyNext = applyCurrentSegment();
        if (!readyNext) {
          return;
        }
      }
      highlightPoint(autoplayIndex);
    }, autoplayStepMs);
  };

  const scheduleAutoplay = () => {
    if (!autoplayEnabled) {
      return;
    }
    if (autoplayIdleTimer) {
      clearTimeout(autoplayIdleTimer);
    }
    autoplayIdleTimer = setTimeout(() => {
      startAutoplay(true);
    }, AUTOPLAY_IDLE_MS);
  };

  const markInteraction = () => {
    stopAutoplay(true);
    scheduleAutoplay();
  };

  const ensureAutoplayScheduled = () => {
    if (!autoplayEnabled) {
      return;
    }
    if (!autoplayTimer && !autoplayIdleTimer) {
      scheduleAutoplay();
    }
  };

  function loadDashboardData(slug) {
    if (!slug) {
      logMessage("Missing archive slug.", "warn");
      return;
    }
    const url = buildArchiveJsonUrl(slug);
    if (!url) {
      logMessage(`Unable to build URL for slug ${slug}`, "warn");
      return;
    }
    fetch(url, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          const err = new Error(`Status ${response.status}`);
          err.status = response.status;
          throw err;
        }
        return response.json();
      })
      .then((data) => {
        applyDashboardData(data, slug);
      })
      .catch((error) => {
        if (Number(error?.status) === 404 && dashboardData?.archiveDates) {
          archiveExistenceCache.set(slug, false);
          dashboardData.archiveDates = dashboardData.archiveDates.filter((entry) => entry?.slug !== slug);
          renderArchiveList();
        }
        logMessage(`Failed to load archive ${slug}: ${error}`, "error");
      });
  }

  const setActiveArchiveItem = (slug) => {
    if (!chartHistoryList) {
      return;
    }
    chartHistoryList.querySelectorAll("button").forEach((btn) => {
      btn.classList.toggle("active", slug && btn.dataset.slug === slug);
    });
  };

  const closeHistoryList = () => {
    hideHistoryFiles();
  };

  const toggleHistoryList = () => {
    setHistoryExpanded(!historyExpanded);
  };

  const updateHistoryStatus = (slug) => {
    const label = slug ? archiveLabelMap.get(slug) : null;
    const text = label || (slug ? String(slug) : "Current");
    const compactMonthDay = (value) => {
      const trimmed = String(value || "").trim();
      if (!trimmed) {
        return trimmed;
      }
      const match = trimmed.match(/^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*\d{4})?$/);
      if (!match) {
        return trimmed;
      }
      return `${match[1]} ${match[2]}`;
    };
    const mainDisplay = document.body && document.body.classList.contains("tv-mode")
      ? text
      : compactMonthDay(text);
    if (chartHistoryStatus) {
      chartHistoryStatus.textContent = mainDisplay;
    }
    if (transportHistoryStatus) {
      transportHistoryStatus.textContent = mainDisplay;
    }
    if (transportHistoryMonth || transportHistoryDay) {
      const trimmed = String(text || "").trim();
      const match = trimmed.match(/^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*\d{4})?$/);
      if (match) {
        const month = String(match[1] || "").slice(0, 3).toUpperCase();
        const day = String(match[2] || "");
        if (transportHistoryMonth) {
          transportHistoryMonth.textContent = month;
        }
        if (transportHistoryDay) {
          transportHistoryDay.textContent = day;
        }
      } else {
        if (transportHistoryMonth) {
          transportHistoryMonth.textContent = compactMonthDay(trimmed) || "Current";
        }
        if (transportHistoryDay) {
          transportHistoryDay.textContent = "";
        }
      }
    }
    if (tvHistoryMonth || tvHistoryDay) {
      const trimmed = String(text || "").trim();
      const match = trimmed.match(/^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*\d{4})?$/);
      if (match) {
        if (tvHistoryMonth) {
          tvHistoryMonth.textContent = String(match[1] || "").toUpperCase();
        } else if (tvHistoryStatus) {
          tvHistoryStatus.textContent = String(match[1] || "").toUpperCase();
        }
        if (tvHistoryDay) {
          tvHistoryDay.textContent = String(match[2] || "");
        }
        const monthText = String(match[1] || "").toUpperCase();
        const dayText = String(match[2] || "");
        setTvStepReadout(monthText, dayText, tvStepTimeValue?.textContent || "");
      } else {
        if (tvHistoryMonth) {
          tvHistoryMonth.textContent = trimmed || "Current";
        } else if (tvHistoryStatus) {
          tvHistoryStatus.textContent = trimmed || "Current";
        }
        if (tvHistoryDay) {
          tvHistoryDay.textContent = "";
        }
        setTvStepReadout(trimmed || "Current", "", "");
      }
    } else if (tvHistoryStatus) {
      tvHistoryStatus.textContent = text;
    }
  };

  const bindTransportHistoryToggle = () => {
    const transportPanel = document.getElementById("transport-panel");
    if (!transportPanel || transportPanel.dataset.boundHistoryToggle === "1") {
      return;
    }
    transportPanel.dataset.boundHistoryToggle = "1";
    transportPanel.title = "Click to select a history file";
    transportPanel.addEventListener("click", (event) => {
      // Don't interfere with actual navigation controls inside the transport panel.
      const target = event.target;
      if (
        target &&
        target.closest &&
        target.closest("button,select,a,input,textarea,label,.transport-step-modes")
      ) {
        return;
      }
      // If a history file has been selected, clicking the cassette deck "loads" it (after spin).
      if (pendingSelectedArchiveSlug && target && target.closest && target.closest("#transport-deck")) {
        event.preventDefault();
        const slug = pendingSelectedArchiveSlug;
        pendingSelectedArchiveSlug = null;
        scheduleArchiveLoadWithTapeRules(slug);
        closeHistoryList();
        return;
      }
      event.preventDefault();
      if (chartHistoryList && chartHistoryList.classList.contains("hidden")) {
        showHistoryFiles();
        if (chartHistoryToggle) {
          chartHistoryToggle.classList.add("history-visible");
        }
      } else {
        hideHistoryFiles();
        if (chartHistoryToggle) {
          chartHistoryToggle.classList.remove("history-visible");
        }
      }
    });
  };

  const updateTimestampDisplay = (text) => {
    if (!timestampDisplay) {
      return;
    }
    timestampDisplay.textContent = text || "History";
  };

  const updateTimestampFromSelection = () => {
    const labels = getChartLabels();
    const length = Array.isArray(labels) ? labels.length : 0;
    const hasPinned = clampIndex(pinnedPointIndex, length) !== null;
    const hasHover = clampIndex(hoverPointIndex, length) !== null;
    const updateStepValue = (labelValue, idxHint = null) => {
      if (!chartStepValueEl) {
        return;
      }
      const raw = String(labelValue || "").trim();
      if (!raw) {
        chartStepValueEl.textContent = "Step Time";
        return;
      }

      const formatTimeFromParsed = (parsed, includeMinutes) => {
        if (!parsed) {
          return "";
        }
        const hour24 = Number(parsed.hour24);
        const minute = Number(parsed.minute);
        if (!Number.isFinite(hour24) || hour24 < 0 || hour24 > 23) {
          return "";
        }
        const ap = hour24 < 12 ? "AM" : "PM";
        let hour12 = hour24 % 12;
        if (hour12 === 0) {
          hour12 = 12;
        }
        if (!includeMinutes || !Number.isFinite(minute)) {
          return `${hour12} ${ap}`;
        }
        const mm = Math.max(0, Math.min(59, Math.floor(minute)));
        return `${hour12}:${String(mm).padStart(2, "0")} ${ap}`;
      };

      const resolveYear = () => {
        const yearMatch = raw.match(/\b(20\d{2})\b/);
        if (yearMatch) {
          const parsed = Number(yearMatch[1]);
          return Number.isFinite(parsed) ? parsed : null;
        }
        const currentSlug = currentArchiveSlug || dashboardData.generatedDateSlug || "";
        const d = parseSlugDateUtc(currentSlug);
        return d ? d.getUTCFullYear() : null;
      };

      const resolveHourText = () => {
        const includeMinutes = /:\s*\d{2}\b/.test(raw);
        const parsed = parseLabelTime(raw);
        if (parsed) {
          return formatTimeFromParsed(parsed, includeMinutes);
        }
        const hour24 = roundedUpHour24FromLabel(raw);
        if (hour24 !== null) {
          return formatHourOnly(hour24);
        }
        const idxNumeric = Number(idxHint);
        if (Number.isFinite(idxNumeric)) {
          const hourFromIdx = Math.max(0, Math.min(23, Math.floor(idxNumeric)));
          return formatHourOnly(hourFromIdx);
        }
        return "";
      };

      const resolveDateParts = () => {
        const year = resolveYear();

        // Prefer explicit YYYY-MM-DD.
        const iso = raw.match(/\b(20\d{2})-(\d{2})-(\d{2})\b/);
        if (iso) {
          const mm = Number(iso[2]);
          const dd = Number(iso[3]);
          const monthName =
            Number.isFinite(mm) && mm >= 1 && mm <= 12 ? MONTH_LABELS_SHORT[mm - 1].toUpperCase() : "";
          const dayText = Number.isFinite(dd) ? String(dd).padStart(2, "0") : "";
          const yearText = String(iso[1]);
          return { monthName, dayText, yearText };
        }

        // Month name + day (optional weekday).
        const nameMatch = raw.match(
          /\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(20\d{2}))?\b/
        );
        if (nameMatch) {
          const monthName = String(nameMatch[1] || "").slice(0, 3).toUpperCase();
          const dd = Number(nameMatch[2]);
          const dayText = Number.isFinite(dd) ? String(dd).padStart(2, "0") : "";
          const yearText = nameMatch[3] ? String(nameMatch[3]) : year ? String(year) : "";
          return { monthName, dayText, yearText };
        }

        // Numeric month/day.
        const mdMatch = raw.match(/\b(\d{1,2})[\/-](\d{1,2})\b/);
        if (mdMatch) {
          const mm = Number(mdMatch[1]);
          const dd = Number(mdMatch[2]);
          const monthName =
            Number.isFinite(mm) && mm >= 1 && mm <= 12 ? MONTH_LABELS_SHORT[mm - 1].toUpperCase() : "";
          const dayText = Number.isFinite(dd) ? String(dd).padStart(2, "0") : "";
          const yearText = year ? String(year) : "";
          return { monthName, dayText, yearText };
        }

        return null;
      };

      const hourText = resolveHourText();
      const dateParts = resolveDateParts();
      if (dateParts) {
        const monthLabel = (dateParts.monthName || "").trim();
        const dayLabel = (dateParts.dayText || "").trim();
        const segments = [];
        if (monthLabel) {
          segments.push(monthLabel);
        }
        if (dayLabel) {
          segments.push(dayLabel);
        }
        if (hourText) {
          segments.push(hourText);
        }
        if (segments.length) {
          chartStepValueEl.textContent = segments.join(" ");
          return;
        }
      }

      // Fall back to something readable if we can't parse date components.
      chartStepValueEl.textContent = hourText ? `${hourText}, ${raw}` : raw;
    };

    if (hasPinned || hasHover) {
      const idx = getSelectedIndex();
      const label = valueAt(labels, idx, null);
      if (label) {
        updateTimestampDisplay(String(label));
        updateStepValue(label, idx);
        if (tvHistoryHour) {
          const hour24 = roundedUpHour24FromLabel(label);
          tvHistoryHour.textContent = hour24 === null ? "" : formatHourOnly(hour24);
        }
        const hour24 = roundedUpHour24FromLabel(label);
        const timeText = hour24 === null ? "" : formatHourOnly(hour24);
        setTvStepReadout(tvStepMonthValue?.textContent || "", tvStepDayValue?.textContent || "", timeText);
        return;
      }
    }
    // No selection: show default (latest) timepoint for the step label.
    const defaultIdx = getDefaultSelectedIndex();
    updateStepValue(valueAt(labels, defaultIdx, ""), defaultIdx);
    const fallback =
      dashboardData.generatedTimestamp ||
      (currentArchiveSlug ? archiveLabelMap.get(currentArchiveSlug) : null) ||
      "History: current data";
    updateTimestampDisplay(fallback);
    if (tvHistoryHour) {
      tvHistoryHour.textContent = "";
    }
    setTvStepReadout(tvStepMonthValue?.textContent || "", tvStepDayValue?.textContent || "", "");
  };

  const formatHourLabel = (label) => {
    const text = String(label || "").trim();
    if (!text) {
      return "";
    }
    // Prefer explicit 12-hour timestamps.
    let match = text.match(/(\d{1,2})\s*:\s*(\d{2})\s*(AM|PM)\b/i);
    if (match) {
      const hh = Number(match[1]);
      const mm = match[2];
      const ap = match[3].toUpperCase();
      return `${hh}:${mm} ${ap}`;
    }
    match = text.match(/(\d{1,2})\s*(AM|PM)\b/i);
    if (match) {
      return `${Number(match[1])} ${match[2].toUpperCase()}`;
    }

    // Handle 24-hour timestamps like "2025-12-18 23:00" (or similar) by converting to 12-hour.
    match = text.match(/\b(\d{1,2})\s*:\s*(\d{2})\b/);
    if (match) {
      const hour24 = Number(match[1]);
      const minute = match[2];
      if (Number.isFinite(hour24) && hour24 >= 0 && hour24 <= 23) {
        const ap = hour24 < 12 ? "AM" : "PM";
        let hour12 = hour24 % 12;
        if (hour12 === 0) {
          hour12 = 12;
        }
        return `${hour12}:${minute} ${ap}`;
      }
    }
    return text;
  };

  function formatXAxisTimeLabel(label) {
    const text = String(label || "").trim();
    if (!text) {
      return "";
    }
    let match = text.match(/(\d{1,2})\s*:\s*(\d{2})\s*(AM|PM)\b/i);
    if (match) {
      const hh = Number(match[1]);
      const mm = match[2];
      const ap = match[3].toUpperCase();
      return `${hh}:${mm} ${ap}`;
    }
    match = text.match(/(\d{1,2})\s*(AM|PM)\b/i);
    if (match) {
      return `${Number(match[1])} ${match[2].toUpperCase()}`;
    }
    match = text.match(/\b(\d{1,2})\s*:\s*(\d{2})\b/);
    if (match) {
      const hour24 = Number(match[1]);
      const minute = match[2];
      if (Number.isFinite(hour24) && hour24 >= 0 && hour24 <= 23) {
        const ap = hour24 < 12 ? "AM" : "PM";
        let hour12 = hour24 % 12;
        if (hour12 === 0) {
          hour12 = 12;
        }
        return `${hour12}:${minute} ${ap}`;
      }
    }
    return text;
  }

  const parseLabelTime = (label) => {
    const text = String(label || "").trim();
    if (!text) {
      return null;
    }
    let match = text.match(/(\d{1,2})\s*:\s*(\d{2})\s*(AM|PM)\b/i);
    if (match) {
      const hour12 = Number(match[1]);
      const minute = Number(match[2]);
      const ap = match[3].toUpperCase();
      if (!Number.isFinite(hour12) || hour12 < 1 || hour12 > 12) {
        return null;
      }
      if (!Number.isFinite(minute) || minute < 0 || minute > 59) {
        return null;
      }
      const hour24 = (hour12 % 12) + (ap === "PM" ? 12 : 0);
      return { hour24, minute };
    }

    match = text.match(/\b(\d{1,2})\s*:\s*(\d{2})\b/);
    if (match) {
      const hour24 = Number(match[1]);
      const minute = Number(match[2]);
      if (!Number.isFinite(hour24) || hour24 < 0 || hour24 > 23) {
        return null;
      }
      if (!Number.isFinite(minute) || minute < 0 || minute > 59) {
        return null;
      }
      return { hour24, minute };
    }

    match = text.match(/(\d{1,2})\s*(AM|PM)\b/i);
    if (match) {
      const hour12 = Number(match[1]);
      const ap = match[2].toUpperCase();
      if (!Number.isFinite(hour12) || hour12 < 1 || hour12 > 12) {
        return null;
      }
      const hour24 = (hour12 % 12) + (ap === "PM" ? 12 : 0);
      return { hour24, minute: 0 };
    }
    return null;
  };

  const formatHourOnly = (hour24) => {
    const h = Number(hour24);
    if (!Number.isFinite(h)) {
      return "";
    }
    const ap = h < 12 ? "AM" : "PM";
    let hour12 = h % 12;
    if (hour12 === 0) {
      hour12 = 12;
    }
    return `${hour12} ${ap}`;
  };

  const roundedUpHour24FromLabel = (label) => {
    const parsed = parseLabelTime(label);
    if (!parsed) {
      return null;
    }
    const { hour24, minute } = parsed;
    if (!Number.isFinite(hour24) || !Number.isFinite(minute)) {
      return null;
    }
    // Round up to the hour for display/selection; clamp within the same day.
    if (minute > 0) {
      return Math.min(hour24 + 1, 23);
    }
    return hour24;
  };

  function loadUiState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (err) {
      return null;
    }
  }

  function saveUiState() {
    try {
      const labels = getChartLabels();
      const length = Array.isArray(labels) ? labels.length : 0;
      const pinned = clampIndex(pinnedPointIndex, length);
      const pinnedLabel = pinned !== null ? valueAt(labels, pinned, "") : "";
      const pinnedHour24 = pinnedLabel ? roundedUpHour24FromLabel(pinnedLabel) : null;
      const pinnedHour = pinnedHour24 === null ? "" : formatHourOnly(pinnedHour24);
      const modes = Array.from(enabledModes || []);
      const payload = {
        pinnedIndex: pinned,
        pinnedHour,
        modes,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch (err) {
      // ignore storage failures
    }
  }

  const ensureSelectionUi = () => {
    const controls =
      document.getElementById("chartcontrols") ||
      document.querySelector(".chart-controls");
    const existingSelectionIndicator = document.getElementById("selection-indicator");
    if (existingSelectionIndicator) {
      selectionIndicatorEl = existingSelectionIndicator;
    }
    if (!controls && !selectionIndicatorEl) {
      return;
    }
    const transportNav = document.getElementById("transport-nav");
    const appendControl = (el) => {
      if (controls) {
        controls.appendChild(el);
      }
    };
    const appendNavControl = (el) => {
      if (transportNav) {
        transportNav.appendChild(el);
      } else {
        appendControl(el);
      }
    };

    if (!selectionIndicatorEl) {
      selectionIndicatorEl = document.createElement("span");
      selectionIndicatorEl.id = "selection-indicator";
      selectionIndicatorEl.style.marginLeft = "10px";
      selectionIndicatorEl.style.fontSize = "14px";
      selectionIndicatorEl.style.opacity = "0.9";
      selectionIndicatorEl.style.userSelect = "none";
      selectionIndicatorEl.textContent = "";
      selectionIndicatorEl.title = "Hover the chart to preview a reading. Click to pin. Use Clear Pin to reset.";
      appendControl(selectionIndicatorEl);
    }

    if (!clearPinButtonEl) {
      clearPinButtonEl = document.createElement("button");
      clearPinButtonEl.id = "clear-pin";
      clearPinButtonEl.type = "button";
      clearPinButtonEl.className = "chart-control";
      clearPinButtonEl.textContent = "Clear Pin";
      clearPinButtonEl.style.marginLeft = "10px";
      clearPinButtonEl.style.display = "none";
      appendControl(clearPinButtonEl);
    }
    if (clearPinButtonEl && clearPinButtonEl.dataset.boundClick !== "1") {
      clearPinButtonEl.dataset.boundClick = "1";
      clearPinButtonEl.addEventListener("click", () => {
        setSelectedPoint(null, null, true);
        suppressHoverUntilLeave();
      });
    }

    // Hour picker removed (the old "Latest" control lived here).
    const existingHourPicker = document.getElementById("hour-picker");
    if (existingHourPicker) {
      existingHourPicker.remove();
    }
    hourPickerEl = null;

    if (!prevDayButtonEl) {
      prevDayButtonEl = document.createElement("button");
      prevDayButtonEl.id = "archive-prev";
      prevDayButtonEl.type = "button";
      prevDayButtonEl.className = "chart-control";
      prevDayButtonEl.textContent = "<<";
      prevDayButtonEl.style.marginLeft = "10px";
      prevDayButtonEl.title = "Previous day";
      const action = () => {
        if (transportStepMode === "month") {
          navigateArchiveByMonths(-1);
        } else {
          navigateArchiveByDays(-1);
        }
      };
      prevDayButtonEl.addEventListener("click", (event) => {
        const until = holdRepeatSuppressClickUntil.get(prevDayButtonEl) || 0;
        if (until > Date.now()) {
          event.preventDefault();
          return;
        }
        action();
      });
      bindHoldRepeat(prevDayButtonEl, action);
      prevDayButtonEl.style.marginLeft = "0";
      appendNavControl(prevDayButtonEl);
    }

    if (!nextDayButtonEl) {
      nextDayButtonEl = document.createElement("button");
      nextDayButtonEl.id = "archive-next";
      nextDayButtonEl.type = "button";
      nextDayButtonEl.className = "chart-control";
      nextDayButtonEl.textContent = ">>";
      nextDayButtonEl.style.marginLeft = "6px";
      nextDayButtonEl.title = "Next day";
      const action = () => {
        if (transportStepMode === "month") {
          navigateArchiveByMonths(1);
        } else {
          navigateArchiveByDays(1);
        }
      };
      nextDayButtonEl.addEventListener("click", (event) => {
        const until = holdRepeatSuppressClickUntil.get(nextDayButtonEl) || 0;
        if (until > Date.now()) {
          event.preventDefault();
          return;
        }
        action();
      });
      bindHoldRepeat(nextDayButtonEl, action);
      nextDayButtonEl.style.marginLeft = "0";
      appendNavControl(nextDayButtonEl);
    }

    syncArchiveNavButtons();
  };

  const syncStepButtons = () => {
    if (!chartStepPrevButton && !chartStepNextButton) {
      return;
    }
    const labels = getChartLabels();
    const length = Array.isArray(labels) ? labels.length : 0;
    const current = clampIndex(
      pinnedPointIndex !== null ? pinnedPointIndex : hoverPointIndex,
      length
    );
    const hasData = length > 0;

    const hasAdjacentDay = (delta) => {
      const slugs = getSortedArchiveSlugs();
      const idx = getCurrentArchiveIndex(slugs);
      if (idx < 0) {
        return false;
      }
      const nextIdx = idx + Number(delta || 0);
      return nextIdx >= 0 && nextIdx < slugs.length && Boolean(slugs[nextIdx]);
    };

    if (chartStepPrevButton) {
      // Keep enabled at the left edge if a previous day exists so we can "scroll" across days.
      const canStepPrevPoint = hasData && current !== null && current > 0;
      const canWrapPrevDay = hasData && current !== null && current <= 0 && hasAdjacentDay(-1);
      chartStepPrevButton.disabled = !(canStepPrevPoint || canWrapPrevDay);
    }
    if (chartStepNextButton) {
      // Keep enabled at the right edge if a next day exists so we can "scroll" across days.
      const canStepNextPoint = hasData && current !== null && current < length - 1;
      const canWrapNextDay = hasData && current !== null && current >= length - 1 && hasAdjacentDay(1);
      chartStepNextButton.disabled = !(canStepNextPoint || canWrapNextDay);
    }
  };

  const stepPinnedPoint = (delta) => {
    const labels = getChartLabels();
    const length = Array.isArray(labels) ? labels.length : 0;
    if (length <= 0) {
      return;
    }
    const base =
      clampIndex(pinnedPointIndex, length) ??
      clampIndex(hoverPointIndex, length) ??
      (length - 1);
    const desired = base + Number(delta || 0);
    if (desired < 0) {
      const moved = navigateArchiveByDaysWithPinnedIndex(-1, length - 1);
      if (moved) {
        suppressHoverUntilLeave();
      }
      return;
    }
    if (desired >= length) {
      const moved = navigateArchiveByDaysWithPinnedIndex(1, 0);
      if (moved) {
        suppressHoverUntilLeave();
      }
      return;
    }
    const next = Math.max(0, Math.min(length - 1, desired));
    setSelectedPoint(next, next, true);
    suppressHoverUntilLeave();
    syncStepButtons();
  };

  const syncHourPickerOptions = () => {
    ensureSelectionUi();
    if (!hourPickerEl) {
      return;
    }
    const labels = getChartLabels();
    if (!Array.isArray(labels) || labels.length === 0) {
      hourPickerEl.innerHTML = "";
      hourPickerEl.disabled = true;
      hourPickerEl.style.display = "none";
      return;
    }

    hourPickerEl.disabled = false;
    hourPickerEl.style.display = "";
    hourPickerEl.innerHTML = "";
    const lastLabel = labels[labels.length - 1];
    const lastHour24 = roundedUpHour24FromLabel(lastLabel);

    const byHour = new Map();
    labels.forEach((label, idx) => {
      const hour24 = roundedUpHour24FromLabel(label);
      if (hour24 === null) {
        return;
      }
      // Keep the latest point in that rounded-up hour.
      byHour.set(hour24, idx);
    });

    const defaultHour24 = (() => {
      if (lastHour24 !== null && byHour.has(lastHour24)) {
        return lastHour24;
      }
      for (let hour24 = 23; hour24 >= 0; hour24 -= 1) {
        if (byHour.has(hour24)) {
          return hour24;
        }
      }
      return 0;
    })();

    for (let hour24 = 0; hour24 <= 23; hour24 += 1) {
      const opt = document.createElement("option");
      opt.value = `H${hour24}`;
      opt.textContent = formatHourOnly(hour24);
      if (!byHour.has(hour24)) {
        opt.disabled = true;
      }
      hourPickerEl.appendChild(opt);
    }

    const selectedPinned = clampIndex(pinnedPointIndex, labels.length);
    if (selectedPinned !== null) {
      const hour24 = roundedUpHour24FromLabel(labels[selectedPinned]);
      hourPickerEl.value =
        hour24 !== null && byHour.has(hour24) ? `H${hour24}` : `H${defaultHour24}`;
    } else {
      hourPickerEl.value = `H${defaultHour24}`;
    }

    // Match the orange selection accents when no pin is set.
    hourPickerEl.style.color = selectedPinned === null ? "#ffb347" : "#f4f6ff";
    syncArchiveNavButtons();
  };

  const updateSelectionIndicator = () => {
    ensureSelectionUi();
    if (!selectionIndicatorEl) {
      return;
    }

    const labels = getChartLabels();
    const length = Array.isArray(labels) ? labels.length : 0;
    const pinned = clampIndex(pinnedPointIndex, length);
    const hovered = clampIndex(hoverPointIndex, length);

    if (clearPinButtonEl) {
      clearPinButtonEl.style.display = pinned !== null ? "inline-flex" : "none";
      clearPinButtonEl.disabled = pinned === null;
      clearPinButtonEl.classList.toggle("active", pinned !== null);
    }

    if (pinned !== null) {
      const label = valueAt(labels, pinned, "");
      selectionIndicatorEl.textContent = `Pinned: ${formatHourLabel(label)}`;
      selectionIndicatorEl.style.color = "#ffb347";
      syncStepButtons();
      return;
    }
    if (hovered !== null) {
      const label = valueAt(labels, hovered, "");
      selectionIndicatorEl.textContent = `Hover: ${formatHourLabel(label)}`;
      selectionIndicatorEl.style.color = "#ffb347";
      syncStepButtons();
      return;
    }
    selectionIndicatorEl.textContent = "";
    selectionIndicatorEl.style.color = "";
    syncStepButtons();
    syncHourPickerOptions();
  };

  const updateCondenserRuntimeSummary = () => {
    const panel = document.querySelector(".condenser-runtime");
    if (!panel) {
      return;
    }
    const valueEl = panel.querySelector(".value");
    const costEl = panel.querySelector(".cost-value");

    const perHour = getCondenserMinutes();
    const computedMinutes = Array.isArray(perHour)
      ? perHour.reduce((acc, v) => acc + (Number.isFinite(Number(v)) ? Number(v) : 0), 0)
      : 0;
    const storedMinutesValueRaw = getTotalCondenserMinutesValue();
    const storedMinutesValue = Number(storedMinutesValueRaw);
    const minutesValue = Number.isFinite(storedMinutesValue) ? storedMinutesValue : computedMinutes;

    const storedMinutesDisplay = String(getTotalCondenserMinutesDisplay() || "").trim();
    const minutesDisplay =
      storedMinutesDisplay ||
      (Number.isFinite(minutesValue) ? String(Math.round(minutesValue)) : "0");

    if (valueEl) {
      valueEl.textContent = `${minutesDisplay} min`;
    }

    const storedCostDisplay = String(getTotalCondenserCostDisplay() || "").trim();
    const storedCostValueRaw = getTotalCondenserCostValue();
    const storedCostValue = Number(storedCostValueRaw);
    const costPerMinute = Number(getCondenserCostPerMinute()) || 0.05;
    const costValue = Number.isFinite(storedCostValue) ? storedCostValue : minutesValue * costPerMinute;
    const costDisplay = storedCostDisplay || `$${costValue.toFixed(2)}`;

    if (costEl) {
      costEl.textContent = costDisplay;
      costEl.classList.remove("cost-ok", "cost-warm", "cost-hot", "cost-red");
      if (costValue < 5) {
        costEl.classList.add("cost-ok");
      } else if (costValue < 10) {
        costEl.classList.add("cost-warm");
      } else if (costValue < 15) {
        costEl.classList.add("cost-hot");
      } else {
        costEl.classList.add("cost-red");
      }
    }
  };

  const archiveExistenceCache = new Map();
  let archiveExistenceValidationRunning = false;

  const fetchArchiveExists = async (slug) => {
    if (!slug) {
      return false;
    }
    if (archiveExistenceCache.has(slug)) {
      return archiveExistenceCache.get(slug);
    }
    const url = buildArchiveJsonUrl(slug);
    if (!url) {
      archiveExistenceCache.set(slug, false);
      return false;
    }
    try {
      // Prefer HEAD, fall back to GET if not supported.
      const headResp = await fetch(url, { method: "HEAD", cache: "no-store" });
      if (headResp.ok) {
        archiveExistenceCache.set(slug, true);
        return true;
      }
      if (headResp.status !== 405 && headResp.status !== 404) {
        // For non-OK responses that aren't "method not allowed" or "not found",
        // fall back to GET to confirm.
      }
    } catch (err) {
      // If HEAD fails (file:// or CORS issues), try GET.
    }
    try {
      const getResp = await fetch(url, { cache: "no-store" });
      const ok = Boolean(getResp && getResp.ok);
      archiveExistenceCache.set(slug, ok);
      return ok;
    } catch (err) {
      // Unknown network state: do not remove the entry, but mark as "unknown".
      // Returning true prevents the UI from hiding the date when we can't verify.
      archiveExistenceCache.set(slug, true);
      return true;
    }
  };

  const pruneMissingArchives = async () => {
    if (archiveExistenceValidationRunning || !dashboardData) {
      return;
    }
    const archiveDates = getArchiveDates();
    if (!Array.isArray(archiveDates) || archiveDates.length === 0) {
      return;
    }
    const slugs = archiveDates.map((e) => e?.slug).filter(Boolean);
    if (slugs.length === 0) {
      return;
    }
    archiveExistenceValidationRunning = true;
    try {
      const results = await Promise.all(slugs.map((slug) => fetchArchiveExists(slug)));
      const existsSet = new Set(slugs.filter((slug, idx) => results[idx]));
      const filtered = archiveDates.filter((entry) => !entry?.slug || existsSet.has(entry.slug));
      if (filtered.length !== archiveDates.length) {
        // Mutate in-memory data only; next render will no longer show missing entries.
        dashboardData.archiveDates = filtered;
        renderArchiveList();
      }
    } finally {
      archiveExistenceValidationRunning = false;
    }
  };

  function renderArchiveList() {
    const archiveDates = getArchiveDates();
    archiveLabelMap.clear();
    if (Array.isArray(archiveDates)) {
      archiveDates.forEach((entry) => {
        const label = entry?.label || entry?.slug || "Unknown";
        const slug = entry?.slug || "";
        if (slug) {
          archiveLabelMap.set(slug, label);
        }
      });
    }

    if (!chartHistoryList) {
      return;
    }
    hideHistoryFiles();
    chartHistoryList.innerHTML = "";
    const monthGroups = new Map();
    const monthLabels = new Map();
    (Array.isArray(archiveDates) ? archiveDates : []).forEach((entry) => {
      const label = entry.label || entry.slug || "Unknown";
      const slug = entry.slug || "";
      const monthKey = getMonthKeyFromSlug(slug) || getMonthKeyFromLabel(label);
      const monthLabel = getMonthLabel(monthKey);
      if (!monthGroups.has(monthKey)) {
        monthGroups.set(monthKey, []);
        monthLabels.set(monthKey, monthLabel);
      }
      monthGroups.get(monthKey).push({ label, slug });
    });

    // Ensure month picker + row exists.
    if (chartHistory && !chartHistoryListsRow) {
      chartHistoryListsRow = document.createElement("div");
      chartHistoryListsRow.className = "history-lists-row";
      chartHistoryMonthPicker = document.createElement("div");
      chartHistoryMonthPicker.className = "history-months";
      const monthHeader = document.createElement("h5");
      monthHeader.textContent = "Months";
      chartHistoryMonthList = document.createElement("ul");
      chartHistoryMonthList.className = "history-months-list";
      chartHistoryMonthList.id = "chart-history-months";
      chartHistoryMonthPicker.appendChild(monthHeader);
      chartHistoryMonthPicker.appendChild(chartHistoryMonthList);
      chartHistoryListColumn = document.createElement("div");
      chartHistoryListColumn.className = "history-list-column";
      chartHistoryListColumn.appendChild(chartHistoryList);
      chartHistoryListsRow.appendChild(chartHistoryMonthPicker);
      chartHistoryListsRow.appendChild(chartHistoryListColumn);
      chartHistory.appendChild(chartHistoryListsRow);

      // Click-to-expand behavior: start collapsed, expand when interacting with months/files.
      chartHistoryMonthPicker.addEventListener("click", () => showHistoryFiles());
      chartHistoryListColumn.addEventListener("click", () => showHistoryFiles());
      setHistoryExpanded(false);
    }

    // Render month picker
    const monthListEl = chartHistoryMonthList;
    const monthKeys = Array.from(monthGroups.keys()).sort().reverse();
    const limitedMonthKeys = monthKeys.slice(0, 12);
    if (monthListEl) {
      monthListEl.innerHTML = "";
      limitedMonthKeys.forEach((key) => {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = monthLabels.get(key) || key || "History";
        button.dataset.month = key;
        if (key === currentMonthKey) {
          button.classList.add("active");
        }
        button.addEventListener("click", () => {
          currentMonthKey = key;
          renderArchiveList();
          showHistoryFiles();
        });
        item.appendChild(button);
        monthListEl.appendChild(item);
      });
    }

    // Render entries for the current month only.
    if (!currentMonthKey && archiveDates.length) {
      const firstEntry = archiveDates[0];
      currentMonthKey =
        getMonthKeyFromSlug(firstEntry.slug) ||
        getMonthKeyFromLabel(firstEntry.label) ||
        "";
    }
    if (currentMonthKey && !limitedMonthKeys.includes(currentMonthKey)) {
      currentMonthKey = limitedMonthKeys[0] || currentMonthKey;
    }
    chartHistoryList.innerHTML = "";
    limitedMonthKeys.forEach((monthKey) => {
      const entries = monthGroups.get(monthKey);
      if (!entries || monthKey !== currentMonthKey) {
        return;
      }
      const monthItem = document.createElement("li");
      monthItem.className = "history-month";
      const header = document.createElement("div");
      header.className = "history-month-header";
      const monthButton = document.createElement("button");
      monthButton.type = "button";
      monthButton.textContent = monthLabels.get(monthKey) || "History";
      const list = document.createElement("ul");
      list.className = "history-month-list";
      entries.forEach((entry) => {
        const entryItem = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = entry.label;
        button.dataset.slug = entry.slug;
        button.addEventListener("click", (event) => {
          event.preventDefault();
          if (entry.slug) {
            pendingSelectedArchiveSlug = null;
            setActiveArchiveItem(entry.slug);
            closeHistoryList();
            // Let the history panel fully close before the tape animation starts.
            if (typeof requestAnimationFrame === "function") {
              requestAnimationFrame(() => scheduleArchiveLoadWithTapeRules(entry.slug));
            } else {
              setTimeout(() => scheduleArchiveLoadWithTapeRules(entry.slug), 0);
            }
            return;
          }
          closeHistoryList();
        });
        entryItem.appendChild(button);
        list.appendChild(entryItem);
      });
      monthButton.addEventListener("click", () => {
        list.classList.toggle("hidden");
      });
      header.appendChild(monthButton);
      monthItem.appendChild(header);
      monthItem.appendChild(list);
      chartHistoryList.appendChild(monthItem);
    });
    setActiveArchiveItem(currentArchiveSlug);

    // Ensure the history list reflects actual files on disk/server.
    // This prevents stale entries when a JSON file is deleted but still present in archiveDates.
    pruneMissingArchives();
  }

  function applyDashboardData(data, slugHint = null) {
    if (!data) {
      return;
    }
    dashboardData = data;
    pendingSelectedArchiveSlug = null;
    currentArchiveSlug = slugHint || data.generatedDateSlug || currentArchiveSlug;
    const labels = getChartLabels();
    const length = Array.isArray(labels) ? labels.length : 0;
    // Restore pinned selection from localStorage when available (prefer matching hour label).
    savedUiState = savedUiState || loadUiState();
    if (savedUiState && typeof savedUiState === "object") {
      const desiredHour = String(savedUiState.pinnedHour || "").trim().toLowerCase();
      if (desiredHour) {
        const matchIdx = labels.findIndex((lbl) => {
          const hour24 = roundedUpHour24FromLabel(lbl);
          if (hour24 === null) {
            return false;
          }
          return formatHourOnly(hour24).trim().toLowerCase() === desiredHour;
        });
        if (matchIdx >= 0) {
          pinnedPointIndex = matchIdx;
        }
      } else if (savedUiState.pinnedIndex !== null && savedUiState.pinnedIndex !== undefined) {
        pinnedPointIndex = savedUiState.pinnedIndex;
      }
    }
    pinnedPointIndex = clampIndex(pinnedPointIndex, length);
    hoverPointIndex = pinnedPointIndex;
    if (pendingPinnedIndexAfterArchiveLoad !== null) {
      pinnedPointIndex = clampIndex(pendingPinnedIndexAfterArchiveLoad, length);
      hoverPointIndex = pinnedPointIndex;
      pendingPinnedIndexAfterArchiveLoad = null;
      saveUiState();
    }
    const isArchiveLoad = Boolean(slugHint);
    renderArchiveList();
    updateHistoryStatus(currentArchiveSlug);
    syncArchiveNavButtons();
    updateTimestampFromSelection();
    updateSelectionIndicator();
    syncStepButtons();
    bindUsageSlotControls();
    bindChartSwapControls();
    renderUsageSlotChart();
    destroyChart();
    createChart();
    updateMetricCards();
    cardsInitialized = true;
    if (chart) {
      chart.options.plugins.legend.display = false;
      chart.update();
    }
    reapplyVisibility();
    showChart();
  }

  function getArchiveDates() {
    return getDashboardValue("archiveDates", []);
  }

  const updateAutoplayToggle = () => {
    if (!autoplayToggle) {
      return;
    }
    autoplayToggle.classList.toggle("active", autoplayEnabled);
    autoplayToggle.classList.toggle("off", !autoplayEnabled);
    autoplayToggle.textContent = autoplayEnabled ? "Auto-play: On" : "Auto-play: Off";
  };

  const bindAutoplayInteractions = () => {
    const interactiveEls = [
      chartArea,
      canvas,
      toggleHistoryBtn,
      chartHistory,
      ...Array.from(chartControlButtons || []),
    ].filter(Boolean);
    const events = ["mousemove", "touchstart", "click"];
    interactiveEls.forEach((el) => {
      events.forEach((evt) => {
        el.addEventListener(evt, markInteraction);
      });
    });
    if (autoplayToggle) {
      autoplayToggle.addEventListener("click", () => {
        autoplayEnabled = !autoplayEnabled;
        stopAutoplay();
        updateAutoplayToggle();
        if (autoplayEnabled) {
          startAutoplay(true);
        } else {
          ensureAutoplayScheduled();
        }
      });
    }
  };

  const getHelpChatState = () => {
    const labels = getChartLabels();
    const length = Array.isArray(labels) ? labels.length : 0;
    const pinned = clampIndex(pinnedPointIndex, length);
    const pinnedLabel = pinned !== null ? valueAt(labels, pinned, "") : "";
    const modes = typeof enabledModes !== "undefined" ? Array.from(enabledModes || []) : [];
    const archiveSlug = currentArchiveSlug || dashboardData.generatedDateSlug || "";
    const isTvMode = Boolean(document.body && document.body.classList.contains("tv-mode"));
    const chartsAreSwapped = Boolean(document.body && document.body.classList.contains("charts-swapped"));
    const historyVisible = Boolean(canvas && canvas.style.display !== "none");
    return {
      viewMode: isTvMode ? "tv" : "normal",
      chartsSwapped: chartsAreSwapped,
      historyChartVisible: historyVisible,
      archiveSlug,
      pinnedIndex: pinned,
      pinnedLabel,
      enabledModes: modes,
    };
  };

  const bindHelpChat = () => {
    if (!helpChatPanel || !helpChatToggle || !helpChatForm) {
      return;
    }
    if (helpChatPanel.dataset.bound === "1") {
      return;
    }
    helpChatPanel.dataset.bound = "1";

    helpChatToggle.addEventListener("click", () => {
      const isHidden = helpChatPanel.classList.contains("hidden");
      setHelpChatOpen(isHidden);
      if (isHidden && (!helpChatMessages || helpChatMessages.childElementCount === 0)) {
        appendHelpChatMessage(
          "assistant",
          "Ask me how to use the dashboard. I can only answer using the operator manual."
        );
      }
    });
    if (helpChatClose) {
      helpChatClose.addEventListener("click", () => setHelpChatOpen(false));
    }

    // Close on Escape when chat is open and focus is inside it.
    window.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") {
        return;
      }
      if (!helpChatPanel || helpChatPanel.classList.contains("hidden")) {
        return;
      }
      const active = document.activeElement;
      if (active && helpChatPanel.contains(active)) {
        event.preventDefault();
        setHelpChatOpen(false);
      }
    });

    helpChatForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (helpChatBusy) {
        return;
      }
      const question = String(helpChatInput?.value || "").trim();
      if (!question) {
        return;
      }
      if (helpChatInput) {
        helpChatInput.value = "";
      }
      appendHelpChatMessage("user", question);
      const placeholder = appendHelpChatMessage("assistant", "…");
      helpChatBusy = true;
      if (helpChatInput) helpChatInput.disabled = true;
      if (helpChatSend) helpChatSend.disabled = true;
      try {
        await loadHelpManual();
        const matched = keywordLookupHelp(question);
        const text = matched || HELP_CHAT_NO_MATCH;
        if (placeholder) {
          setHelpChatMessageContent(placeholder, "assistant", text);
        } else {
          appendHelpChatMessage("assistant", text);
        }
      } catch (err) {
        const manualUrlRaw = helpChatPanel?.dataset?.manualUrl || "dashboard_operator_manual.md";
        const manualUrl = new URL(manualUrlRaw, window.location.href).toString();
        const msg = `Help manual is not reachable (${manualUrl}). Ensure the manual file is hosted at that URL.`;
        if (placeholder) {
          setHelpChatMessageContent(placeholder, "assistant", msg);
        } else {
          appendHelpChatMessage("assistant", msg);
        }
      } finally {
        helpChatBusy = false;
        if (helpChatInput) helpChatInput.disabled = false;
        if (helpChatSend) helpChatSend.disabled = false;
        if (helpChatInput) helpChatInput.focus();
      }
    });
    if (helpChatClear) {
      helpChatClear.addEventListener("click", (event) => {
        event.preventDefault();
        clearHelpChatMessages();
      });
    }
    if (helpChatTagToggle) {
      helpChatTagToggle.addEventListener("change", syncTagToggle);
      syncTagToggle();
    }
  };

  if (chartControlButtons) {
    chartControlButtons.forEach((button) => {
      button.addEventListener("click", () => {
        toggleMode(button.dataset.mode);
      });
    });
  }

  if (toggleHistoryBtn) {
    toggleHistoryBtn.addEventListener("click", () => {
      if (!canvas || canvas.style.display === "none") {
        showChart();
      } else {
        hideChart();
      }
    });
  }

  if (!isChartHistoryUiHidden() && chartHistoryToggle && chartHistoryList) {
    chartHistoryToggle.addEventListener("click", () => {
      toggleHistoryList();
    });
  }

  applyDashboardData(dashboardData);
  bindTransportHistoryToggle();
  bindArchiveKeyboardShortcuts();
  bindTvControls();
  bindAutoplayInteractions();
  bindHelpChat();
  updateAutoplayToggle();
  ensureAutoplayScheduled();
})();
