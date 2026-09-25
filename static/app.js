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
    compile: "Compile error",
    runtime: "Runtime error",
    input: "Input error",
    network: "Can't reach the server",
    server: "Server error",
  };

  const FLOW_OPS = new Set(["JUMP", "JUMP_IF_FALSE", "CALL", "RET", "HALT"]);
  const MATH_OPS = new Set(["ADD", "SUB", "MUL", "DIV", "NEG", "EQ", "NE", "LT", "GT", "LE", "GE", "NOT"]);
  const TARGET_OPS = new Set(["JUMP", "JUMP_IF_FALSE", "CALL"]);

  // ------------------------------------------------------------------- editor

  const editor = createEditor($("#source"));

  function createEditor(textarea) {
    if (!window.CodeMirror || !CodeMirror.defineSimpleMode) return createFallbackEditor(textarea);

    CodeMirror.defineSimpleMode("minilang", {
      start: [
        { regex: /#.*/, token: "comment" },
        { regex: /(func)(\s+)([A-Za-z_]\w*)/, token: ["keyword", null, "def"] },
        { regex: /(?:if|else|while|for|break|continue|return|print|func|and|or|not)\b/, token: "keyword" },
        { regex: /\d+/, token: "number" },
        { regex: /[A-Za-z_]\w*(?=\s*\()/, token: "variable-2" },
        { regex: /[A-Za-z_]\w*/, token: "variable" },
        { regex: /==|!=|<=|>=|[-+*/<>=]/, token: "operator" },
        { regex: /[{}()]/, token: "bracket" },
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
      extraKeys: {
        Tab: (c) => c.execCommand(c.somethingSelected() ? "indentMore" : "insertSoftTab"),
        "Shift-Tab": "indentLess",
      },
    });

    const marks = {}; // kind -> { handle, cls }
    const validLine = (line) => Number.isInteger(line) && line >= 1 && line <= cm.lineCount();

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
    astView: "tree",
    bcView: "optimized",
    stale: false,     // editor changed since the last run
    dirty: false,     // editor differs from the loaded example
    running: false,
  };

  const examples = JSON.parse($("#examples-data").textContent);

  // Keyboard hint text
  const shortcut = isMac ? "⌘ ↵" : "Ctrl ↵";
  $("#run-kbd").textContent = shortcut;
  $("#empty-kbd").textContent = shortcut;
  $("#run").title = `Run (${isMac ? "⌘" : "Ctrl"}+Enter)`;

  // --------------------------------------------------------------------- tabs

  const TABS = ["tokens", "ast", "bytecode", "output"];

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
    applyStepHighlight();
    if (name === "bytecode") scrollCurrentInstructionIntoView();
  }

  for (const t of TABS) {
    $(`#tab-${t}`).addEventListener("click", () => selectTab(t));
  }
  $(".tabs").addEventListener("keydown", (e) => {
    const i = TABS.indexOf(state.tab);
    let next = null;
    if (e.key === "ArrowRight") next = TABS[(i + 1) % TABS.length];
    else if (e.key === "ArrowLeft") next = TABS[(i - 1 + TABS.length) % TABS.length];
    else if (e.key === "Home") next = TABS[0];
    else if (e.key === "End") next = TABS[TABS.length - 1];
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
        body: JSON.stringify({ source: editor.getValue() }),
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
      trace_truncated: false, error: { stage, message, line: null },
    };
  }

  $("#run").addEventListener("click", run);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      run();
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
    editor.unmark("error");
    if (result.error && result.error.line) editor.mark("error", result.error.line, "cm-line-error");

    renderTokens();
    renderAst();
    renderBytecode();
    renderOutput();
    updateBadges();
    updateStatus(elapsed);

    if (result.error) selectTab("output"); // errors are always shown in the Output panel
    applyStepHighlight();
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
      const where = r.error.line ? ` on line ${r.error.line}` : "";
      setStatus(`${STAGE_LABEL[r.error.stage] || "Error"}${where}`, "error");
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
    if (r.trace && r.trace.length) bits.push(`${fmt(r.trace.length)}${r.trace_truncated ? "+" : ""} VM steps`);
    if (r.output && r.output.length) bits.push(`${plural(r.output.length, "line")} printed`);
    $("#status-meta").textContent = bits.join("  ·  ");
  }

  function updateBadges() {
    const r = state.result;
    const set = (id, text, isError = false) => {
      const badge = $(`#badge-${id}`);
      badge.hidden = text === null;
      badge.textContent = text ?? "";
      badge.classList.toggle("is-error", isError);
    };
    set("tokens", r.tokens ? fmt(r.tokens.length) : null);
    set("ast", null);
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
    body.replaceChildren();
    $("#ast-toolbar").hidden = !r.ast;
    if (!r.ast) return body.append(blocked("syntax tree"));

    for (const seg of $$("[data-ast-view]")) seg.setAttribute("aria-pressed", String(seg.dataset.astView === state.astView));
    $("#ast-tree-actions").hidden = state.astView !== "tree";

    if (state.astView === "text") {
      body.append(el("pre", { class: "ast-text" }, r.ast_dump));
    } else {
      body.append(el("ul", { class: "ast-tree", "aria-label": "Abstract syntax tree" }, astItem(r.ast)));
    }
  }

  for (const seg of $$("[data-ast-view]")) {
    seg.addEventListener("click", () => {
      state.astView = seg.dataset.astView;
      renderAst();
    });
  }
  $("#ast-expand").addEventListener("click", () => {
    $$("#ast-body .ast-item").forEach((item) => setCollapsed(item, false));
  });
  $("#ast-collapse").addEventListener("click", () => {
    // Keep the Program root open so every top-level statement stays visible.
    $$("#ast-body .ast-item").forEach((item, i) => {
      if (i > 0 && $(":scope > .ast-row > .ast-toggle", item)) setCollapsed(item, true);
    });
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
    const callee = ins.op === "CALL" && code[ins.arg] ? code[ins.arg].label : null;
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

    const slot = $("#error-slot");
    slot.replaceChildren();
    if (r.error) slot.append(errorBox(r.error, r.output.length));

    renderStepper();
  }

  function errorBox(err, printedLines) {
    const hints = {
      lex: "The lexer found a character that isn't part of MiniLang.",
      parse: "The code doesn't match MiniLang's grammar. Check for a missing ';', brace or bracket.",
      compile: "The syntax is fine, but a compile-time check failed.",
      runtime: printedLines
        ? "The program started, printed the output above, then stopped here. Step through below to see the state just before the error."
        : "The program compiled but stopped while running. Step through below to see the state just before the error.",
    };
    return el("div", { class: "error-box", role: "alert" },
      el("div", { class: "error-head" },
        el("span", { class: "error-stage" }, STAGE_LABEL[err.stage] || "Error"),
        err.line
          ? el("button", {
              class: "error-line", type: "button", title: "Show this line in the editor",
              onclick: () => editor.goTo(err.line),
            }, `line ${err.line}`)
          : null),
      el("p", { class: "error-message" }, err.message),
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
          el("span", null, String(value)),
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

    // Output printed up to this step.
    $("#step-output").textContent = r.output.slice(0, s.lines_printed).join("\n");

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
            el("tr", { class: previous && previous[name] !== value ? "is-changed" : null },
              el("th", { scope: "row" }, name),
              el("td", null, String(value))))))
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

  for (const id of ["#tokens-body", "#ast-body", "#bytecode-body"]) {
    const root = $(id);
    root.addEventListener("mouseover", (e) => {
      const row = e.target.closest("[data-line]");
      const line = row && Number(row.dataset.line);
      if (line) editor.mark("hover", line, "cm-line-hover");
      else editor.unmark("hover");
    });
    root.addEventListener("mouseleave", () => editor.unmark("hover"));
    root.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      const row = e.target.closest("[data-line]");
      const line = row && Number(row.dataset.line);
      if (line) editor.reveal(line);
    });
  }

  // ----------------------------------------------------- editor bookkeeping

  let loading = false; // true while an example is being loaded into the editor

  editor.onChange(() => {
    if (loading) return;
    if (!state.dirty) {
      state.dirty = true;
      $("#dirty-dot").hidden = false;
    }
    if (state.result && !state.stale) {
      state.stale = true;
      $("#stale-note").hidden = false;
      editor.unmark("error");
      applyStepHighlight();
      setStatus("Edited since last run. Press Run to update.", null);
    }
  });

  editor.onCursor((line, col) => {
    $("#cursor-pos").textContent = `Ln ${line}, Col ${col}`;
  });

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
      editor.unmark("error");
      applyStepHighlight();
    }
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

  selectTab("output");
})();
