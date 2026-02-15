(function () {
  const statusLine = document.getElementById("statusLine");
  const callerDisplay = document.getElementById("callerDisplay");
  const answerBtn = document.getElementById("answerBtn");
  const hangupBtn = document.getElementById("hangupBtn");

  if (!statusLine || !callerDisplay || !answerBtn || !hangupBtn) {
    throw new Error("FAIL-FAST: Missing required softphone DOM elements.");
  }

  const state = {
    device: null,
    incomingCall: null,
    activeCall: null,
    socket: null,
    ringAudioContext: null,
    ringInterval: null,
  };

  const postServerLog = (event, data) => {
    const stamp = new Date().toISOString();
    let payload = "";
    if (data !== undefined && data !== null) {
      try {
        payload = ` ${JSON.stringify(data)}`;
      } catch (_) {
        payload = ` ${String(data)}`;
      }
    }
    const line = `[SOFTPHONE_CLIENT ${stamp}] ${event}${payload}`;
    fetch("/cores/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: line }),
      keepalive: true,
    }).catch(() => {});
  };

  const log = (event, data) => {
    if (data === undefined) {
      console.log(`[softphone] ${event}`);
      postServerLog(event, null);
      return;
    }
    console.log(`[softphone] ${event}`, data);
    postServerLog(event, data);
  };

  const logDependencyStatus = () => {
    let twilioKeys = [];
    if (window.Twilio && typeof window.Twilio === "object") {
      try {
        twilioKeys = Object.keys(window.Twilio).slice(0, 12);
      } catch (_) {}
    }
    log("boot.dependencies", {
      hasTwilio: !!window.Twilio,
      twilioDeviceType: window.Twilio ? typeof window.Twilio.Device : "missing",
      hasSocketIo: !!window.io,
      socketIoType: typeof window.io,
      twilioKeys,
    });
  };

  const setStatus = (text, tone) => {
    statusLine.textContent = text;
    statusLine.classList.remove("warn", "active", "error");
    if (tone) {
      statusLine.classList.add(tone);
    }
    log("status.change", { text, tone: tone || "default" });
  };

  const setCaller = (value) => {
    callerDisplay.textContent = value;
  };

  const setControls = ({ canAnswer, canHangup }) => {
    answerBtn.disabled = !canAnswer;
    hangupBtn.disabled = !canHangup;
  };

  const stopRingTone = () => {
    if (state.ringInterval) {
      window.clearInterval(state.ringInterval);
      state.ringInterval = null;
    }
    if (state.ringAudioContext) {
      state.ringAudioContext.close().catch(() => {});
      state.ringAudioContext = null;
    }
  };

  const startRingTone = async () => {
    stopRingTone();
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) {
      log("ringtone.unavailable");
      return;
    }

    const ctx = new AudioContextCtor();
    if (ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch (_) {}
    }

    state.ringAudioContext = ctx;
    let oscillator = null;
    let ringing = false;

    state.ringInterval = window.setInterval(() => {
      if (!state.ringAudioContext) {
        return;
      }
      if (!ringing) {
        oscillator = state.ringAudioContext.createOscillator();
        const gain = state.ringAudioContext.createGain();
        oscillator.type = "sine";
        oscillator.frequency.value = 880;
        gain.gain.value = 0.06;
        oscillator.connect(gain);
        gain.connect(state.ringAudioContext.destination);
        oscillator.start();
        ringing = true;
        return;
      }
      if (oscillator) {
        oscillator.stop();
        oscillator.disconnect();
        oscillator = null;
      }
      ringing = false;
    }, 450);
  };

  const resetCallState = () => {
    stopRingTone();
    state.incomingCall = null;
    state.activeCall = null;
    setCaller("No active caller");
    setControls({ canAnswer: false, canHangup: false });
    setStatus("Waiting");
  };

  const connectWebSocket = () => {
    if (!window.io) {
      log("ws.unavailable", {
        reason: "Socket.IO client script missing. Continuing without websocket telemetry.",
      });
      return;
    }

    state.socket = window.io("/softphone-ws", {
      transports: ["websocket"],
      reconnection: true,
    });

    state.socket.on("connect", () => {
      log("ws.connected", { id: state.socket.id });
      setStatus("Connected");
    });

    state.socket.on("disconnect", (reason) => {
      log("ws.disconnected", { reason });
      setStatus("Waiting", "warn");
    });
    state.socket.on("connect_error", (error) => {
      log("ws.connect_error", { message: error && error.message ? error.message : String(error) });
    });

    state.socket.on("server_status", (payload) => {
      log("ws.server_status", payload);
    });
  };

  const bindCallLifecycle = (call) => {
    call.on("accept", () => {
      log("call.accept");
      stopRingTone();
      state.activeCall = call;
      state.incomingCall = null;
      setStatus("On Call", "active");
      setControls({ canAnswer: false, canHangup: true });
    });

    call.on("disconnect", () => {
      log("call.disconnect");
      resetCallState();
    });

    call.on("cancel", () => {
      log("call.cancel");
      resetCallState();
    });

    call.on("reject", () => {
      log("call.reject");
      resetCallState();
    });

    call.on("error", (error) => {
      log("call.error", { message: error && error.message ? error.message : String(error) });
      setStatus("Call Error", "error");
    });
  };

  const answerIncomingCall = async () => {
    if (!state.incomingCall) {
      throw new Error("FAIL-FAST: No incoming call is available to answer.");
    }
    setStatus("Connecting", "warn");
    state.incomingCall.accept();
  };

  const hangupCall = () => {
    if (state.activeCall) {
      state.activeCall.disconnect();
      return;
    }
    if (state.incomingCall) {
      state.incomingCall.reject();
      return;
    }
    if (state.device) {
      state.device.disconnectAll();
    }
    resetCallState();
  };

  const fetchToken = async () => {
    log("token.request.start");
    const response = await fetch("/token", { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    log("token.request.response", { status: response.status, ok: response.ok });
    if (!response.ok) {
      const error = payload && payload.error ? payload.error : `Token request failed (${response.status})`;
      log("token.request.error", { error });
      throw new Error(error);
    }
    const token = String(payload.token || "").trim();
    if (!token) {
      log("token.request.error", { error: "empty token" });
      throw new Error("FAIL-FAST: /token returned an empty token.");
    }
    log("token.request.success", { tokenLength: token.length });
    return token;
  };

  const initDevice = async () => {
    if (!window.Twilio || typeof window.Twilio.Device !== "function") {
      const hasTwilio = !!window.Twilio;
      const deviceType = window.Twilio ? typeof window.Twilio.Device : "missing";
      throw new Error(
        `FAIL-FAST: Twilio Voice SDK Device API unavailable (hasTwilio=${hasTwilio}, deviceType=${deviceType}).`
      );
    }

    const token = await fetchToken();
    log("device.init.start");
    const device = new window.Twilio.Device(token, {
      codecPreferences: ["opus", "pcmu"],
      logLevel: 1,
    });
    state.device = device;

    device.on("registered", () => {
      log("device.registered");
      setStatus("Waiting");
    });

    device.on("unregistered", () => {
      log("device.unregistered");
      setStatus("Waiting", "warn");
    });

    device.on("error", (error) => {
      log("device.error", { message: error && error.message ? error.message : String(error) });
      setStatus("Device Error", "error");
    });

    device.on("incoming", async (call) => {
      log("call.incoming", call && call.parameters ? call.parameters : {});
      state.incomingCall = call;
      const from = call && call.parameters && call.parameters.From ? call.parameters.From : "Unknown Caller";
      setCaller(from);
      setStatus("Incoming Call", "warn");
      setControls({ canAnswer: true, canHangup: true });
      bindCallLifecycle(call);
      await startRingTone();
    });

    setStatus("Connected", "active");
    await device.register();
    log("device.register.requested");
  };

  const boot = async () => {
    try {
      logDependencyStatus();
      setStatus("Connected", "active");
      setControls({ canAnswer: false, canHangup: false });
      connectWebSocket();
      await initDevice();
      log("softphone.ready");
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      log("boot.failed", { message });
      setStatus(message, "error");
      setControls({ canAnswer: false, canHangup: false });
      throw error;
    }
  };

  answerBtn.addEventListener("click", () => {
    log("ui.answer.click");
    answerIncomingCall().catch((error) => {
      const message = error && error.message ? error.message : String(error);
      setStatus(message, "error");
      console.error(error);
    });
  });

  hangupBtn.addEventListener("click", () => {
    log("ui.hangup.click");
    try {
      hangupCall();
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      setStatus(message, "error");
      console.error(error);
    }
  });

  window.addEventListener("error", (evt) => {
    log("window.error", {
      message: String(evt.message || ""),
      source: String(evt.filename || ""),
      line: Number(evt.lineno || 0),
      column: Number(evt.colno || 0),
    });
  });

  window.addEventListener("unhandledrejection", (evt) => {
    log("window.unhandledrejection", {
      reason: String((evt.reason && evt.reason.message) || evt.reason || ""),
    });
  });

  boot().catch(() => {});
})();
