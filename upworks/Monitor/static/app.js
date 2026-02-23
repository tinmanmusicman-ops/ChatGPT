"use strict";

const NODE_WIDTH = 48;
const NODE_HEIGHT = 48;
const NODE_TOP_OFFSET = 70;
const EDGE_PULSE_MS = 900;
const EVENT_LIMIT = 500;

const nodeLayer = document.getElementById("node-layer");
const edgeLayer = document.getElementById("edge-layer");
const eventBox = document.getElementById("events");
const connectionState = document.getElementById("connection-state");
const lastEvent = document.getElementById("last-event");
const graphScroll = document.getElementById("graph-scroll");

let graph = null;
let nodeById = new Map();
let nodeElementById = new Map();
let incomingEdgesByNode = new Map();
let outgoingEdgesByNode = new Map();
let edgeElements = [];

function setConnection(label, klass) {
  connectionState.className = "chip " + klass;
  connectionState.textContent = label;
}

function setLastEvent(text) {
  lastEvent.textContent = text;
}

function addEventLine(text, kind) {
  const line = document.createElement("div");
  line.className = "event-line " + kind;
  line.textContent = text;
  eventBox.prepend(line);
  while (eventBox.childElementCount > EVENT_LIMIT) {
    eventBox.removeChild(eventBox.lastChild);
  }
}

function buildGraph(data) {
  graph = data;
  nodeById = new Map(data.nodes.map((n) => [n.id, n]));
  incomingEdgesByNode = new Map();
  outgoingEdgesByNode = new Map();
  edgeElements = [];
  nodeElementById = new Map();
  nodeLayer.innerHTML = "";
  edgeLayer.innerHTML = "";

  const maxX = Math.max(...data.nodes.map((n) => n.x)) + NODE_WIDTH + 120;
  const maxY = Math.max(...data.nodes.map((n) => n.y)) + NODE_HEIGHT + NODE_TOP_OFFSET + 120;
  edgeLayer.setAttribute("width", String(maxX));
  edgeLayer.setAttribute("height", String(maxY));
  edgeLayer.setAttribute("viewBox", `0 0 ${maxX} ${maxY}`);
  nodeLayer.style.width = `${maxX}px`;
  nodeLayer.style.height = `${maxY}px`;
  graphScroll.scrollLeft = 0;
  graphScroll.scrollTop = 0;

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const markerDot = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  markerDot.setAttribute("id", "edge-dot");
  markerDot.setAttribute("viewBox", "0 0 6 6");
  markerDot.setAttribute("refX", "3");
  markerDot.setAttribute("refY", "3");
  markerDot.setAttribute("markerUnits", "strokeWidth");
  markerDot.setAttribute("markerWidth", "4");
  markerDot.setAttribute("markerHeight", "4");
  markerDot.setAttribute("orient", "auto");
  const markerDotCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  markerDotCircle.setAttribute("cx", "3");
  markerDotCircle.setAttribute("cy", "3");
  markerDotCircle.setAttribute("r", "2");
  markerDotCircle.setAttribute("fill", "#8fa5c4");
  markerDot.appendChild(markerDotCircle);
  defs.appendChild(markerDot);
  edgeLayer.appendChild(defs);

  for (const edge of data.edges) {
    const src = nodeById.get(edge.source);
    const dst = nodeById.get(edge.target);
    if (!src || !dst) {
      continue;
    }
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.classList.add("edge");
    line.dataset.source = edge.source;
    line.dataset.target = edge.target;
    line.setAttribute("x1", String(src.x + NODE_WIDTH / 2));
    line.setAttribute("y1", String(src.y + NODE_TOP_OFFSET + NODE_HEIGHT / 2));
    line.setAttribute("x2", String(dst.x + NODE_WIDTH / 2));
    line.setAttribute("y2", String(dst.y + NODE_TOP_OFFSET + NODE_HEIGHT / 2));
    line.setAttribute("marker-start", "url(#edge-dot)");
    line.setAttribute("marker-end", "url(#edge-dot)");
    edgeLayer.appendChild(line);
    edgeElements.push(line);

    if (!incomingEdgesByNode.has(edge.target)) {
      incomingEdgesByNode.set(edge.target, []);
    }
    if (!outgoingEdgesByNode.has(edge.source)) {
      outgoingEdgesByNode.set(edge.source, []);
    }
    incomingEdgesByNode.get(edge.target).push(line);
    outgoingEdgesByNode.get(edge.source).push(line);
  }

  for (const node of data.nodes) {
    const el = document.createElement("div");
    el.className = "node status-idle";
    el.dataset.nodeId = node.id;
    el.style.left = `${node.x}px`;
    el.style.top = `${node.y + NODE_TOP_OFFSET}px`;
    el.dataset.label = node.label;
    nodeLayer.appendChild(el);
    nodeElementById.set(node.id, el);
  }
}

