// Frontend helpers for the ShantyCircuit (SC) YuE2 ABC nodes.
//  - Shows each node's summary text in a read-only box on the node.
//  - When a run starts, clears the boxes and resets the search node's color;
//    if ComfyUI reuses a node's cached result instead of running it, its
//    previous text and color are put back.
//  - SC YuE2 ABC Length Search: shows live progress while searching, colors the
//    node green (found) or red (not found), sets the seed box after each run,
//    can pick a new random seed every time the workflow is queued, and has a
//    "new search" button for a fresh random seed.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const SEARCH_NODE = "SC_YuE2ABCLengthSearch";
const NODE_IDS = new Set(["SC_YuE2ABCSongLength", "SC_YuE2ABCSpeedChange", "SC_YuE2ABCFixMeter", SEARCH_NODE]);
const LIVE_EVENT = "shantycircuit.yue2_abc.progress";
const SUMMARY = "summary";
const NEW_SEARCH = "new search (random seed)";

// Size of each node's text box. The search node's box can also grow with the
// node; the others stay fixed and scroll if there's more text than fits.
const SEARCH_BOX_HEIGHT = 110;  // about six lines
const BOX_LINES = { SC_YuE2ABCSongLength: 4, SC_YuE2ABCSpeedChange: 3, SC_YuE2ABCFixMeter: 3 };
const LINE_HEIGHT = 18;
const BOX_PADDING = 8;

// Default width of newly added nodes. Nodes loaded from a saved workflow keep
// their saved size, and any node can still be resized by hand.
const NODE_WIDTHS = { SC_YuE2ABCSongLength: 260, SC_YuE2ABCFixMeter: 260, SC_YuE2ABCSpeedChange: 260 };

function applyDefaultWidth(node) {
  const width = NODE_WIDTHS[node.constructor.comfyClass];
  if (width) node.setSize([width, node.size[1]]);
}

function fixedBoxHeight(node) {
  const lines = BOX_LINES[node.comfyClass] ?? BOX_LINES[node.type] ?? 2;
  return lines * LINE_HEIGHT + BOX_PADDING;
}

const FOUND_COLORS = { color: "#2f5a2f", bgcolor: "#1f3a1f" };
const NOT_FOUND_COLORS = { color: "#6a2f2f", bgcolor: "#432020" };

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function isHelper(node) {
  return NODE_IDS.has(node?.comfyClass) || NODE_IDS.has(node?.type);
}

function isSearch(node) {
  return node?.comfyClass === SEARCH_NODE || node?.type === SEARCH_NODE;
}

function allNodes() {
  const graph = app.graph;
  return graph?.nodes ?? graph?._nodes ?? [];
}

function nodeById(id) {
  if (id === null || id === undefined) return null;
  const graph = app.graph;
  return graph?.getNodeById?.(id) ?? graph?.getNodeById?.(Number(id)) ?? null;
}

function firstValue(value) {
  return Array.isArray(value) ? value[0] : value;
}

function textFrom(message) {
  // UI text normally arrives as message.text (a list of strings).
  let text = message?.text;
  if (text === undefined && message) {
    text = Object.values(message).find(
      (v) => typeof v === "string" || (Array.isArray(v) && v.every((x) => typeof x === "string"))
    );
  }
  if (Array.isArray(text)) text = text.join("\n");
  return text ? String(text) : "";
}

function redraw() {
  app.graph?.setDirtyCanvas?.(true, true);
}

// ---------------------------------------------------------------------------
// The summary box
// ---------------------------------------------------------------------------

function displayOnly(widget) {
  // Never saved into the workflow or sent to the backend, so the node's real
  // widget values keep their positions.
  widget.serialize = false;
  if (widget.options) widget.options.serialize = false;
  widget.serializeValue = () => undefined;
}

