/* Runnable examples in the learning section: editable code with syntax colours.

   A language lesson's example runs the whole program (POST /run). A compiler chapter's
   demo (<figure class="ex" data-view="tokens">) shows what one stage makes of the
   code instead (POST /stage), as the same text the server first rendered.

   Each <figure class="ex"> arrives with its code in a textarea and the output the
   server got when it rendered the page. This script colours the code (a highlighted
   copy sits under a transparent textarea), and wires Run, Reset and the playground
   link. Without JavaScript the examples still show their code and output. */
(() => {
  "use strict";

  const KEYWORDS = new Set(["if", "else", "while", "for", "break", "continue", "return",
                            "print", "input", "func", "and", "or", "not"]);
  const TOKENS = /(#[^\n]*)|([A-Za-z_]\w*)(?=(\s*\()?)|(\d+)|(==|!=|<=|>=|[-+*/%]=|[-+*/%<>=])|([{}()[\];,])/g;
  const STAGES = { lex: "Lexer error", parse: "Parse error", semantic: "Semantic error", type: "Type error",
                   compile: "Compile error", runtime: "Runtime error", input: "Input error",
                   network: "Can't reach the server", server: "Server error" };

  const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  /** MiniLang source as HTML with a span around each kind of token. */
  function highlight(code) {
    let html = "";
    let last = 0;
    code.replace(TOKENS, (match, comment, word, call, number, op, punct, offset) => {
      html += escape(code.slice(last, offset));
      let cls = "tk-punct";
      if (comment) cls = "tk-comment";
      else if (word) cls = KEYWORDS.has(word) ? "tk-kw" : call ? "tk-call" : "tk-var";
      else if (number) cls = "tk-num";
      else if (op) cls = "tk-op";
      html += `<span class="${cls}">${escape(match)}</span>`;
      last = offset + match.length;
      return match;
    });
    return html + escape(code.slice(last)) + "\n";   // the newline keeps the last line's height
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /** The same markup the server renders in templates/guide/_macros.html. */
  function renderResult(r, expect) {
    const parts = [];
    if (r.errors && r.errors.length) {
      const box = el("div", "ex-error");
      const label = el("p", "ex-label",
        STAGES[r.errors[0].stage] ? `${STAGES[r.errors[0].stage]}${r.errors.length > 1 ? `s · ${r.errors.length}` : ""}` : "Error");
      if (expect) label.append(" ", el("span", "ex-purpose", "on purpose"));
      const list = el("ul", "ex-messages");
      for (const e of r.errors) {
        const li = el("li");
        if (e.line) li.append(el("span", "ex-line", `line ${e.line}`));
        li.append(el("span", null, e.message));
        list.append(li);
      }
      box.append(label, list);
      parts.push(box);
    }
    if ((r.output && r.output.length) || !(r.errors && r.errors.length)) {
      parts.push(el("p", "ex-label", "Output"));
      const pre = el("pre", "ex-out");
      if (r.output && r.output.length) pre.textContent = r.output.join("\n");
      else pre.append(el("span", "ex-none", "nothing was printed"));
      parts.push(pre);
    }
    if (r.warnings && r.warnings.length) {
      const list = el("ul", "ex-warnings");
      for (const w of r.warnings) {
        const li = el("li");
        li.append(el("span", "ex-line", `line ${w.line}`), el("span", null, `Warning: ${w.message}`));
        list.append(li);
      }
      parts.push(list);
    }
    return parts;
  }

  /** A stage demo's result: any errors, then the stage's text (templates/guide/_macros.html). */
  function renderStage(r, expect) {
    const parts = renderResult({ errors: r.errors, output: [], warnings: r.warnings }, expect)
      .filter((node) => !node.classList.contains("ex-label") && !node.classList.contains("ex-out"));
    if (r.text || !(r.errors && r.errors.length)) {
      const label = el("p", "ex-label", r.label || "Result");
      const pre = el("pre", "ex-out ex-stage-out");
      if (r.text) pre.textContent = r.text;
      else pre.append(el("span", "ex-none", "nothing"));
      const at = parts.findIndex((node) => node.classList.contains("ex-warnings"));
      parts.splice(at < 0 ? parts.length : at, 0, label, pre);
    }
    return parts;
  }

  for (const ex of document.querySelectorAll(".ex")) {
    const area = ex.querySelector(".ex-code");
    const hl = ex.querySelector(".ex-hl");
    const result = ex.querySelector(".ex-result");
    const runButton = ex.querySelector("[data-run]");
    const resetButton = ex.querySelector("[data-reset]");
    const open = ex.querySelector("[data-open]");
    const stdinField = ex.querySelector(".ex-stdin input");
    const original = area.value;
    const originalStdin = stdinField ? stdinField.value : "";
    const expect = ex.dataset.expect || "";
    const view = ex.dataset.view || "";

    function sync() {
      hl.innerHTML = highlight(area.value);
      area.rows = Math.max(1, area.value.split("\n").length);
      hl.style.transform = `translateX(${-area.scrollLeft}px)`;
      const changed = area.value !== original || (stdinField && stdinField.value !== originalStdin);
      resetButton.hidden = !changed;
      const url = new URL("/play", location.origin);
      url.searchParams.set("code", area.value);
      if (stdinField && stdinField.value.trim()) url.searchParams.set("stdin", stdinField.value);
      if (open.dataset.tab) url.searchParams.set("tab", open.dataset.tab);
      open.href = url.pathname + url.search;
    }

    async function run() {
      runButton.disabled = true;
      runButton.classList.add("is-busy");
      runButton.textContent = "Running…";
      let r;
      try {
        const stdin = stdinField ? stdinField.value : "";
        const response = await fetch(view ? "/stage" : "/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(view ? { source: area.value, stdin, view } : { source: area.value, stdin, trace: false }),
        });
        const body = await response.json();
        r = response.ok && ("ok" in body || "view" in body) ? body
          : { errors: [{ stage: "server", message: body.error || `HTTP ${response.status}` }], output: [] };
      } catch {
        r = { errors: [{ stage: "network", message: "The page couldn't reach app.py. Is the server still running?" }], output: [] };
      }
      const purpose = area.value === original ? expect : "";
      result.replaceChildren(...(view ? renderStage(r, purpose) : renderResult(r, purpose)));
      runButton.disabled = false;
      runButton.classList.remove("is-busy");
      runButton.textContent = "Run";
      ex.classList.remove("is-flash");
      void ex.offsetWidth;   // restart the flash animation
      ex.classList.add("is-flash");
    }

    ex.classList.add("is-enhanced");
    area.addEventListener("input", sync);
    area.addEventListener("scroll", () => { hl.style.transform = `translateX(${-area.scrollLeft}px)`; });
    area.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        run();
      }
    });
    if (stdinField) {
      stdinField.addEventListener("input", sync);
      stdinField.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(); } });
    }
    runButton.addEventListener("click", run);
    resetButton.addEventListener("click", () => {
      area.value = original;
      if (stdinField) stdinField.value = originalStdin;
      sync();
      run();
    });
    sync();
  }
})();
