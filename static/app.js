/* MiniLang Playground.
   The page never compiles anything itself: Run POSTs the editor text to /run,
   and this file only renders the JSON that app.py sends back. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ helpers

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  /** Build a DOM element. Text is always set via textContent, never innerHTML. */
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "dataset") Object.assign(node.dataset, value);
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }

  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  const pad4 = (n) => String(n).padStart(4, "0");
  const fmt = (n) => Number(n).toLocaleString();
  const plural = (n, word, many = word + "s") => `${fmt(n)} ${n === 1 ? word : many}`;
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

  const STAGE_LABEL = {
    lex: "Lexer error",
    parse: "Parse error",
    semantic: "Semantic error",
    type: "Type error",
    compile: "Compile error",
    runtime: "Runtime error",
    input: "Input error",
    network: "Can't reach the server",
    server: "Server error",
  };

  const FLOW_OPS = new Set(["JUMP", "JUMP_IF_FALSE", "CALL", "TAIL_CALL", "RET", "HALT"]);
  const MATH_OPS = new Set(["ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "EQ", "NE", "LT", "GT", "LE", "GE", "NOT"]);

  /** A VM value as MiniLang prints it: 5, or [1, [2, 3]] for lists. */
  const showValue = (v) => (Array.isArray(v) ? `[${v.map(showValue).join(", ")}]` : String(v));
  const TARGET_OPS = new Set(["JUMP", "JUMP_IF_FALSE", "CALL", "TAIL_CALL"]);

  // ------------------------------------------------------------------- editor

  const editor = createEditor($("#source"));

  function createEditor(textarea) {
    if (!window.CodeMirror || !CodeMirror.defineSimpleMode) return createFallbackEditor(textarea);

    CodeMirror.defineSimpleMode("minilang", {
      start: [
        { regex: /#.*/, token: "comment" },
        { regex: /(func)(\s+)([A-Za-z_]\w*)/, token: ["keyword", null, "def"] },
        { regex: /(?:if|else|while|for|break|continue|return|print|input|func|and|or|not)\b/, token: "keyword" },
        { regex: /\d+/, token: "number" },
        { regex: /[A-Za-z_]\w*(?=\s*\()/, token: "variable-2" },
        { regex: /[A-Za-z_]\w*/, token: "variable" },
        { regex: /==|!=|<=|>=|[-+*/%]=|[-+*/%<>=]/, token: "operator" },
        { regex: /[{}()[\]]/, token: "bracket" },
      ],
      meta: { lineComment: "#" },
    });

    const cm = CodeMirror.fromTextArea(textarea, {
      mode: "minilang",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      matchBrackets: true,
      styleActiveLine: true,
      autofocus: true,
      gutters: ["lint-gutter", "CodeMirror-linenumbers"],
      extraKeys: {
        Tab: (c) => c.execCommand(c.somethingSelected() ? "indentMore" : "insertSoftTab"),
        "Shift-Tab": "indentLess",
      },
    });

    const marks = {}; // kind -> { handle, cls }
    const validLine = (line) => Number.isInteger(line) && line >= 1 && line <= cm.lineCount();
    let problemMarks = []; // squiggles from live checking

    return {
      getValue: () => cm.getValue(),
      setValue(text) {
        cm.setValue(text);
        cm.clearHistory();
        cm.setCursor({ line: 0, ch: 0 });
      },
      onChange: (fn) => cm.on("changes", fn),
      onCursor: (fn) => cm.on("cursorActivity", () => {
        const c = cm.getCursor();
        fn(c.line + 1, c.ch + 1);
      }),
      mark(kind, line, cls) {
        if (marks[kind] && marks[kind].line === line) return;
        this.unmark(kind);
        if (!validLine(line)) return;
        const handle = cm.addLineClass(line - 1, "background", cls);
        cm.addLineClass(handle, "gutter", `${cls}-gutter`);
        marks[kind] = { handle, cls, line };
      },
      unmark(kind) {
        const m = marks[kind];
        if (!m) return;
        cm.removeLineClass(m.handle, "background", m.cls);
        cm.removeLineClass(m.handle, "gutter", `${m.cls}-gutter`);
        delete marks[kind];
      },
      /** Live-check results: a wavy underline and a gutter dot per line, the messages as a tooltip. */
      setProblems(problems) {
        cm.operation(() => {
          problemMarks.forEach((m) => m.clear());
          problemMarks = [];
          cm.clearGutter("lint-gutter");
          const byLine = new Map();
          for (const p of problems) {
            if (!validLine(p.line)) continue;
            const entry = byLine.get(p.line) || { severity: "warning", messages: [] };
            if (p.severity === "error") entry.severity = "error";
            entry.messages.push(p.message);
            byLine.set(p.line, entry);
          }
          for (const [line, { severity, messages }] of byLine) {
            const text = cm.getLine(line - 1);
            const start = text.search(/\S/);
            const title = messages.join("\n");
            if (start >= 0) {
              problemMarks.push(cm.markText({ line: line - 1, ch: start }, { line: line - 1, ch: text.trimEnd().length },
                { className: `cm-problem-${severity}`, attributes: { title } }));
            }
            const dot = document.createElement("span");
            dot.className = `lint-dot is-${severity}`;
            dot.title = title;
            cm.setGutterMarker(line - 1, "lint-gutter", dot);
          }
        });
      },
      reveal(line) {
        if (validLine(line)) cm.scrollIntoView({ line: line - 1, ch: 0 }, 80);
      },
      goTo(line) {
        if (!validLine(line)) return;
        cm.focus();
        cm.setCursor({ line: line - 1, ch: 0 });
        cm.scrollIntoView({ line: line - 1, ch: 0 }, 80);
      },
      refresh: () => cm.refresh(),
    };
  }

  /** Plain textarea editor, used only if the CodeMirror CDN can't be loaded. */
  function createFallbackEditor(textarea) {
    textarea.classList.add("editor-fallback");
    const lineStart = (line) => textarea.value.split("\n").slice(0, line - 1).join("\n").length + (line > 1 ? 1 : 0);
    return {
      getValue: () => textarea.value,
      setValue(text) { textarea.value = text; },
      onChange: (fn) => textarea.addEventListener("input", fn),
      onCursor: (fn) => {
        const report = () => {
          const before = textarea.value.slice(0, textarea.selectionStart).split("\n");
          fn(before.length, before[before.length - 1].length + 1);
        };
        ["keyup", "click", "input"].forEach((ev) => textarea.addEventListener(ev, report));
      },
      mark() {},
      unmark() {},
      setProblems() {},
      reveal() {},
      goTo(line) {
        const pos = lineStart(line);
        textarea.focus();
        textarea.setSelectionRange(pos, pos);
      },
      refresh() {},
    };
  }

  // -------------------------------------------------------------------- state

  const state = {
    result: null,     // last JSON from /run
    step: 0,          // index into result.trace
    tab: "output",
    astView: "graph",   // AST tab: "graph" (diagram), "tree" (collapsible list) or "text"
    bcView: "optimized",
    irView: "tac",      // IR tab: "tac" or "optimized" (after constant propagation)
    stale: false,     // editor changed since the last run
    dirty: false,     // editor differs from the loaded example
    running: false,
    runContext: null, // extra fields for /run, e.g. {level: "c1"} while playing a level
  };

  // Tiny event hub so game.js can react to runs without touching this file's internals.
  const listeners = {};
  function emit(type, detail) {
    for (const fn of listeners[type] || []) {
      try { fn(detail); } catch (err) { console.error(err); }
    }
  }

  const examples = JSON.parse($("#examples-data").textContent);

  // Keyboard hint text
  const shortcut = isMac ? "⌘ ↵" : "Ctrl ↵";
  $("#run-kbd").textContent = shortcut;
  $("#empty-kbd").textContent = shortcut;
  $("#run").title = `Run (${isMac ? "⌘" : "Ctrl"}+Enter)`;

  // --------------------------------------------------------------------- tabs

  const TABS = ["level", "tokens", "ast", "symbols", "ir", "bytecode", "output"]; // "level" is only shown while playing

  function selectTab(name, { focus = false } = {}) {
    state.tab = name;
    for (const t of TABS) {
      const tab = $(`#tab-${t}`);
      const on = t === name;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      $(`#panel-${t}`).hidden = !on;
    }
    if (focus) $(`#tab-${name}`).focus();
    if (name !== "ast") leaveAstFullscreen();
    applyStepHighlight();
    if (name === "bytecode") scrollCurrentInstructionIntoView();
    if (name === "ir") drawIrEdges();
    emit("tab", name);
  }

  for (const t of TABS) {
    $(`#tab-${t}`).addEventListener("click", () => selectTab(t));
  }
  $(".tabs").addEventListener("keydown", (e) => {
    const visible = TABS.filter((t) => !$(`#tab-${t}`).hidden);
    const i = visible.indexOf(state.tab);
    let next = null;
    if (e.key === "ArrowRight") next = visible[(i + 1) % visible.length];
    else if (e.key === "ArrowLeft") next = visible[(i - 1 + visible.length) % visible.length];
    else if (e.key === "Home") next = visible[0];
    else if (e.key === "End") next = visible[visible.length - 1];
    if (next) {
      e.preventDefault();
      selectTab(next, { focus: true });
    }
  });

  // ---------------------------------------------------------------------- run

  async function run() {
    if (state.running) return;
    state.running = true;
    const button = $("#run");
    button.disabled = true;
    button.classList.add("is-busy");
    $(".btn-run-label", button).textContent = "Running…";
    setStatus("Running…", "busy");

    const started = performance.now();
    let result;
    try {
      const response = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.runContext
          ? { ...state.runContext, source: editor.getValue() }   // a level brings its own input
          : { source: editor.getValue(), stdin: $("#stdin").value }),
      });
      let body = null;
      try { body = await response.json(); } catch { /* not JSON */ }
      if (response.ok && body && "ok" in body) {
        result = body;
      } else {
        const message = (body && body.error) || `The server answered with HTTP ${response.status}.`;
        result = failedRequest("server", message);
      }
    } catch {
      result = failedRequest("network", "The page couldn't reach app.py. Check that the server is still running in your terminal, then press Run again.");
    }
    const elapsed = performance.now() - started;

    state.running = false;
    button.disabled = false;
    button.classList.remove("is-busy");
    $(".btn-run-label", button).textContent = "Run";
    showResult(result, elapsed);
  }

  function failedRequest(stage, message) {
    return {
      ok: false, tokens: null, ast: null, ast_dump: null, bytecode: null,
      bytecode_unoptimized: null, optimizer: {}, output: [], trace: null,
      trace_truncated: false, error: { stage, message, line: null }, errors: [{ stage, message, line: null }],
    };
  }

  $("#run").addEventListener("click", run);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey) emit("check-shortcut");
      else run();
    }
  });

  function showResult(result, elapsed) {
    state.result = result;
    state.stale = false;
    $("#stale-note").hidden = true;

    const trace = result.trace || [];
    // After a runtime error, open the stepper on the last good state (like Python Tutor).
    state.step = result.error && result.error.stage === "runtime" ? Math.max(0, trace.length - 1) : 0;

    editor.unmark("hover");
    editor.unmark("step");
    markErrors(allErrors(result));
    markWarnings(result.warnings);

    renderTokens();
    renderAst();
    renderSymbols();
    renderIr();
    renderBytecode();
    renderOutput();
    updateBadges();
    updateStatus(elapsed);

    if (result.error || state.tab === "level") selectTab("output"); // errors are always shown in Output
    applyStepHighlight();
    emit("result", { result, context: state.runContext, source: editor.getValue() });
  }

  // Snapshot the panels' first-run content so results can be cleared later.
  const pristine = {};
  for (const id of ["tokens-body", "ast-body", "symbols-body", "ir-body", "bytecode-body"]) pristine[id] = $(`#${id}`).cloneNode(true);

  /** Forget the last run and show every panel's empty state again. */
  function clearResults() {
    state.result = null;
    state.step = 0;
    state.stale = false;
    // Swap the children, not the containers, so their event listeners survive.
    for (const [id, node] of Object.entries(pristine)) $(`#${id}`).replaceChildren(...node.cloneNode(true).childNodes);
    $("#ast-toolbar").hidden = true;
    $("#ast-body").classList.remove("is-graph");
    $("#ast-graph-hint").hidden = true;
    $("#ast-minimap").hidden = true;
    graph.result = null;
    graph.svg = null;
    graph.mini = null;
    $("#bytecode-toolbar").hidden = true;
    $("#ir-toolbar").hidden = true;
    $("#output-empty").hidden = false;
    $("#output-result").hidden = true;
    $("#stale-note").hidden = true;
    for (const t of ["tokens", "ast", "symbols", "ir", "bytecode", "output"]) $(`#badge-${t}`).hidden = true;
    unmarkWarnings();
    editor.unmark("hover");
    editor.unmark("step");
    unmarkErrors();
    setStatus("Ready", null);
    $("#status-meta").textContent = "";
  }

  // ------------------------------------------------------------------ status

  function setStatus(text, kind) {
    const status = $("#status");
    status.textContent = text;
    status.className = `status${kind ? ` is-${kind}` : ""}`;
  }

  function updateStatus(elapsed) {
    const r = state.result;
    const ms = `${Math.max(1, Math.round(elapsed))} ms`;
    if (r.error) {
      const count = allErrors(r).length;
      const where = r.error.line ? ` on line ${r.error.line}` : "";
      setStatus(count > 1 ? `${count} ${(STAGE_LABEL[r.error.stage] || "Error").toLowerCase()}s, the first${where}`
        : `${STAGE_LABEL[r.error.stage] || "Error"}${where}`, "error");
    } else {
      setStatus(`Ran in ${ms}`, "ok");
    }
    const bits = [];
    if (r.bytecode) {
      const { before, after } = r.optimizer || {};
      bits.push(before && before !== after
        ? `${plural(after, "instruction")} (${fmt(before)} before optimizing)`
        : plural(r.bytecode.length, "instruction"));
    }
    if (r.warnings && r.warnings.length) bits.push(plural(r.warnings.length, "warning"));
    if (r.steps) bits.push(`${fmt(r.steps)} VM steps`);
    if (r.output && r.output.length) bits.push(`${plural(r.output.length, "line")} printed`);
    $("#status-meta").textContent = bits.join("  ·  ");
  }

  function updateBadges() {
    const r = state.result;
    const set = (id, text, isError = false, isWarning = false) => {
      const badge = $(`#badge-${id}`);
      badge.hidden = text === null;
      badge.textContent = text ?? "";
      badge.classList.toggle("is-error", isError);
      badge.classList.toggle("is-warning", isWarning);
    };
    set("tokens", r.tokens ? fmt(r.tokens.length) : null);
    set("ast", null);
    const warningCount = (r.warnings || []).length;
    set("symbols", warningCount ? `${warningCount} ⚠` : r.symbols ? "✓" : null, false, warningCount > 0);
    set("ir", r.ir ? fmt(r.ir.stats.blocks) : null);
    set("bytecode", r.bytecode ? fmt(r.bytecode.length) : null);
    if (r.error) set("output", "!", true);
    else set("output", r.output.length ? fmt(r.output.length) : null);
    $("#badge-output").setAttribute("aria-label", r.error ? "error" : `${r.output.length} lines`);
  }

  // ---------------------------------------------- shared: blocked-stage state

  /** Shown in a panel whose stage never ran because an earlier stage failed. */
  function blocked(stageName) {
    const err = state.result.error || {};
    const label = STAGE_LABEL[err.stage] || "An error";
    const where = err.line ? ` on line ${err.line}` : "";
    const reason = err.stage === "network" || err.stage === "server"
      ? "The request didn't complete, so there's nothing to show."
      : `${label}${where} stopped the pipeline before this stage.`;
    return el("div", { class: "empty is-blocked" },
      el("p", { class: "empty-title" }, `No ${stageName} for this run`),
      el("p", { class: "empty-text" }, reason),
      el("button", { class: "btn-link", type: "button", onclick: () => selectTab("output", { focus: true }) }, "See the error in Output"));
  }

  // ------------------------------------------------------------------ tokens

  function renderTokens() {
    const body = $("#tokens-body");
    const r = state.result;
    body.replaceChildren();
    if (!r.tokens) return body.append(blocked("tokens"));

    const lastLine = r.tokens.length ? r.tokens[r.tokens.length - 1].line : 0;
    const rows = r.tokens.map((tok, i) =>
      el("tr", { dataset: { line: tok.line } },
        el("td", { class: "num" }, i),
        el("td", { class: "num" }, tok.line),
        el("td", { class: "col-type" }, el("span", { class: `tok-type tok-${tok.type.toLowerCase()}` }, tok.type)),
        el("td", { class: "tok-value" },
          tok.type === "EOF" ? el("span", { class: "muted" }, "end of file") : String(tok.value))));

    body.append(
      el("p", { class: "panel-summary" }, `${plural(r.tokens.length, "token")} across ${plural(lastLine, "line")}. Hover a row to find it in the source.`),
      el("table", { class: "data-table" },
        el("thead", null, el("tr", null,
          el("th", { class: "num", scope: "col" }, "#"),
          el("th", { class: "num", scope: "col" }, "Line"),
          el("th", { class: "col-type", scope: "col" }, "Type"),
          el("th", { scope: "col" }, "Value"))),
        el("tbody", null, rows)));
  }

  // --------------------------------------------------------------------- AST

  const isNode = (v) => v !== null && typeof v === "object" && !Array.isArray(v) && typeof v.type === "string";
  const isNodeList = (v) => Array.isArray(v) && v.length > 0 && v.every(isNode);

  function formatValue(v) {
    if (v === null || v === undefined) return "none";
    if (typeof v === "string") return JSON.stringify(v);
    if (Array.isArray(v)) return `[${v.map(formatValue).join(", ")}]`;
    return String(v);
  }

  function astItem(node) {
    const fields = Object.keys(node).filter((k) => k !== "type" && k !== "line");
    const simple = fields.filter((k) => !isNode(node[k]) && !isNodeList(node[k]));
    const nested = fields.filter((k) => isNode(node[k]) || isNodeList(node[k]));

    const item = el("li", { class: "ast-item" });
    const toggle = nested.length
      ? el("button", {
          class: "ast-toggle", type: "button", "aria-expanded": "true", "aria-label": `Collapse ${node.type}`,
          onclick: () => setCollapsed(item, !item.classList.contains("is-collapsed")),
        })
      : el("span", { class: "ast-toggle-spacer", "aria-hidden": "true" });

    item.append(el("div", { class: "ast-row", dataset: { line: node.line ?? "" } },
      toggle,
      el("span", { class: "ast-type" }, node.type),
      simple.map((k) => {
        const v = node[k];
        const kind = v === null ? "null" : typeof v;
        return el("span", { class: "ast-prop" },
          el("span", { class: "ast-key" }, k),
          el("span", { class: `ast-val ast-val-${kind}` }, formatValue(v)));
      }),
      node.line != null ? el("span", { class: "ast-line" }, `line ${node.line}`) : null));

    if (nested.length) {
      item.append(el("ul", { class: "ast-children" },
        nested.map((k) => {
          const v = node[k];
          const kids = Array.isArray(v) ? v : [v];
          return el("li", null,
            el("div", { class: "ast-field-name" }, k, Array.isArray(v) ? el("span", { class: "ast-count" }, ` (${v.length})`) : null),
            el("ul", { class: "ast-kids" }, kids.map(astItem)));
        })));
    }
    return item;
  }

  function setCollapsed(item, collapsed) {
    item.classList.toggle("is-collapsed", collapsed);
    const toggle = $(":scope > .ast-row > .ast-toggle", item);
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(!collapsed));
      toggle.setAttribute("aria-label", `${collapsed ? "Expand" : "Collapse"} ${$(".ast-type", item).textContent}`);
    }
  }

  function renderAst() {
    const body = $("#ast-body");
    const r = state.result;
    if (body.classList.contains("is-graph")) graph.scroll = { left: body.scrollLeft, top: body.scrollTop };
    body.classList.remove("is-graph");
    body.replaceChildren();
    graph.svg = null;
    graph.mini = null;
    const isGraph = state.astView === "graph" && !!r.ast;
    $("#ast-toolbar").hidden = !r.ast;
    $("#ast-graph-hint").hidden = !isGraph;
    $("#ast-minimap").hidden = true;
    if (!r.ast) return body.append(blocked("syntax tree"));

    for (const seg of $$("[data-ast-view]")) seg.setAttribute("aria-pressed", String(seg.dataset.astView === state.astView));
    $("#ast-tree-actions").hidden = state.astView === "text";
    $("#ast-graph-actions").hidden = !isGraph;

    if (isGraph) {
      renderAstGraph(body, r);
    } else if (state.astView === "text") {
      body.append(el("pre", { class: "ast-text" }, r.ast_dump));
    } else {
      body.append(el("ul", { class: "ast-tree", "aria-label": "Abstract syntax tree" }, astItem(r.ast)));
    }
  }

  for (const seg of $$("[data-ast-view]")) {
    seg.addEventListener("click", () => {
      if (seg.dataset.astView !== "graph") leaveAstFullscreen();
      state.astView = seg.dataset.astView;
      renderAst();
    });
  }
  $("#ast-expand").addEventListener("click", () => {
    if (state.astView === "graph") return foldGraph(() => false);
    $$("#ast-body .ast-item").forEach((item) => setCollapsed(item, false));
  });
  $("#ast-collapse").addEventListener("click", () => {
    // Keep the Program root open so every top-level statement stays visible.
    if (state.astView === "graph") return foldGraph((g) => g.path !== "");
    $$("#ast-body .ast-item").forEach((item, i) => {
      if (i > 0 && $(":scope > .ast-row > .ast-toggle", item)) setCollapsed(item, true);
    });
  });

  // ------------------------------------------------------------- AST: graph

  /* The Graph view draws the syntax tree as a diagram: a box per node and a line to each child,
     labelled with the field the child fills (left, right, condition, then_body…). Statement lists
     (Program and Block) hang their statements left to right in source order, each in its own
     column; everywhere else a child subtree may tuck in beside its neighbour, which keeps
     expressions compact. The diagram can be zoomed, dragged around, folded node by node and
     shown full screen. */

  const AST_KIND = {
    BinOp: "op", LogicalOp: "op", UnaryOp: "op",
    Call: "call", Index: "call", ArrayLit: "call",
    Number: "num", Var: "var",
  };
  const SEQUENCE_NODES = new Set(["Program", "Block"]);
  const AG = {
    nodeH: 40, rowGap: 46, padX: 11, minW: 48, gap: 14, seqGap: 28, margin: 28,
    minZoom: 0.15, maxZoom: 2, maxFit: 1.25, readable: 0.55, bigTreeZoom: 0.85, detailMax: 18,
  };

  const graph = {
    result: null,          // the run the measured tree belongs to
    tree: null,
    collapsed: new Set(),  // paths of folded nodes
    zoom: 1,
    mode: "auto",          // "auto": pick the zoom for the panel; "fit": fit the whole tree; "manual"
    pending: true,         // still needs its first zoom (the panel was hidden when it was drawn)
    scroll: null,          // scroll position kept while the Tree or Text view is shown
    W: 0, H: 0,
    svg: null,
    visible: [],
    mini: null,
  };
  const astBody = $("#ast-body");

  /** What a node's box shows under its type: the operator, name or value it holds. */
  function graphDetail(node) {
    if (node.type === "FuncDef") return `${node.name}(${(node.params || []).join(", ")})`;
    const bits = [];
    for (const [k, v] of Object.entries(node)) {
      if (k === "type" || k === "line" || v === null || v === undefined || isNode(v) || isNodeList(v)) continue;
      if (Array.isArray(v)) { if (v.length) bits.push(v.join(", ")); continue; }
      bits.push(String(v));
    }
    return bits.join(" ");
  }

  function buildGraphTree(node, path, edge) {
    const kids = [];
    for (const [k, v] of Object.entries(node)) {
      if (k === "type" || k === "line") continue;
      if (isNode(v)) kids.push(buildGraphTree(v, `${path}/${k}`, k));
      else if (isNodeList(v)) v.forEach((child, i) => kids.push(buildGraphTree(child, `${path}/${k}.${i}`, null)));
    }
    return {
      node, path, edge, kids, type: node.type, line: node.line,
      detail: graphDetail(node), kind: AST_KIND[node.type] || "stmt",
      size: 1 + kids.reduce((n, k) => n + k.size, 0),
    };
  }

  let measureCtx = null;
  function textWidth(text, font) {
    measureCtx = measureCtx || document.createElement("canvas").getContext("2d");
    measureCtx.font = font;
    return measureCtx.measureText(text).width;
  }

  /** Box widths, from the same fonts the CSS gives the SVG text. */
  function measureGraphTree(g, mono) {
    g.shown = g.detail.length > AG.detailMax ? `${g.detail.slice(0, AG.detailMax - 1)}…` : g.detail;
    const typeW = textWidth(g.type, g.shown ? `500 11px ${mono}` : `600 12px ${mono}`);
    const detailW = g.shown ? textWidth(g.shown, `600 13px ${mono}`) : 0;
    g.w = Math.max(AG.minW, Math.ceil(Math.max(typeW, detailW)) + 2 * AG.padX);
    g.labelW = g.edge ? Math.ceil(textWidth(g.edge, `400 10px ${mono}`)) + 10 : 0;
    g.kids.forEach((k) => measureGraphTree(k, mono));
  }

  /**
   * Lay out a subtree with its root at x = 0, returning its contour: the [left, right] extent of
   * each level below the root. Siblings are pushed apart until their contours clear at every level.
   */
  function layoutGraphTree(g) {
    g.open = g.kids.length > 0 && !graph.collapsed.has(g.path);
    const half = Math.max(g.w, g.labelW) / 2;   // the edge label above a node needs room too
    if (!g.open) {
      g.kidX = [];
      return [[-half, half]];
    }
    const seq = SEQUENCE_NODES.has(g.type);
    const contours = g.kids.map(layoutGraphTree);
    const offsets = [0];
    const acc = contours[0].map(([l, r]) => [l, r]);
    for (let i = 1; i < contours.length; i++) {
      const c = contours[i];
      let shift = -Infinity;
      if (seq) {   // statements keep a column each, in source order
        shift = Math.max(...acc.map(([, r]) => r)) - Math.min(...c.map(([l]) => l)) + AG.seqGap;
      } else {
        for (let d = 0; d < Math.min(acc.length, c.length); d++) shift = Math.max(shift, acc[d][1] - c[d][0] + AG.gap);
      }
      offsets.push(shift);
      c.forEach(([l, r], d) => {
        if (d < acc.length) {
          acc[d][0] = Math.min(acc[d][0], l + shift);
          acc[d][1] = Math.max(acc[d][1], r + shift);
        } else {
          acc.push([l + shift, r + shift]);
        }
      });
    }
    // A statement list sits above its first statement; any other node is centred over its children.
    const anchor = seq ? 0 : (offsets[0] + offsets[offsets.length - 1]) / 2;
    g.kidX = offsets.map((o) => o - anchor);
    return [[-half, half], ...acc.map(([l, r]) => [l - anchor, r - anchor])];
  }

  function placeGraphTree(g, x, depth, out) {
    g.x = x;
    g.y = depth * (AG.nodeH + AG.rowGap);
    out.push(g);
    if (g.open) g.kids.forEach((k, i) => placeGraphTree(k, x + g.kidX[i], depth + 1, out));
  }

  function layoutGraph() {
    layoutGraphTree(graph.tree);
    const visible = [];
    placeGraphTree(graph.tree, 0, 0, visible);
    let left = Infinity, right = -Infinity, bottom = 0;
    for (const g of visible) {
      const half = Math.max(g.w, g.labelW) / 2;
      left = Math.min(left, g.x - half);
      right = Math.max(right, g.x + half);
      bottom = Math.max(bottom, g.y + AG.nodeH);
    }
    for (const g of visible) {
      g.x = Math.round(g.x - left + AG.margin);
      g.y += AG.margin;
    }
    graph.visible = visible;
    graph.W = Math.ceil(right - left + 2 * AG.margin);
    graph.H = Math.ceil(bottom + 10 + 2 * AG.margin);   // + room for a fold button under the lowest row
  }

  function svgText(attrs, text) {
    const t = svg("text", attrs);
    t.textContent = text;
    return t;
  }

  function drawGraphEdges(g, edges, labels) {
    const bottom = g.y + AG.nodeH;
    const bus = bottom + 20;
    edges.append(svg("path", { class: "ag-edge", d: `M${g.x},${bottom + 7}V${bus}` }));
    for (const k of g.kids) {
      const dx = k.x - g.x;
      const r = Math.min(6, Math.abs(dx));
      edges.append(svg("path", {
        class: "ag-edge",
        d: dx === 0 ? `M${k.x},${bus}V${k.y}` : `M${g.x},${bus}H${k.x - Math.sign(dx) * r}Q${k.x},${bus} ${k.x},${bus + r}V${k.y}`,
      }));
      if (k.edge) {
        const label = svg("g", { class: "ag-label", transform: `translate(${k.x},${bus + (k.y - bus) / 2})` });
        label.append(svg("rect", { x: -k.labelW / 2, y: -7, width: k.labelW, height: 14, rx: 3 }), svgText({ y: 3.5, "text-anchor": "middle" }, k.edge));
        labels.append(label);
      }
    }
  }

  function drawGraphNode(g) {
    const folded = g.kids.length > 0 && !g.open;
    const group = svg("g", {
      class: `ag-node k-${g.kind}${g.path === "" ? " is-root" : ""}${folded ? " is-folded" : ""}`,
      transform: `translate(${g.x - g.w / 2},${g.y})`,
      "data-line": g.line ?? "",
      "data-path": g.path,
    });
    const title = svg("title");
    title.textContent = `${g.type}${g.detail ? ` ${g.detail}` : ""}${g.line != null ? ` · line ${g.line}` : ""}`;
    group.append(title);
    if (folded) group.append(svg("rect", { class: "ag-stack", x: 4, y: 4, width: g.w, height: AG.nodeH, rx: 5 }));
    group.append(svg("rect", { class: "ag-box", width: g.w, height: AG.nodeH, rx: 5 }));
    const mid = g.w / 2;
    if (g.shown) {
      group.append(svgText({ class: "ag-type", x: mid, y: 15, "text-anchor": "middle" }, g.type),
                   svgText({ class: "ag-detail", x: mid, y: 31.5, "text-anchor": "middle" }, g.shown));
    } else {
      group.append(svgText({ class: "ag-type is-solo", x: mid, y: 24.5, "text-anchor": "middle" }, g.type));
    }
    if (g.kids.length) group.append(drawGraphToggle(g));
    return group;
  }

  /** The fold button under a node: a minus while open, "+N" (hidden nodes) while folded. */
  function drawGraphToggle(g) {
    const hidden = g.size - 1;
    const t = svg("g", {
      class: "ag-toggle", role: "button", tabindex: "0", "data-path": g.path,
      "aria-expanded": String(g.open),
      "aria-label": g.open ? `Fold ${g.type}` : `Unfold ${g.type}, ${plural(hidden, "node")} hidden`,
      transform: `translate(${g.w / 2},${AG.nodeH})`,
    });
    const tip = svg("title");
    tip.textContent = g.open ? "Fold this subtree" : `Unfold ${plural(hidden, "hidden node")}`;
    t.append(tip, svg("circle", { class: "ag-hit", r: 12 }));
    if (g.open) {
      t.append(svg("circle", { class: "ag-knob", r: 7 }), svg("path", { class: "ag-glyph", d: "M-3,0H3" }));
    } else {
      const text = `+${fmt(hidden)}`;
      const w = Math.round(textWidth(text, `500 10px ${monoFont()}`)) + 12;
      t.append(svg("rect", { class: "ag-knob", x: -w / 2, y: -7, width: w, height: 14, rx: 7 }),
               svgText({ class: "ag-count", y: 3.5, "text-anchor": "middle" }, text));
    }
    return t;
  }

  const monoFont = () => getComputedStyle(document.documentElement).getPropertyValue("--font-mono").trim() || "monospace";

  function drawGraph() {
    layoutGraph();
    const root = svg("svg", {
      class: "ag-svg", viewBox: `0 0 ${graph.W} ${graph.H}`, role: "group",
      "aria-label": `Syntax tree diagram, ${plural(graph.tree.size, "node")}. The Tree view lists the same nodes as text.`,
    });
    const edges = svg("g", { class: "ag-edges", "aria-hidden": "true" });
    const labels = svg("g", { class: "ag-labels", "aria-hidden": "true" });
    const nodes = svg("g", { class: "ag-nodes" });
    for (const g of graph.visible) {
      if (g.open) drawGraphEdges(g, edges, labels);
      nodes.append(drawGraphNode(g));
    }
    root.append(edges, labels, nodes);
    root.addEventListener("click", (e) => {
      const toggle = e.target.closest(".ag-toggle");
      if (toggle) toggleGraphNode(toggle.dataset.path, false);
    });
    root.addEventListener("keydown", (e) => {
      const toggle = e.target.closest(".ag-toggle");
      if (toggle && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        toggleGraphNode(toggle.dataset.path, true);
      }
    });
    astBody.replaceChildren(root);
    graph.svg = root;
    applyGraphZoom();
  }

  function renderAstGraph(body, r) {
    if (graph.result !== r) {
      graph.result = r;
      graph.tree = buildGraphTree(r.ast, "", null);
      measureGraphTree(graph.tree, monoFont());
      graph.collapsed = new Set();
      graph.mode = "auto";
      graph.pending = true;
      graph.scroll = null;
      // Box sizes depend on the code font; measure again if it was still loading.
      if (document.fonts && document.fonts.status !== "loaded") {
        document.fonts.ready.then(() => {
          if (graph.result !== r) return;
          measureGraphTree(graph.tree, monoFont());
          if (graph.svg) drawGraph();
        });
      }
    }
    body.classList.add("is-graph");
    drawGraph();
    if (graph.pending || !graph.scroll) {
      autoGraphView();
    } else {
      body.scrollLeft = graph.scroll.left;
      body.scrollTop = graph.scroll.top;
      drawMinimap();
    }
  }

  function applyGraphZoom() {
    if (!graph.svg) return;
    graph.svg.setAttribute("width", Math.round(graph.W * graph.zoom));
    graph.svg.setAttribute("height", Math.round(graph.H * graph.zoom));
    const percent = `${Math.round(graph.zoom * 100)}%`;
    $("#ast-zoom-fit").textContent = percent;
    $("#ast-zoom-fit").setAttribute("aria-label", `Zoom ${percent}. Fit the whole tree`);
  }

  /** Zoom keeping the point under `anchor` (panel coordinates; default: the centre) where it is. */
  function setGraphZoom(zoom, anchor) {
    if (!graph.svg || !astBody.clientWidth) return;
    zoom = clamp(zoom, AG.minZoom, AG.maxZoom);
    const box = astBody.getBoundingClientRect();
    const ax = box.left + (anchor ? anchor.x : astBody.clientWidth / 2);
    const ay = box.top + (anchor ? anchor.y : astBody.clientHeight / 2);
    const before = graph.svg.getBoundingClientRect();
    const cx = (ax - before.left) / graph.zoom;
    const cy = (ay - before.top) / graph.zoom;
    graph.zoom = zoom;
    graph.mode = "manual";
    applyGraphZoom();
    const after = graph.svg.getBoundingClientRect();
    astBody.scrollLeft += after.left + cx * zoom - ax;
    astBody.scrollTop += after.top + cy * zoom - ay;
    drawMinimap();
  }

  const fitZoom = () => Math.min((astBody.clientWidth - 8) / graph.W, (astBody.clientHeight - 8) / graph.H);

  function fitGraph() {
    if (!graph.svg || !astBody.clientWidth) return;
    graph.zoom = clamp(fitZoom(), AG.minZoom, AG.maxFit);
    graph.mode = "fit";
    applyGraphZoom();
    astBody.scrollLeft = 0;
    astBody.scrollTop = 0;
    drawMinimap();
  }

  /** The starting view: the whole tree if it is still readable, else the top-left corner at a readable size. */
  function autoGraphView() {
    if (!graph.svg || !astBody.clientWidth) {
      graph.pending = true;
      return;
    }
    graph.pending = false;
    const fit = fitZoom();
    graph.zoom = fit >= AG.readable ? Math.min(fit, AG.maxFit) : AG.bigTreeZoom;
    graph.mode = "auto";
    applyGraphZoom();
    astBody.scrollLeft = 0;
    astBody.scrollTop = 0;
    drawMinimap();
  }

  /** Fold or unfold one node, keeping it still on screen. */
  function toggleGraphNode(path, refocus) {
    const find = () => graph.svg && graph.svg.querySelector(`.ag-node[data-path="${CSS.escape(path)}"]`);
    const before = find()?.getBoundingClientRect();
    if (graph.collapsed.has(path)) graph.collapsed.delete(path);
    else graph.collapsed.add(path);
    if (graph.mode === "auto") graph.mode = "manual";
    drawGraph();
    const node = find();
    const after = node?.getBoundingClientRect();
    if (before && after) {
      astBody.scrollLeft += after.left - before.left;
      astBody.scrollTop += after.top - before.top;
    }
    drawMinimap();
    if (refocus) node?.querySelector(".ag-toggle")?.focus();
  }

  /** Expand all / Collapse all in the Graph view. */
  function foldGraph(shouldFold) {
    if (!graph.tree) return;
    graph.collapsed = new Set();
    (function walk(g) {
      if (g.kids.length && shouldFold(g)) graph.collapsed.add(g.path);
      g.kids.forEach(walk);
    })(graph.tree);
    drawGraph();
    autoGraphView();
  }

  // Minimap: the whole tree in miniature with the visible part outlined, shown once the tree
  // no longer fits. Click or drag in it to move there.
  function drawMinimap() {
    const mini = $("#ast-minimap");
    const show = state.tab === "ast" && state.astView === "graph" && !!graph.svg && astBody.clientWidth > 0
      && (graph.W * graph.zoom > astBody.clientWidth + 2 || graph.H * graph.zoom > astBody.clientHeight + 2);
    mini.hidden = !show;
    if (!show) {
      graph.mini = null;
      return;
    }
    const scale = Math.min(168 / graph.W, 84 / graph.H);
    const map = svg("svg", {
      width: Math.max(24, Math.round(graph.W * scale)), height: Math.max(12, Math.round(graph.H * scale)),
      viewBox: `0 0 ${graph.W} ${graph.H}`, preserveAspectRatio: "none",
    });
    const d = [...graph.svg.querySelectorAll(".ag-edge")].map((p) => p.getAttribute("d")).join("");
    map.append(svg("path", { class: "mm-edge", d }));
    for (const g of graph.visible) {
      map.append(svg("rect", { class: `mm-node k-${g.kind}`, x: g.x - g.w / 2, y: g.y, width: g.w, height: AG.nodeH, rx: 6 }));
    }
    const view = svg("rect", { class: "mm-view" });
    map.append(view);
    mini.replaceChildren(map);
    graph.mini = { map, view };
    drawMinimapView();
  }

  function drawMinimapView() {
    const m = graph.mini;
    if (!m || !graph.svg) return;
    const z = graph.zoom;
    const box = astBody.getBoundingClientRect(), at = graph.svg.getBoundingClientRect();
    const x = Math.max(0, (box.left - at.left) / z);   // the diagram's point at the panel's top-left corner
    const y = Math.max(0, (box.top - at.top) / z);
    m.view.setAttribute("x", x);
    m.view.setAttribute("y", y);
    m.view.setAttribute("width", Math.min(graph.W - x, astBody.clientWidth / z));
    m.view.setAttribute("height", Math.min(graph.H - y, astBody.clientHeight / z));
  }

  astBody.addEventListener("scroll", drawMinimapView, { passive: true });   // scroll events come at most once a frame

  (() => {
    const mini = $("#ast-minimap");
    let dragging = false;
    const goTo = (e) => {
      if (!graph.mini) return;
      const r = graph.mini.map.getBoundingClientRect();
      const cx = ((e.clientX - r.left) / r.width) * graph.W;
      const cy = ((e.clientY - r.top) / r.height) * graph.H;
      astBody.scrollLeft = cx * graph.zoom - astBody.clientWidth / 2;
      astBody.scrollTop = cy * graph.zoom - astBody.clientHeight / 2;
    };
    mini.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      dragging = true;
      mini.setPointerCapture(e.pointerId);
      goTo(e);
    });
    mini.addEventListener("pointermove", (e) => { if (dragging) goTo(e); });
    mini.addEventListener("pointerup", () => { dragging = false; });
    mini.addEventListener("pointercancel", () => { dragging = false; });
  })();

  // Drag the diagram to move around (a mouse or pen; touch screens already scroll natively).
  // A drag must not count as a click, which would jump the editor to a line.
  (() => {
    let pan = null;
    let swallowClick = false;
    astBody.addEventListener("pointerdown", (e) => {
      if (!astBody.classList.contains("is-graph") || e.button !== 0 || e.pointerType === "touch") return;
      if (e.target.closest(".ag-toggle")) return;
      pan = { id: e.pointerId, x: e.clientX, y: e.clientY, left: astBody.scrollLeft, top: astBody.scrollTop, moved: false };
    });
    astBody.addEventListener("pointermove", (e) => {
      if (!pan || e.pointerId !== pan.id) return;
      const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
      if (!pan.moved) {
        if (Math.hypot(dx, dy) < 4) return;
        pan.moved = true;
        astBody.setPointerCapture(pan.id);
        astBody.classList.add("is-panning");
        if (graph.mode === "auto") graph.mode = "manual";
      }
      astBody.scrollLeft = pan.left - dx;
      astBody.scrollTop = pan.top - dy;
    });
    const end = (e) => {
      if (!pan || e.pointerId !== pan.id) return;
      if (pan.moved) {
        swallowClick = true;
        setTimeout(() => { swallowClick = false; }, 0);
      }
      astBody.classList.remove("is-panning");
      pan = null;
    };
    astBody.addEventListener("pointerup", end);
    astBody.addEventListener("pointercancel", end);
    astBody.addEventListener("click", (e) => {
      if (!swallowClick) return;
      swallowClick = false;
      e.stopPropagation();
      e.preventDefault();
    }, true);
  })();

  // Ctrl/⌘ + wheel (or a trackpad pinch) zooms at the pointer. A plain wheel scrolls; when the
  // tree is wide but short, it scrolls sideways so the wheel still gets you somewhere.
  astBody.addEventListener("wheel", (e) => {
    if (!astBody.classList.contains("is-graph")) return;
    const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const box = astBody.getBoundingClientRect();
      setGraphZoom(graph.zoom * Math.exp(-delta * 0.0018), { x: e.clientX - box.left, y: e.clientY - box.top });
    } else if (!e.shiftKey && Math.abs(e.deltaY) > Math.abs(e.deltaX)
               && astBody.scrollHeight <= astBody.clientHeight && astBody.scrollWidth > astBody.clientWidth) {
      e.preventDefault();
      astBody.scrollLeft += delta;
      if (graph.mode === "auto") graph.mode = "manual";
    }
  }, { passive: false });

  $("#ast-zoom-in").addEventListener("click", () => setGraphZoom(graph.zoom * 1.25));
  $("#ast-zoom-out").addEventListener("click", () => setGraphZoom(graph.zoom / 1.25));
  $("#ast-zoom-fit").addEventListener("click", fitGraph);
  $("#panel-ast").addEventListener("keydown", (e) => {
    if (state.astView !== "graph" || !graph.svg || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "+" || e.key === "=") setGraphZoom(graph.zoom * 1.25);
    else if (e.key === "-" || e.key === "_") setGraphZoom(graph.zoom / 1.25);
    else if (e.key === "0") fitGraph();
    else return;
    e.preventDefault();
  });

  // Full screen: the AST panel alone fills the screen (Esc leaves it). Where the browser refuses
  // real full screen (an embedded browser, an iPhone), the panel fills the window instead.
  const astPanel = $("#panel-ast");
  const fullscreenButton = $("#ast-fullscreen");

  function syncFullscreenButton() {
    const on = document.fullscreenElement === astPanel || astPanel.classList.contains("is-maximized");
    fullscreenButton.setAttribute("aria-pressed", String(on));
    fullscreenButton.setAttribute("aria-label", on ? "Exit full screen" : "Full screen");
    fullscreenButton.title = on ? "Exit full screen (Esc)" : "Full screen";
  }

  function setAstMaximized(on) {
    astPanel.classList.toggle("is-maximized", on);
    syncFullscreenButton();
  }

  function leaveAstFullscreen() {
    if (document.fullscreenElement === astPanel) document.exitFullscreen().catch(() => {});
    if (astPanel.classList.contains("is-maximized")) setAstMaximized(false);
  }

  fullscreenButton.addEventListener("click", async () => {
    if (document.fullscreenElement === astPanel || astPanel.classList.contains("is-maximized")) return leaveAstFullscreen();
    try {
      if (!document.fullscreenEnabled) throw new Error("full screen is not available");
      // Some embedded browsers neither grant nor refuse the request, so don't wait for long.
      await Promise.race([astPanel.requestFullscreen(), new Promise((_, no) => setTimeout(() => no(new Error("no answer")), 600))]);
    } catch {
      if (document.fullscreenElement !== astPanel) setAstMaximized(true);
    }
  });
  document.addEventListener("fullscreenchange", () => {
    if (document.fullscreenElement === astPanel) astPanel.classList.remove("is-maximized");
    syncFullscreenButton();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && astPanel.classList.contains("is-maximized")) setAstMaximized(false);
  });

  // Re-zoom when the panel changes size: a window resize, the pane divider, full screen, or the
  // tab becoming visible for the first time after a run.
  new ResizeObserver(() => {
    if (state.astView !== "graph" || !graph.svg || !astBody.clientWidth) return;
    if (graph.pending || graph.mode === "auto") autoGraphView();
    else if (graph.mode === "fit") fitGraph();
    else drawMinimap();
  }).observe(astBody);

  // ------------------------------------------------------- warnings (semantic)

  const WARNING_LABEL = {
    "maybe-unassigned": "may be unassigned",
    "scope-trap": "scope trap",
    unreachable: "unreachable",
    unused: "unused",
    "dead-store": "dead store",
  };
  let warningKinds = [];

  /** Every error of the failing stage (the lexer, parser and semantic analysis report them all). */
  const allErrors = (r) => (r.errors && r.errors.length ? r.errors : r.error ? [r.error] : []);
  let errorKinds = [];

  function markErrors(list) {
    unmarkErrors();
    list.forEach((err, i) => {
      if (!err.line || err.in_test_code) return;
      const kind = `error-${i}`;
      editor.mark(kind, err.line, "cm-line-error");
      errorKinds.push(kind);
    });
  }

  function unmarkErrors() {
    errorKinds.forEach((kind) => editor.unmark(kind));
    errorKinds = [];
  }

  function markWarnings(list) {
    unmarkWarnings();
    (list || []).forEach((w, i) => {
      if (!w.line) return;
      const kind = `warning-${i}`;
      editor.mark(kind, w.line, "cm-line-warning");
      warningKinds.push(kind);
    });
  }

  function unmarkWarnings() {
    warningKinds.forEach((kind) => editor.unmark(kind));
    warningKinds = [];
  }

  function warningItem(w) {
    return el("li", { class: "warning", dataset: { line: w.line ?? "" } },
      w.line
        ? el("button", { class: "warning-line", type: "button", title: "Show this line in the editor",
            onclick: () => editor.goTo(w.line) }, `line ${w.line}`)
        : null,
      el("span", { class: "warning-code" }, WARNING_LABEL[w.code] || w.code),
      el("span", { class: "warning-msg" }, w.message));
  }

  function warningSummary(list) {
    return el("div", { class: "warning-box" },
      el("p", { class: "warning-title" },
        `${plural(list.length, "warning")} from semantic analysis`,
        el("button", { class: "btn-link", type: "button", onclick: () => selectTab("symbols", { focus: true }) },
          "Open the symbol table")),
      el("ul", { class: "warning-list" }, list.slice(0, 3).map(warningItem)),
      list.length > 3 ? el("p", { class: "muted" }, `and ${list.length - 3} more in the Symbols tab.`) : null);
  }

  // ------------------------------------------------------------ symbol table

  const lineList = (lines) => (lines && lines.length ? lines.join(", ") : "–");

  /** An inferred type: "number", "list", "number or list" (or "no value"). */
  const typeChip = (type) => el("span", { class: `type-chip type-${(type || "unknown").replace(/\W+/g, "-")}` }, type || "?");

  function symbolTable(rows, emptyText, withTypes) {
    if (!rows.length) return el("p", { class: "sym-empty" }, emptyText);
    return el("table", { class: "data-table sym-table" },
      el("thead", null, el("tr", null,
        el("th", { scope: "col" }, "Name"), el("th", { scope: "col" }, "Kind"),
        withTypes ? el("th", { scope: "col" }, "Type") : null,
        el("th", { scope: "col" }, "Assigned on"), el("th", { scope: "col" }, "Read on"))),
      el("tbody", null, rows.map((row) =>
        el("tr", { dataset: { line: row.line ?? (row.reads && row.reads[0]) ?? "" } },
          el("td", { class: "sym-name" }, row.name),
          el("td", null, el("span", { class: `sym-kind kind-${row.kind.replace(/\W+/g, "-")}` }, row.kind)),
          withTypes ? el("td", null, typeChip(row.type)) : null,
          el("td", { class: "num-cell" }, lineList(row.assigned)),
          el("td", { class: "num-cell" }, lineList(row.reads))))));
  }

  function renderSymbols() {
    const body = $("#symbols-body");
    const r = state.result;
    body.replaceChildren();
    if (!r.symbols) return body.append(blocked("symbol table"));
    const s = r.symbols;

    const sections = [];
    sections.push(s.warnings.length
      ? el("section", { class: "sym-section" },
          el("h3", { class: "section-label" }, `Warnings · ${s.warnings.length}`),
          el("ul", { class: "warning-list" }, s.warnings.map(warningItem)))
      : el("p", { class: "sym-clean" },
          "No warnings. Every variable is assigned before it's read, and nothing is unused or unreachable."));

    // Types come from the type checker; they're missing if it found an error.
    const t = r.types;
    if (t) {
      sections.push(el("p", { class: "sym-types-note" },
        "Types are inferred: MiniLang has no type declarations, so the type checker works out what each name can hold. ",
        t.elements !== "no value" ? ["Values stored in lists: ", typeChip(t.elements), "."] : null));
    } else if (r.error && r.error.stage === "type") {
      sections.push(el("p", { class: "sym-types-note" }, "The type checker found an error, so no types are shown. See Output."));
    }

    const globals = s.globals.map((g) => ({ ...g, type: t && t.globals[g.name] }));
    sections.push(el("section", { class: "sym-section" },
      el("h3", { class: "section-label" }, "Global scope"),
      symbolTable(globals, "No global variables.", !!t)));

    for (const fn of s.functions) {
      const ft = t && t.functions[fn.name];
      const typeOf = (sym) => (ft ? (sym.kind === "parameter" ? ft.params[sym.name] : ft.locals[sym.name]) : null);
      const rows = fn.symbols.map((sym) => ({ ...sym, type: typeOf(sym) }))
        .concat(fn.globals_read.map((g) => ({ name: g.name, kind: "global (read)", reads: g.reads, type: t && t.globals[g.name] })));
      sections.push(el("section", { class: "sym-section" },
        el("h3", { class: "sym-fn-title", dataset: { line: fn.line } },
          el("span", { class: "sym-fn" }, ft ? ft.signature.replace(" -> ", " → ") : fn.signature),
          el("span", { class: "sym-fn-meta" },
            `defined on line ${fn.line} · ${fn.calls.length ? `called on line${fn.calls.length > 1 ? "s" : ""} ${fn.calls.join(", ")}` : "never called"}`)),
        symbolTable(rows, "No parameters or locals.", !!t)));
    }
    body.append(...sections);
  }

  // ----------------------------------------------------------------------- IR

  function renderIr() {
    const body = $("#ir-body");
    const r = state.result;
    body.replaceChildren();
    $("#ir-toolbar").hidden = !r.ir;
    if (!r.ir) return body.append(blocked("intermediate representation"));

    const optimized = state.irView === "optimized";
    for (const seg of $$("[data-ir-view]")) seg.setAttribute("aria-pressed", String(seg.dataset.irView === state.irView));
    const st = r.ir.stats;
    $("#ir-note").textContent = optimized
      ? `${plural(st.constant_reads, "constant read")} proven · ${plural(st.removed_stores, "dead store")} removed`
        + (st.unreachable_blocks ? ` · ${plural(st.unreachable_blocks, "unreachable block")} dropped` : "")
      : `${plural(st.blocks, "basic block")} · live variables per block`
        + (st.dead_stores ? ` · ${plural(st.dead_stores, "dead store")}` : "");

    for (const proc of r.ir.procedures) {
      const cfg = el("div", { class: "cfg", dataset: { proc: proc.name } },
        proc.blocks.map((b) => irBlock(b, optimized)));
      body.append(el("section", { class: "ir-proc" },
        el("h3", { class: "ir-proc-title" }, proc.name === "main" ? "main (top-level code)" : proc.name),
        cfg));
      cfg.__blocks = proc.blocks;
    }
    if (state.tab === "ir") drawIrEdges();
  }

  const liveRow = (label, names, title) =>
    el("div", { class: "ir-live", title },
      el("span", { class: "ir-live-label" }, label),
      names.length ? names.map((n) => el("span", { class: "ir-var" }, n)) : el("span", { class: "muted" }, "nothing"));

  function irBlock(b, optimized) {
    const facts = optimized ? Object.entries(b.constants_in || {}) : [];
    const head = el("div", { class: "ir-block-head" },
      el("span", { class: "ir-block-id" }, b.id),
      b.label ? el("span", { class: "ir-block-label" }, `${b.label}:`) : null,
      !b.reachable ? el("span", { class: "ir-dead" }, "unreachable") : null,
      el("span", { class: "ir-succ" }, b.succ.length ? `→ ${b.succ.join(", ")}` : "→ exit"));

    let lines;
    if (optimized && !b.reachable) {
      lines = [el("div", { class: "ir-line muted" }, "removed: no path reaches this block")];
    } else if (optimized) {
      const removed = new Set(b.optimized_dead || []);
      lines = b.optimized.length
        ? b.optimized.map((line, i) => removed.has(i)
            ? el("div", { class: "ir-line is-removed", title: "Dead store: nothing reads this value, so it is removed" }, line)
            : el("div", { class: "ir-line" }, line))
        : [el("div", { class: "ir-line muted" }, "(empty)")];
    } else {
      const dead = new Set(b.dead || []);
      lines = b.lines.length
        ? b.lines.map((line, i) => el("div", {
              class: `ir-line${dead.has(i) ? " is-dead-store" : ""}`,
              title: dead.has(i) ? "Dead store: this value is never read before it is overwritten or the program ends" : null,
              dataset: { line: b.source_lines[i] ?? "" },
            }, line, dead.has(i) ? el("span", { class: "ir-tag" }, "dead store") : null))
        : [el("div", { class: "ir-line muted" }, "(empty)")];
    }

    return el("div", { class: `ir-block${b.reachable ? "" : " is-dead"}`, id: null, dataset: { block: b.id } },
      head,
      facts.length
        ? el("div", { class: "ir-facts", title: "Constants known on entry to this block" },
            facts.map(([name, value]) => el("span", { class: "ir-fact" }, `${name} = ${value}`)))
        : null,
      optimized ? null : liveRow("live in", b.live_in, "Variables whose value on entry may still be read"),
      el("div", { class: "ir-code" }, lines),
      optimized ? null : liveRow("live out", b.live_out, "Variables whose value on exit may still be read by a later block"));
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    return node;
  }

  /** Draw the control-flow edges. Needs the panel visible, so it runs when the IR tab opens. */
  function drawIrEdges() {
    for (const cfg of $$("#ir-body .cfg")) {
      cfg.querySelector(":scope > svg")?.remove();
      const blocks = cfg.__blocks || [];
      const cards = Object.fromEntries([...cfg.querySelectorAll(".ir-block")].map((c) => [c.dataset.block, c]));
      const width = cfg.clientWidth, height = cfg.scrollHeight;
      if (!width) continue;
      const layer = svg("svg", { class: "cfg-edges", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
      const defs = svg("defs");
      for (const kind of ["fall", "jump", "back"]) {
        const marker = svg("marker", { id: `arrow-${kind}`, viewBox: "0 0 8 8", refX: "7", refY: "4", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
        marker.append(svg("path", { d: "M0,0 L8,4 L0,8 z", class: `arrow-${kind}` }));
        defs.append(marker);
      }
      layer.append(defs);

      const box = (id) => {
        const c = cards[id];
        return { top: c.offsetTop, bottom: c.offsetTop + c.offsetHeight, left: c.offsetLeft, right: c.offsetLeft + c.offsetWidth,
                 mid: c.offsetTop + Math.min(22, c.offsetHeight / 2) };
      };
      let rightLane = 0, leftLane = 0;
      blocks.forEach((b, i) => {
        for (const target of b.succ) {
          const j = blocks.findIndex((x) => x.id === target);
          const from = box(b.id), to = box(target);
          if (j === i + 1) {           // fall through to the next block: straight down
            const x = from.left + 28;
            layer.append(svg("path", { d: `M${x},${from.bottom} L${x},${to.top - 1}`, class: "edge edge-fall", "marker-end": "url(#arrow-fall)" }));
          } else if (j > i) {          // forward jump: route down the right-hand side
            const x = from.right + 14 + (rightLane++ % 4) * 9;
            layer.append(svg("path", { d: `M${from.right},${from.mid} H${x} V${to.mid} H${to.right + 1}`, class: "edge edge-jump", "marker-end": "url(#arrow-jump)" }));
          } else {                     // back edge (a loop): route up the left-hand side
            const x = from.left - 14 - (leftLane++ % 4) * 9;
            layer.append(svg("path", { d: `M${from.left},${from.mid + 8} H${x} V${to.mid} H${to.left - 1}`, class: "edge edge-back", "marker-end": "url(#arrow-back)" }));
          }
        }
      });
      cfg.prepend(layer);
    }
  }

  for (const seg of $$("[data-ir-view]")) {
    seg.addEventListener("click", () => {
      state.irView = seg.dataset.irView;
      renderIr();
    });
  }
  let irResizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(irResizeTimer);
    irResizeTimer = setTimeout(() => { if (state.tab === "ir") drawIrEdges(); }, 120);
  });

  // ---------------------------------------------------------------- bytecode

  function renderBytecode() {
    const body = $("#bytecode-body");
    const r = state.result;
    body.replaceChildren();
    $("#bytecode-toolbar").hidden = !r.bytecode;
    if (!r.bytecode) return body.append(blocked("bytecode"));

    const optimized = state.bcView === "optimized";
    const code = optimized ? r.bytecode : r.bytecode_unoptimized;
    for (const seg of $$("[data-bc-view]")) seg.setAttribute("aria-pressed", String(seg.dataset.bcView === state.bcView));
    $("#bc-count-opt").textContent = fmt(r.bytecode.length);
    $("#bc-count-orig").textContent = fmt(r.bytecode_unoptimized.length);

    const saved = r.bytecode_unoptimized.length - r.bytecode.length;
    $("#bc-note").textContent = optimized
      ? (saved > 0 ? `The optimizer removed ${plural(saved, "instruction")}. This is the code that ran.` : "This is the code that ran.")
      : "The compiler's output before the optimizer ran.";

    const list = el("ol", { class: "bc-list", "aria-label": "Bytecode instructions" });
    for (const ins of code) {
      if (ins.label) list.append(el("li", { class: "bc-label" }, `${ins.label}:`));
      list.append(bytecodeRow(ins, code));
    }
    body.append(list);
    applyStepHighlight();
  }

  function bytecodeRow(ins, code) {
    const opClass = FLOW_OPS.has(ins.op) ? "op-flow" : MATH_OPS.has(ins.op) ? "op-math" : "op-data";
    let arg = null;
    if (TARGET_OPS.has(ins.op) && Number.isInteger(ins.arg)) {
      arg = el("button", {
        class: "bc-target", type: "button", dataset: { target: ins.arg },
        "aria-label": `Go to instruction ${pad4(ins.arg)}`,
      }, `→ ${pad4(ins.arg)}`);
    } else if (ins.arg !== null && ins.arg !== undefined) {
      arg = el("span", { class: typeof ins.arg === "number" ? "bc-num" : "bc-name" }, String(ins.arg));
    }
    const callee = (ins.op === "CALL" || ins.op === "TAIL_CALL") && code[ins.arg] ? code[ins.arg].label : null;
    return el("li", { class: "bc-row", dataset: { addr: ins.addr, line: ins.line ?? "" } },
      el("span", { class: "bc-addr" }, pad4(ins.addr)),
      el("span", { class: `bc-op ${opClass}` }, ins.op),
      el("span", { class: "bc-arg" }, arg, callee ? el("span", { class: "bc-note" }, `  ${callee}`) : null),
      el("span", { class: "bc-line" }, ins.line != null ? `line ${ins.line}` : ""));
  }

  for (const seg of $$("[data-bc-view]")) {
    seg.addEventListener("click", () => {
      state.bcView = seg.dataset.bcView;
      renderBytecode();
    });
  }

  // Clicking a jump target scrolls to that instruction and flashes it.
  $("#bytecode-body").addEventListener("click", (e) => {
    const button = e.target.closest(".bc-target");
    if (!button) return;
    const row = $(`.bc-row[data-addr="${button.dataset.target}"]`, $("#bytecode-body"));
    if (!row) return;
    row.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    row.classList.remove("is-flash");
    void row.offsetWidth; // restart the animation
    row.classList.add("is-flash");
  });

  function scrollCurrentInstructionIntoView() {
    const row = $(".bc-row.is-current", $("#bytecode-body"));
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  // ------------------------------------------------------------------ output

  function renderOutput() {
    const r = state.result;
    $("#output-empty").hidden = true;
    $("#output-result").hidden = false;

    const consoleEl = $("#console");
    consoleEl.replaceChildren();
    if (r.output.length) {
      consoleEl.textContent = r.output.join("\n");
    } else if (!r.error) {
      consoleEl.append(el("span", { class: "muted" }, "The program ran but didn't print anything."));
    }
    $("#console-count").textContent = r.output.length ? `· ${plural(r.output.length, "line")}` : "";

    const note = $("#harness-note");
    note.hidden = !r.harness;
    if (r.harness) {
      note.replaceChildren("Ran with the level's example test: ", el("code", null, r.harness.label || "no inputs"),
        ". Check runs every test.");
    }

    const inputNote = $("#input-note");
    const input = r.input || { values: [], used: 0 };
    inputNote.hidden = !readsInputAtRuntime(r);
    if (!inputNote.hidden) inputNote.replaceChildren(...inputSummary(input));

    const warnSlot = $("#warning-slot");
    warnSlot.replaceChildren();
    if (r.warnings && r.warnings.length) warnSlot.append(warningSummary(r.warnings));

    const slot = $("#error-slot");
    slot.replaceChildren();
    if (r.error) slot.append(errorBox(allErrors(r), r.output.length));

    renderStepper();
  }

  /** True when the program that ran has input statements (its bytecode has an INPUT). */
  const readsInputAtRuntime = (r) => !!(r.bytecode && r.input && r.bytecode.some((ins) => ins.op === "INPUT"));

  /** "Input: 3 4 5 0 · read 2 of 4", with the values not read yet dimmed. */
  function inputSummary(input, used = input.used) {
    if (!input.values.length) {
      return [state.runContext ? "Input: none." : "Input: none given. Type numbers for input statements into the Input box under the editor."];
    }
    const shown = input.values.slice(0, 40);
    return [
      "Input: ",
      shown.map((v, i) => [i ? " " : "", el("code", { class: i < used ? "is-read" : "is-unread" }, v)]),
      input.values.length > shown.length ? " …" : "",
      used === input.values.length
        ? (used ? ` · all ${plural(used, "value")} read` : " · nothing given")
        : ` · read ${fmt(used)} of ${fmt(input.values.length)}`,
    ].flat(Infinity);
  }

  function errorBox(errors, printedLines) {
    const err = errors[0];
    const many = errors.length > 1;
    const hints = {
      lex: many
        ? "The lexer skipped each bad character and kept going, so every one is listed."
        : "The lexer found a character that isn't part of MiniLang.",
      parse: many
        ? "The parser recovered after each error and kept checking, so all of them are listed. Fix the first one first: a later one can be a knock-on effect of it."
        : "The code doesn't match MiniLang's grammar. Check for a missing ';', brace or bracket.",
      semantic: many
        ? "The grammar is fine, but these names or calls don't make sense. Semantic analysis found all of them before anything ran."
        : "The grammar is fine, but a name or call doesn't make sense. Semantic analysis caught it before anything ran.",
      type: "Every name is defined, but a value is used as the wrong type: a list where a number is needed, or a number "
        + "where a list is needed. The type checker proved it before anything ran, so the line would fail every time.",
      compile: "The syntax is fine, but a compile-time check failed.",
      runtime: printedLines
        ? "The program started, printed the output above, then stopped here. Step through below to see the state just before the error."
        : "The program compiled but stopped while running. Step through below to see the state just before the error.",
    };
    const where = (e) => (e.in_test_code
      ? el("span", { class: "error-line is-static" }, "in the test code")
      : e.line
        ? el("button", {
            class: "error-line", type: "button", title: "Show this line in the editor",
            onclick: () => editor.goTo(e.line),
          }, `line ${e.line}`)
        : null);
    const label = STAGE_LABEL[err.stage] || "Error";
    return el("div", { class: "error-box", role: "alert" },
      el("div", { class: "error-head" },
        el("span", { class: "error-stage" }, many ? `${errors.length} ${label.toLowerCase()}s` : label),
        many ? null : where(err)),
      many
        ? el("ul", { class: "error-list" }, errors.map((e) =>
            el("li", { class: "error-item" }, where(e), el("span", { class: "error-message" }, e.message))))
        : el("p", { class: "error-message" }, err.message),
      hints[err.stage] ? el("p", { class: "error-hint" }, hints[err.stage]) : null);
  }

  // ----------------------------------------------------------------- stepper

  function renderStepper() {
    const r = state.result;
    const trace = r.trace || [];
    $("#stepper").hidden = trace.length === 0;
    if (!trace.length) return;

    $("#step-range").max = String(trace.length - 1);
    const note = $("#step-truncated");
    note.hidden = !r.trace_truncated;
    note.textContent = r.trace_truncated
      ? `The trace keeps the first ${fmt(trace.length)} steps. The program ran on after that, and its full output is above.`
      : "";
    showStep(state.step);
  }

  function showStep(index) {
    const r = state.result;
    const trace = r.trace || [];
    if (!trace.length) return;
    const i = clamp(index, 0, trace.length - 1);
    if (i < state.step) emit("step-back", i);
    state.step = i;
    const s = trace[i];
    const prev = i > 0 ? trace[i - 1] : null;
    const last = i === trace.length - 1;

    $("#step-range").value = String(i);
    $("#step-count").textContent = `Step ${fmt(i + 1)} of ${fmt(trace.length)}${r.trace_truncated ? "+" : ""}`;
    $("#step-first").disabled = i === 0;
    $("#step-prev").disabled = i === 0;
    $("#step-next").disabled = last;
    $("#step-last").disabled = last;

    // What just ran, and what runs next.
    const describe = (ins) => `${pad4(ins.addr)}  ${ins.op}${ins.arg !== null && ins.arg !== undefined ? ` ${ins.arg}` : ""}`;
    const where = [];
    if (s.line != null) where.push(`line ${s.line}`);
    if (s.call_stack.length) where.push(`in ${s.call_stack[s.call_stack.length - 1]}`);

    let nextLine;
    if (s.op === "HALT") {
      nextLine = el("div", { class: "step-line is-next" }, el("span", { class: "step-tag" }, "Next"), el("code", null, "program finished"));
    } else if (last && r.error && r.error.stage === "runtime") {
      nextLine = el("div", { class: "step-line is-error" }, el("span", { class: "step-tag" }, "Next"),
        el("code", null, `${r.error.message}${r.error.line ? ` (line ${r.error.line})` : ""}`));
    } else {
      const next = r.bytecode && r.bytecode[s.next_pc];
      nextLine = next
        ? el("div", { class: "step-line is-next" }, el("span", { class: "step-tag" }, "Next"), el("code", null, describe(next)),
            next.line != null ? el("span", { class: "step-where" }, `line ${next.line}`) : null)
        : null;
    }

    $("#step-now").replaceChildren(
      el("div", { class: "step-line is-now" }, el("span", { class: "step-tag" }, "Just ran"), el("code", null, describe(s)),
        where.length ? el("span", { class: "step-where" }, where.join(" · ")) : null),
      nextLine);

    // Operand stack, top first.
    const stack = $("#step-stack");
    stack.replaceChildren();
    if (!s.stack.length) {
      stack.append(el("li", { class: "stack-empty" }, "empty"));
    } else {
      [...s.stack].reverse().forEach((value, k) => {
        stack.append(el("li", { class: k === 0 ? "is-top" : null },
          el("span", null, showValue(value)),
          k === 0 ? el("span", { class: "stack-top" }, "top") : null));
      });
    }

    // Frames: globals, then each active call, innermost last (like Python Tutor).
    const frames = s.frames || [];
    const prevFrames = prev ? prev.frames || [] : [];
    const cards = [frameCard("Global frame", s.variables, prev ? prev.variables : {}, frames.length === 0, true)];
    frames.forEach((f, k) => {
      // Compare with the same frame one step earlier; a brand-new frame has nothing to compare with.
      const before = prevFrames[k] && prevFrames[k].name === f.name ? prevFrames[k].locals : {};
      cards.push(frameCard(f.name, f.locals, before, k === frames.length - 1, false));
    });
    $("#step-frames").replaceChildren(...cards);

    // Output printed up to this step, and the input read so far.
    $("#step-output").textContent = r.output.slice(0, s.lines_printed).join("\n");
    const stepInput = $("#step-input");
    stepInput.hidden = !readsInputAtRuntime(r);
    if (!stepInput.hidden) stepInput.replaceChildren(...inputSummary(r.input, s.input_used || 0));

    applyStepHighlight();
  }

  function frameCard(title, vars, previous, current, isGlobals) {
    const entries = Object.entries(vars || {});
    return el("div", { class: `frame${current ? " is-current" : ""}` },
      el("div", { class: "frame-head" },
        el("span", { class: `frame-name${isGlobals ? " is-globals" : ""}` }, title),
        current ? el("span", { class: "frame-badge" }, "active") : null),
      entries.length
        ? el("table", { class: "vars" }, el("tbody", null, entries.map(([name, value]) =>
            el("tr", { class: previous && (!(name in previous) || showValue(previous[name]) !== showValue(value)) ? "is-changed" : null },
              el("th", { scope: "row" }, name),
              el("td", null, showValue(value))))))
        : el("p", { class: "frame-empty" }, isGlobals ? "No variables yet" : "No locals yet"));
  }

  /** Mirror the current step in the editor and the bytecode listing. */
  function applyStepHighlight() {
    const r = state.result;
    const trace = (r && r.trace) || [];
    const s = trace[state.step];
    const show = s && !state.stale && (state.tab === "output" || state.tab === "bytecode");

    if (show) editor.mark("step", s.line, "cm-line-step");
    else editor.unmark("step");

    for (const row of $$(".bc-row.is-current")) row.classList.remove("is-current");
    if (s && !state.stale && state.bcView === "optimized") {
      const row = $(`.bc-row[data-addr="${s.addr}"]`, $("#bytecode-body"));
      if (row) row.classList.add("is-current");
    }
  }

  $("#step-first").addEventListener("click", () => showStep(0));
  $("#step-prev").addEventListener("click", () => showStep(state.step - 1));
  $("#step-next").addEventListener("click", () => showStep(state.step + 1));
  $("#step-last").addEventListener("click", () => showStep(Infinity));
  $("#step-range").addEventListener("input", (e) => showStep(Number(e.target.value)));
  $("#stepper").addEventListener("keydown", (e) => {
    if (e.target.matches("input")) return; // the slider handles its own arrows
    if (e.key === "ArrowRight") { e.preventDefault(); showStep(state.step + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); showStep(state.step - 1); }
  });
  $("#step-now").addEventListener("click", () => {
    const s = state.result && state.result.trace && state.result.trace[state.step];
    if (s && s.line) editor.reveal(s.line);
  });

  // ------------------------------------------- hover a row -> find its line

  for (const id of ["#tokens-body", "#ast-body", "#symbols-body", "#ir-body", "#bytecode-body"]) {
    const root = $(id);
    root.addEventListener("mouseover", (e) => {
      const row = e.target.closest("[data-line]");
      const line = row && Number(row.dataset.line);
      if (line) editor.mark("hover", line, "cm-line-hover");
      else editor.unmark("hover");
    });
    root.addEventListener("mouseleave", () => editor.unmark("hover"));
    root.addEventListener("click", (e) => {
      if (e.target.closest("button, [role='button']")) return;
      const row = e.target.closest("[data-line]");
      const line = row && Number(row.dataset.line);
      if (line) editor.reveal(line);
    });
  }

  // ----------------------------------------------------- editor bookkeeping

  let loading = false; // true while an example is being loaded into the editor

  editor.onChange(() => {
    noticeInput();
    if (loading) return;
    scheduleCheck();
    emit("change");
    if (!state.dirty) {
      state.dirty = true;
      $("#dirty-dot").hidden = false;
    }
    if (state.result && !state.stale) {
      state.stale = true;
      $("#stale-note").hidden = false;
      unmarkErrors();
      unmarkWarnings();
      applyStepHighlight();
      setStatus("Edited since last run. Press Run to update.", null);
    }
  });

  editor.onCursor((line, col) => {
    $("#cursor-pos").textContent = `Ln ${line}, Col ${col}`;
  });

  // ------------------------------------------- live checking while you type

  // After a short pause in typing, /lint runs the lexer, parser and semantic
  // analysis (nothing is compiled or run) and the editor underlines what they find.
  const CHECK_DELAY_MS = 450;
  let checkTimer = null;
  let checkSeq = 0;
  let problems = [];

  function scheduleCheck(delay = CHECK_DELAY_MS) {
    clearTimeout(checkTimer);
    checkTimer = setTimeout(checkNow, delay);
  }

  async function checkNow() {
    const seq = ++checkSeq;
    let body = null;
    try {
      const response = await fetch("/lint", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(state.runContext || {}), source: editor.getValue() }),
      });
      if (response.ok) body = await response.json();
    } catch { /* server unreachable: Run will say so */ }
    if (seq !== checkSeq || !body) return; // a newer edit has already started another check
    problems = [
      ...(body.errors || []).map((e) => ({ ...e, severity: "error" })),
      ...(body.warnings || []).map((w) => ({ ...w, severity: "warning" })),
    ];
    editor.setProblems(problems);
    showProblemCount();
  }

  function showProblemCount() {
    const button = $("#problems");
    const errors = problems.filter((p) => p.severity === "error").length;
    const warnings = problems.length - errors;
    button.hidden = false;
    button.className = `problems${errors ? " is-error" : warnings ? " is-warning" : " is-clean"}`;
    const parts = [];
    if (errors) parts.push(plural(errors, "error"));
    if (warnings) parts.push(plural(warnings, "warning"));
    button.textContent = parts.length ? parts.join(" · ") : "No problems";
    button.title = problems.length
      ? `${problems.map((p) => `Line ${p.line ?? "?"}: ${p.message}`).join("\n")}\n\nClick to go to the first one.`
      : "The lexer, parser and semantic analysis found nothing to report.";
    button.disabled = !problems.length;
  }

  $("#problems").addEventListener("click", () => {
    const first = problems.find((p) => p.line);
    if (first) editor.goTo(first.line);
  });

  // ------------------------------------------------------- program input

  // Values for `input x;`. The drawer opens by itself when the program starts using input.
  const stdinPanel = $("#stdin-panel");
  const stdinBox = $("#stdin");
  let usedInput = false;
  const readsInput = (text) => /^[^#]*\binput\b/m.test(text);

  function updateStdinMeta() {
    const count = stdinBox.value.split(/\s+/).filter(Boolean).length;
    $("#stdin-meta").textContent = count ? plural(count, "value") : "numbers for input statements";
  }

  function noticeInput() {
    const now = readsInput(editor.getValue());
    if (now && !usedInput) stdinPanel.open = true;
    usedInput = now;
  }

  try { stdinBox.value = localStorage.getItem("minilang.stdin") || ""; } catch { /* storage unavailable */ }
  stdinBox.addEventListener("input", () => {
    updateStdinMeta();
    try { localStorage.setItem("minilang.stdin", stdinBox.value); } catch { /* storage unavailable */ }
  });
  stdinPanel.addEventListener("toggle", () => editor.refresh());
  updateStdinMeta();

  // ---------------------------------------------------------------- examples

  const select = $("#example-select");
  let currentExample = select.value;
  $("#file-name").textContent = currentExample;

  select.addEventListener("change", () => {
    const example = examples.find((ex) => ex.name === select.value);
    if (!example) return;
    if (state.dirty && !confirm(`Replace the code in the editor with ${example.name}? Your edits will be lost.`)) {
      select.value = currentExample;
      return;
    }
    loading = true;
    editor.setValue(example.source);
    loading = false;
    currentExample = example.name;
    state.dirty = false;
    $("#dirty-dot").hidden = true;
    $("#file-name").textContent = example.name;
    if (state.result) {
      state.stale = true;
      $("#stale-note").hidden = false;
      unmarkErrors();
      applyStepHighlight();
    }
    scheduleCheck(0);
    setStatus(`Loaded ${example.name}. Press Run.`, null);
  });

  // ----------------------------------------------------------- pane divider

  const workspace = $("#workspace");
  const divider = $("#divider");

  function setSplit(percent) {
    const p = clamp(percent, 25, 75);
    workspace.style.setProperty("--split", `${p}%`);
    divider.setAttribute("aria-valuenow", String(Math.round(p)));
    editor.refresh();
    if (state.tab === "ir") drawIrEdges();
    try { localStorage.setItem("minilang.split", String(p)); } catch { /* storage unavailable */ }
  }

  divider.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    divider.setPointerCapture(e.pointerId);
    workspace.classList.add("is-resizing");
    const rect = workspace.getBoundingClientRect();
    const move = (ev) => setSplit(((ev.clientX - rect.left) / rect.width) * 100);
    const stop = () => {
      workspace.classList.remove("is-resizing");
      divider.removeEventListener("pointermove", move);
      divider.removeEventListener("pointerup", stop);
      divider.removeEventListener("pointercancel", stop);
    };
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", stop);
    divider.addEventListener("pointercancel", stop);
  });
  divider.addEventListener("dblclick", () => setSplit(50));
  divider.addEventListener("keydown", (e) => {
    const now = Number(divider.getAttribute("aria-valuenow"));
    if (e.key === "ArrowLeft") { e.preventDefault(); setSplit(now - 2); }
    if (e.key === "ArrowRight") { e.preventDefault(); setSplit(now + 2); }
  });

  try {
    const saved = Number(localStorage.getItem("minilang.split"));
    if (saved) setSplit(saved);
  } catch { /* storage unavailable */ }

  // ------------------------------------------------ bridge for game.js

  /** Put new code in the editor (a level, or the playground again) and clear old results. */
  function loadSource(text, title) {
    loading = true;
    editor.setValue(text);
    loading = false;
    state.dirty = false;
    $("#dirty-dot").hidden = true;
    if (title) $("#file-name").textContent = title;
    clearResults();
    scheduleCheck(0);
  }

  window.MiniLang = {
    on(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    dom: { $, $$, el },
    getSource: () => editor.getValue(),
    getTitle: () => $("#file-name").textContent,
    loadSource,
    setRunContext(ctx) {
      state.runContext = ctx;
      stdinPanel.hidden = !!ctx;   // a level supplies its own input
      scheduleCheck(0);
    },
    run,
    selectTab,
    goToLine: (line) => editor.goTo(line),
    refreshEditor: () => editor.refresh(),
  };

  selectTab("output");
  noticeInput();
  scheduleCheck(0);

  // Deep links from the learning section, e.g. /play?example=dataflow.ml&tab=ir:
  // open that example, run it, and show that stage.
  const params = new URLSearchParams(location.search);
  const linked = examples.find((ex) => ex.name === params.get("example"));
  if (params.has("code")) {
    loadSource(params.get("code"), "lesson.ml");
    if (params.has("stdin")) {
      stdinBox.value = params.get("stdin");
      updateStdinMeta();
      stdinPanel.open = true;
    }
    noticeInput();
    const tab = params.get("tab");
    if (TABS.includes(tab) && tab !== "level") selectTab(tab);
    run();
  } else if (linked) {
    if (linked.name !== select.value) {
      select.value = linked.name;
      select.dispatchEvent(new Event("change"));
    }
    const tab = params.get("tab");
    if (TABS.includes(tab) && tab !== "level") selectTab(tab);
    run();
  }
})();