function makeScrollable(el) {
  el.readOnly = true;
  el.style.opacity = 0.75;
  el.style.overflowY = "auto";
  el.style.overflowX = "auto";
  el.style.whiteSpace = "pre";  // one log line per row, no wrapping
  // Normally the mouse wheel over a node zooms the canvas. When the box has
  // more text than fits, let the wheel scroll the box instead.
  el.addEventListener("wheel", (event) => {
    const scrollable = el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth;
    if (scrollable && !event.ctrlKey) event.stopImmediatePropagation();
  }, { capture: true, passive: true });
  // Dragging the scrollbar or selecting text shouldn't drag the node around.
  el.addEventListener("pointerdown", (event) => event.stopPropagation());
}

function summaryWidget(node, create) {
  let widget = node.widgets?.find((w) => w.name === SUMMARY);
  if (widget || !create) return widget;

  widget = ComfyWidgets["STRING"](node, SUMMARY, ["STRING", { multiline: true }], app).widget;
  displayOnly(widget);
  const height = isSearch(node) ? SEARCH_BOX_HEIGHT : fixedBoxHeight(node);
  if (widget.options) {
    widget.options.getMinHeight = () => height;
    if (!isSearch(node)) widget.options.getMaxHeight = () => height;  // fixed size; scrolls
  }
  if (widget.inputEl) makeScrollable(widget.inputEl);

  // Fit the node's height to its new contents once, when the box first appears
  // (the width stays as it is).
  requestAnimationFrame(() => {
    const size = node.computeSize();
    node.setSize([node.size[0], size[1]]);
    redraw();
  });
  return widget;
}

function setSummary(node, text) {
  const widget = summaryWidget(node, Boolean(text));
  if (!widget) return;
  widget.value = text;
  if (widget.inputEl) {
    widget.inputEl.value = text;
    widget.inputEl.scrollTop = 0;
  }
  redraw();
}

function getSummary(node) {
  return summaryWidget(node, false)?.value ?? "";
}

// ---------------------------------------------------------------------------
// Result colors (search node)
// ---------------------------------------------------------------------------

function rememberOriginalColors(node) {
  // Stored in the node's properties so it survives saving and reloading.
  node.properties = node.properties || {};
  if (node.properties.abcColorSaved) return;
  node.properties.abcColorSaved = true;
  node.properties.abcOriginalColor = node.color ?? null;
  node.properties.abcOriginalBgcolor = node.bgcolor ?? null;
}

function showResult(node, found) {
  rememberOriginalColors(node);
  const colors = found ? FOUND_COLORS : NOT_FOUND_COLORS;
  node.color = colors.color;
  node.bgcolor = colors.bgcolor;
  redraw();
}

function hasResultColor(node) {
  return [FOUND_COLORS, NOT_FOUND_COLORS].some(
    (c) => node.color === c.color && node.bgcolor === c.bgcolor
  );
}

function setColors(node, color, bgcolor) {
  // Assign rather than delete: in current ComfyUI versions a node's color can be
  // a built-in property that ignores `delete`. Assigning undefined = no custom color.
  node.color = color ?? undefined;
  node.bgcolor = bgcolor ?? undefined;
}

function resetColor(node) {
  const props = node.properties || {};
  // Also reset if the node still shows a result color but lost the saved original
  // (for example, a workflow saved by an older version of this script).
  if (!props.abcColorSaved && !hasResultColor(node)) return;
  if (props.abcColorSaved) setColors(node, props.abcOriginalColor, props.abcOriginalBgcolor);
  else setColors(node, undefined, undefined);
  delete props.abcColorSaved;
  delete props.abcOriginalColor;
  delete props.abcOriginalBgcolor;
  redraw();
}

// ---------------------------------------------------------------------------
// Seed box (search node)
// ---------------------------------------------------------------------------

function setSeed(node, seed) {
  const widget = node.widgets?.find((w) => w.name === "seed");
  if (!widget || !Number.isSafeInteger(seed) || widget.value === seed) return;
  widget.value = seed;
  widget.callback?.(seed);
  redraw();
}

function randomSeed() {
  return Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);
}

// ---------------------------------------------------------------------------
// Run lifecycle: clear on start, put back if a cached result is reused
// ---------------------------------------------------------------------------

