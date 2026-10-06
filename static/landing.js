/* MiniLang landing page: the boot screen, the windows, and a live stack machine.
   Everything here sits on real data: the boot self-test and the machine both run
   programs through POST /run, and the numbers come from the server. */
(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const data = JSON.parse($("#landing-data").textContent);
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isDesktop = () => matchMedia("(min-width: 1100px) and (min-height: 640px)").matches;
  const pad4 = (n) => String(n).padStart(4, "0");
  const showValue = (v) => (Array.isArray(v) ? `[${v.map(showValue).join(", ")}]` : String(v));

  // Storage can be blocked (private windows, strict settings): never let that break the page.
  const storage = (area) => ({
    get(key) { try { return window[area].getItem(key); } catch { return null; } },
    set(key, value) { try { window[area].setItem(key, value); } catch { /* unavailable */ } },
    remove(key) { try { window[area].removeItem(key); } catch { /* unavailable */ } },
  });
  const local = storage("localStorage");
  const session = storage("sessionStorage");

  async function runProgram(source) {
    const started = performance.now();
    const response = await fetch("/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    const body = await response.json();
    if (!response.ok || !("ok" in body)) throw new Error(body.error || `HTTP ${response.status}`);
    return { body, ms: performance.now() - started };
  }

  // -------------------------------------------------------------- scramble

  // Text "decodes" from random glyphs, left to right, like a terminal catching up.
  const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+=/<>{}";

  function scramble(el, duration = 700) {
    if (reduceMotion || el.childElementCount) return;
    const text = el.dataset.text || (el.dataset.text = el.textContent);
    const start = performance.now();
    cancelAnimationFrame(el._scramble);
    const frame = (now) => {
      const progress = Math.min(1, (now - start) / duration);
      const shown = Math.floor(progress * text.length);
      let out = text.slice(0, shown);
      for (let i = shown; i < text.length; i++) {
        out += /\s/.test(text[i]) ? text[i] : GLYPHS[(Math.random() * GLYPHS.length) | 0];
      }
      el.textContent = out;
      if (progress < 1) el._scramble = requestAnimationFrame(frame);
    };
    el._scramble = requestAnimationFrame(frame);
  }

  function scrambleAll() {
    $$("[data-scramble]").forEach((el, i) => setTimeout(() => scramble(el, el.tagName === "P" ? 1100 : 600), i * 70));
  }

  for (const link of $$(".index-list a")) {
    const label = $("[data-scramble-hover]", link);
    if (label) link.addEventListener("mouseenter", () => scramble(label, 320));
  }

  // --------------------------------------------------------------- windows

  // Each window can be collapsed with its button and, on a wide screen, dragged by its
  // grip (or moved with the arrow keys). Positions are offsets from where the layout put
  // the window, snapped to the background grid, and remembered in this browser.
  const LAYOUT_KEY = "minilang.windows.v1";
  const SNAP = 20;
  let layout = {};
  try { layout = JSON.parse(local.get(LAYOUT_KEY)) || {}; } catch { layout = {}; }
  const saveLayout = () => local.set(LAYOUT_KEY, JSON.stringify(layout));
  const windows = $$(".win[data-win]");

  function place(win) {
    const saved = layout[win.dataset.win] || {};
    win.style.transform = isDesktop() && (saved.x || saved.y) ? `translate(${saved.x || 0}px, ${saved.y || 0}px)` : "";
  }

  function setCollapsed(win, collapsed) {
    const button = $(".win-btn[aria-controls]", win);
    if (!button) return;
    const title = $(".win-title", win).dataset.text || $(".win-title", win).textContent;
    win.classList.toggle("is-collapsed", collapsed);
    button.setAttribute("aria-expanded", String(!collapsed));
    button.setAttribute("aria-label", `${collapsed ? "Expand" : "Collapse"} ${title.replace(/[[\]]/g, "")}`);
  }

  /** Keep a dragged window on screen: at least its title bar stays reachable. */
  function clampOffset(win, x, y, base) {
    const rect = base;
    const minX = -rect.left + 8, maxX = innerWidth - rect.right - 8;
    const minY = -rect.top + 8, maxY = innerHeight - rect.top - 40;
    return [Math.max(minX, Math.min(maxX, x)), Math.max(minY, Math.min(maxY, y))];
  }

  function moveTo(win, x, y) {
    const id = win.dataset.win;
    layout[id] = { ...(layout[id] || {}), x, y };
    place(win);
  }

  for (const win of windows) {
    const id = win.dataset.win;
    const toggle = $(".win-btn[aria-controls]", win);
    setCollapsed(win, !!(layout[id] && layout[id].collapsed));
    if (toggle) {
      toggle.addEventListener("click", () => {
        const collapsed = !win.classList.contains("is-collapsed");
        setCollapsed(win, collapsed);
        layout[id] = { ...(layout[id] || {}), collapsed };
        saveLayout();
      });
    }

    const handle = $(".win-handle", win);
    handle.addEventListener("pointerdown", (e) => {
      if (!isDesktop() || e.button !== 0) return;
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      const saved = layout[id] || {};
      const startX = saved.x || 0, startY = saved.y || 0;
      const rect = win.getBoundingClientRect();
      const base = { left: rect.left - startX, right: rect.right - startX, top: rect.top - startY };
      win.classList.add("is-dragging");
      const move = (ev) => {
        const [x, y] = clampOffset(win, startX + ev.clientX - e.clientX, startY + ev.clientY - e.clientY, base);
        moveTo(win, x, y);
      };
      const stop = () => {
        const saved2 = layout[id] || {};
        moveTo(win, Math.round((saved2.x || 0) / SNAP) * SNAP, Math.round((saved2.y || 0) / SNAP) * SNAP);
        saveLayout();
        win.classList.remove("is-dragging");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
    handle.addEventListener("keydown", (e) => {
      const step = { ArrowLeft: [-SNAP, 0], ArrowRight: [SNAP, 0], ArrowUp: [0, -SNAP], ArrowDown: [0, SNAP] }[e.key];
      if (!step || !isDesktop()) return;
      e.preventDefault();
      const saved = layout[id] || {};
      moveTo(win, (saved.x || 0) + step[0], (saved.y || 0) + step[1]);
      saveLayout();
    });
  }

  function syncWindows() {
    const desktop = isDesktop();
    for (const win of windows) {
      const handle = $(".win-handle", win);
      handle.classList.toggle("is-draggable", desktop);
      handle.tabIndex = desktop ? 0 : -1;
      handle.title = desktop ? "Drag to move, or use the arrow keys" : "";
      place(win);
    }
  }

  function resetWindows() {
    layout = {};
    saveLayout();
    windows.forEach((win) => setCollapsed(win, false));
    syncWindows();
  }

  addEventListener("resize", syncWindows);
  syncWindows();

  // --------------------------------------------------------- the machine

  // Replays the VM trace that /run returns for the demo program: the program counter,
  // the operand stack (drawn as a tower), the variables and the output, step by step.
  const STEP_MS = 420;
  const machine = { trace: [], code: [], output: [], step: 0, timer: null, playing: false };
  const vmToggle = $("#vm-toggle");

  function renderSource() {
    $("#vm-source").replaceChildren(...data.demo.replace(/\n$/, "").split("\n").map((text, i) => {
      const line = document.createElement("span");
      line.className = "line";
      line.dataset.line = String(i + 1);
      line.textContent = text || " ";
      return line;
    }));
  }

  function renderCode() {
    $("#vm-code").replaceChildren(...machine.code.map((ins) => {
      const li = document.createElement("li");
      li.dataset.addr = String(ins.addr);
      const addr = document.createElement("span");
      addr.textContent = pad4(ins.addr);
      const op = document.createElement("span");
      op.className = "op";
      op.textContent = ins.arg === null || ins.arg === undefined ? ins.op : `${ins.op} ${ins.arg}`;
      li.append(addr, op);
      return li;
    }));
  }

  let shownStack = [];

  function renderStack(stack) {
    const list = $("#m-stack");
    let same = 0;
    while (same < shownStack.length && same < stack.length && showValue(shownStack[same]) === showValue(stack[same])) same++;
    // Keep the cells that didn't change; pop the rest and push the new ones (they animate in).
    $$("li", list).slice(same).forEach((li) => li.remove());
    if (!stack.length) {
      list.replaceChildren();
      const empty = document.createElement("li");
      empty.className = "is-empty";
      empty.textContent = "empty";
      list.append(empty);
    } else {
      $$("li.is-empty", list).forEach((li) => li.remove());
      for (const value of stack.slice(same).slice(-5)) {
        const li = document.createElement("li");
        li.textContent = showValue(value);
        list.append(li);
      }
    }
    shownStack = stack.slice();
  }

  function showStep(i) {
    const s = machine.trace[i];
    if (!s) return;
    machine.step = i;
    $("#m-addr").textContent = pad4(s.addr);
    $("#m-op").textContent = s.arg === null || s.arg === undefined ? s.op : `${s.op} ${s.arg}`;
    renderStack(s.stack);

    for (const line of $$("#vm-source .line")) line.classList.toggle("is-current", Number(line.dataset.line) === s.line);
    const code = $("#vm-code");
    let current = null;
    for (const li of $$("li", code)) {
      const on = Number(li.dataset.addr) === s.addr;
      li.classList.toggle("is-current", on);
      if (on) current = li;
    }
    if (current) code.scrollTop = Math.max(0, current.offsetTop - code.clientHeight / 2 + current.offsetHeight / 2);

    const vars = $("#vm-vars");
    const entries = Object.entries(s.variables);
    vars.replaceChildren(...(entries.length ? entries : [["–", ""]]).flatMap(([name, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = name;
      const dd = document.createElement("dd");
      dd.textContent = showValue(value);
      return [dt, dd];
    }));
    $("#vm-out").textContent = machine.output.slice(0, s.lines_printed).join("\n");
  }

  function tick() {
    const last = machine.step >= machine.trace.length - 1;
    showStep(last ? 0 : machine.step + 1);
    const pause = machine.step === machine.trace.length - 1 ? 2400 : STEP_MS;   // linger on the result
    machine.timer = setTimeout(tick, pause);
  }

  function setPlaying(on) {
    machine.playing = on && machine.trace.length > 0;
    clearTimeout(machine.timer);
    if (machine.playing) machine.timer = setTimeout(tick, STEP_MS);
    vmToggle.setAttribute("aria-pressed", String(!machine.playing));
    vmToggle.setAttribute("aria-label", machine.playing ? "Pause the machine" : "Play the machine");
    $("#vm-toggle-icon").textContent = machine.playing ? "❚❚" : "▶";
  }

  vmToggle.addEventListener("click", () => setPlaying(!machine.playing));
  // Don't burn CPU in a background tab.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(machine.timer);
    else if (machine.playing) machine.timer = setTimeout(tick, STEP_MS);
  });

  async function startMachine() {
    renderSource();
    renderStack([]);
    const status = $("#vm-status");
    try {
      const { body, ms } = await runProgram(data.demo);
      setCompiler(true, ms);
      if (!body.ok) throw new Error(body.error ? body.error.message : "the demo program failed");
      machine.trace = body.trace;
      machine.code = body.bytecode;
      machine.output = body.output;
      renderCode();
      showStep(0);
      const { before, after } = body.optimizer;
      status.textContent = `Compiled on the server in ${Math.round(ms)} ms: ${after} instructions `
        + `(${before} before optimizing), ${body.steps} VM steps, prints ${body.output.join(", ")}.`;
      setPlaying(!reduceMotion);   // with reduced motion, it waits for Play
    } catch {
      setCompiler(false);
      status.classList.add("is-error");
      status.textContent = "The compiler isn't answering. Start it with python app.py, then reload this page.";
      setPlaying(false);
      vmToggle.disabled = true;
    }
  }

  // ------------------------------------------------------------ readouts

  function setCompiler(online, ms) {
    $("#s-compiler").textContent = online ? "Online" : "Offline";
    $("#s-ping").textContent = online ? `${Math.max(1, Math.round(ms))} ms` : "--";
  }

  function clock() {
    $("#s-time").textContent = new Date().toLocaleTimeString([], { hour12: false });
  }
  clock();
  setInterval(clock, 1000);

  // Stars earned in the playground (game.js keeps them in localStorage).
  let stars = 0;
  try {
    const progress = JSON.parse(local.get("minilang.progress.v1"));
    for (const level of Object.values((progress && progress.levels) || {})) stars += (level.stars || []).filter(Boolean).length;
  } catch { stars = 0; }
  $("#s-stars").textContent = `${stars} / ${data.max_stars}`;
  $("#stars-chip").textContent = `${stars} / ${data.max_stars} stars`;
  $("#stars-meter").style.setProperty("--fill", String(Math.min(1, stars / data.max_stars)));

  // ----------------------------------------------------------- boot screen

  // A power-on self test that is real: it compiles and runs `print 6 * 7;`, and each
  // stage reports what it produced. Shown once per browser session; any key skips it.
  const BOOT_KEY = "minilang.booted";
  const SELF_TEST = "print 6 * 7;";
  const boot = $("#boot");
  const log = $("#boot-log");
  let booting = false;

  const dots = (label, width = 18) => `${label} `.padEnd(width, ".") + " ";

  function addLine(parts) {
    const row = document.createElement("span");
    for (const [text, cls] of parts) {
      const span = document.createElement("span");
      if (cls) span.className = cls;
      span.textContent = text;
      row.append(span);
    }
    row.append("\n");
    log.append(row);
  }

  async function runBoot() {
    booting = true;
    boot.hidden = false;
    document.documentElement.classList.add("is-booting");
    log.replaceChildren();
    $("#boot-enter").hidden = true;
    const wait = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));

    addLine([[`MINILANG-V1 BIOS (C) ${data.course}`, "hi"]]);
    addLine([["PRESS ANY KEY ...... SKIP"]]);
    addLine([[""]]);
    addLine([["POWER-ON SELF TEST: ", "hi"], [SELF_TEST, "hi code"]]);

    let r = null;
    try { r = (await runProgram(SELF_TEST)).body; } catch { r = null; }
    const stages = [
      ["LEXER", r && r.tokens && `${r.tokens.length} TOKENS`],
      ["PARSER", r && r.ast && "SYNTAX TREE"],
      ["SEMANTIC", r && r.symbols && "SYMBOL TABLE"],
      ["TYPE CHECKER", r && r.types && "TYPES INFERRED"],
      ["IR", r && r.ir && `${r.ir.stats.blocks} BASIC BLOCK${r.ir.stats.blocks === 1 ? "" : "S"}`],
      ["COMPILER", r && r.bytecode && `${r.bytecode.length} INSTRUCTIONS`],
      ["STACK VM", r && r.ok && `PRINTED ${r.output.join(" ")}`],
    ];
    for (const [name, result] of stages) {
      if (!booting) return;
      await wait(110);
      addLine([[dots(name)], [(result || "NO ANSWER").padEnd(16, " ")], [result ? "OK" : "FAIL", result ? "ok" : "fail"]]);
    }
    if (!r) addLine([["\nSTART THE SERVER WITH  python app.py  AND RELOAD", "fail"]]);
    await wait(150);
    if (!booting) return;
    $("#boot-enter").hidden = false;
    $("#boot-enter").focus();
  }

  function endBoot() {
    if (boot.hidden) return;
    booting = false;
    boot.hidden = true;
    document.documentElement.classList.remove("is-booting");
    session.set(BOOT_KEY, "1");
    scrambleAll();
  }

  boot.addEventListener("click", endBoot);   // keys are handled below, so a skipped key does nothing else

  // ------------------------------------------------------------- shortcuts

  document.addEventListener("keydown", (e) => {
    if (!boot.hidden) { e.preventDefault(); endBoot(); return; }
    const target = e.target instanceof Element ? e.target : document.body;
    if (e.ctrlKey || e.metaKey || e.altKey || target.closest("input, textarea, select")) return;
    const key = e.key.toLowerCase();
    if (key === "p") location.href = "/play";
    else if (key === "l") location.href = "/learn";
    else if (key === "g") location.href = "/play#levels";
    else if (key === "r") resetWindows();
    else if (key === "b") { session.remove(BOOT_KEY); runBoot(); }
    else if (key === " " && !target.closest("button, a")) { e.preventDefault(); setPlaying(!machine.playing); }
  });

  // ------------------------------------------------------------------ start

  if (session.get(BOOT_KEY)) scrambleAll();
  else runBoot();
  startMachine();
})();