function setNodeStatus(nodeId, statusName) {
  const el = nodeElementById.get(nodeId);
  if (!el) {
    return;
  }
  el.classList.remove("status-idle", "status-running", "status-success", "status-error");
  el.classList.add(`status-${statusName}`);
}

function pulseEdges(lines) {
  if (!lines || lines.length === 0) {
    return;
  }
  for (const line of lines) {
    line.classList.add("active");
  }
  window.setTimeout(() => {
    for (const line of lines) {
      line.classList.remove("active");
    }
  }, EDGE_PULSE_MS);
}

function resetPipelineNodes() {
  if (!graph || !Array.isArray(graph.pipeline_reset_nodes)) {
    return;
  }
  for (const nodeId of graph.pipeline_reset_nodes) {
    setNodeStatus(nodeId, "idle");
  }
}

function statusSummary(event) {
  const msg = event.message ? ` ${event.message}` : "";
  return `${event.ts} ${event.source} ${event.status}${msg}`;
}

function consumeEvent(event, fromHistory = false) {
  if (!event || !event.kind) {
    return;
  }

  if (event.kind === "status") {
    addEventLine(statusSummary(event), "status");
    if (!fromHistory && event.node_id) {
      if (event.source === "Function LeadVettingPipeline.run_single_row" && event.status === "start") {
        resetPipelineNodes();
      }
      if (event.status === "start") {
        setNodeStatus(event.node_id, "running");
        pulseEdges(incomingEdgesByNode.get(event.node_id));
      } else if (event.status === "ok") {
        setNodeStatus(event.node_id, "success");
        pulseEdges(outgoingEdgesByNode.get(event.node_id));
      } else if (event.status === "error") {
        setNodeStatus(event.node_id, "error");
        pulseEdges(incomingEdgesByNode.get(event.node_id));
      } else if (event.status === "info") {
        const el = nodeElementById.get(event.node_id);
        if (el && el.classList.contains("status-idle")) {
          setNodeStatus(event.node_id, "success");
          pulseEdges(outgoingEdgesByNode.get(event.node_id));
        }
      }
    }
    if (!fromHistory) {
      setLastEvent(statusSummary(event));
    }
    return;
  }

  if (event.kind === "payload_pair") {
    addEventLine(`${event.key}=${event.value}`, "payload_pair");
    if (!fromHistory) {
      if (event.source === "LeadVettingPipeline.sheet_update_payload" && event.key === "status") {
        if (String(event.value).toUpperCase().includes("COMPLETE")) {
          setNodeStatus("complete", "success");
        }
        if (String(event.value).toUpperCase().includes("ERROR")) {
          setNodeStatus("error", "error");
        }
      }
      if (event.source === "LeadVettingPipeline.sheet_update_result" && event.key === "updated_keys") {
        setNodeStatus("complete", "success");
      }
    }
    if (!fromHistory) {
      setLastEvent(`${event.key}=...`);
    }
    return;
  }

  if (event.raw_line) {
    addEventLine(event.raw_line, "text");
    if (!fromHistory) {
      setLastEvent(event.raw_line);
    }
  }
}

async function loadGraphAndHistory() {
  const graphResponse = await fetch("/graph", { cache: "no-store" });
  const graphJson = await graphResponse.json();
  buildGraph(graphJson);

  const historyResponse = await fetch("/history", { cache: "no-store" });
  const historyJson = await historyResponse.json();
  if (Array.isArray(historyJson.events)) {
    for (const event of historyJson.events) {
      consumeEvent(event, true);
    }
  }
}

function connectEvents() {
  const source = new EventSource("/events");
  source.onopen = () => {
    setConnection("connected", "chip-ok");
  };
  source.onerror = () => {
    setConnection("reconnecting", "chip-warn");
  };
  source.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      consumeEvent(event, false);
    } catch (_err) {
      addEventLine(msg.data, "text");
    }
  };
}

async function boot() {
  setConnection("connecting", "chip-warn");
  try {
    await loadGraphAndHistory();
    connectEvents();
  } catch (err) {
    setConnection("error", "chip-error");
    setLastEvent("failed to load monitor UI");
    addEventLine(String(err), "text");
  }
}

boot();