const before = new Map();  // node -> state captured when the run started
let runningNodeId = null;

function snapshot(node) {
  const props = node.properties || {};
  return {
    text: getSummary(node),
    color: node.color,
    bgcolor: node.bgcolor,
    colorProps: props.abcColorSaved
      ? { abcColorSaved: true, abcOriginalColor: props.abcOriginalColor, abcOriginalBgcolor: props.abcOriginalBgcolor }
      : null,
  };
}

function restore(node, state) {
  setSummary(node, state.text);
  setColors(node, state.color, state.bgcolor);
  node.properties = node.properties || {};
  if (state.colorProps) Object.assign(node.properties, state.colorProps);
  redraw();
}

function onRunStart() {
  before.clear();
  runningNodeId = null;
  for (const node of allNodes()) {
    if (!isHelper(node)) continue;
    before.set(node, snapshot(node));
    setSummary(node, "");
    if (isSearch(node)) resetColor(node);
  }
}

function onCached(ids) {
  for (const id of ids || []) {
    const node = nodeById(id);
    const state = node && before.get(node);
    if (state) {
      restore(node, state);
      before.delete(node);
    }
  }
}

function onRunEnd(stopped) {
  // Nodes that neither ran nor were cached weren't part of this run.
  for (const [node, state] of before) {
    if (stopped && String(node.id) === String(runningNodeId)) {
      setSummary(node, "Stopped before finishing.");
    } else {
      restore(node, state);
    }
  }
  before.clear();
  runningNodeId = null;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

app.registerExtension({
  name: "ShantyCircuit.YuE2ABC.ShowSummary",

  setup() {
    api.addEventListener("execution_start", onRunStart);
    api.addEventListener("execution_cached", ({ detail }) => onCached(detail?.nodes));
    api.addEventListener("executing", ({ detail }) => {
      let id = detail;
      if (detail && typeof detail === "object") id = detail.display_node ?? detail.node;
      if (id !== null && id !== undefined) runningNodeId = id;
    });
    api.addEventListener("execution_success", () => onRunEnd(false));
    api.addEventListener("execution_error", () => onRunEnd(true));
    api.addEventListener("execution_interrupted", () => onRunEnd(true));

    // Live progress from the search node while it runs. The first message also
    // resets the color, in case the run-start event was missed.
    api.addEventListener(LIVE_EVENT, ({ detail }) => {
      const node = nodeById(detail?.node);
      if (!node || !isHelper(node)) return;
      if (isSearch(node)) resetColor(node);
      setSummary(node, String(detail.text ?? ""));
    });
  },

  // Runs right after a node is built. Nodes loaded from a workflow get their
  // saved size applied afterwards, so this only shows on newly added nodes.
  nodeCreated(node) {
    applyDefaultWidth(node);
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!NODE_IDS.has(nodeData.name)) return;

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      before.delete(this);  // it ran, so its new result stays
      const text = textFrom(message);
      if (text) setSummary(this, text);
      if (nodeData.name === SEARCH_NODE) {
        const found = firstValue(message?.found);
        if (found !== undefined) showResult(this, Boolean(found));
        const seed = firstValue(message?.next_seed ?? message?.seed_used);
        if (seed !== undefined) setSeed(this, Number(seed));
      }
    };

    if (nodeData.name === SEARCH_NODE) {
      const onNodeCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        onNodeCreated?.apply(this, arguments);
        const node = this;

        const button = this.addWidget("button", NEW_SEARCH, null, () => setSeed(node, randomSeed()));
        displayOnly(button);

        // "new_seed_each_run": pick a random seed just before the workflow is queued.
        const seedWidget = this.widgets?.find((w) => w.name === "seed");
        if (seedWidget) {
          const beforeQueued = seedWidget.beforeQueued;
          seedWidget.beforeQueued = function () {
            beforeQueued?.apply(this, arguments);
            const toggle = node.widgets?.find((w) => w.name === "new_seed_each_run");
            if (toggle?.value) setSeed(node, randomSeed());
          };
        }
      };
    }
  },
});
