/* MiniLang interface effects, shared by every page.

   - A cursor of four violet corner brackets. They glide after the pointer, and snap
     to frame whatever button, link or window grip it is over, sometimes with a label.
   - A trail: as the pointer travels, it drops small squares stamped with their x / y
     position, joined to the pointer by a dashed line (landing and learning pages only;
     the playground sets <body data-cursor="lite"> and gets just the brackets).
   - Text that scrambles, one character at a time, when you hover it.

   Only for a mouse or trackpad. Touch screens keep their normal behaviour, and with
   reduced motion there is no trail and nothing scrambles. Everything here is
   decoration: it is hidden from screen readers and never takes a click. */
(() => {
  "use strict";

  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+=/<>{}";

  // -------------------------------------------------------- scrambling text

  // Each character sits in its own box, sized by an invisible copy of itself, so the
  // text keeps its exact width while random glyphs flicker through it. Screen readers
  // get the real text from a visually hidden copy.
  function prepare(el) {
    if (el.dataset.scrambleReady) return;
    const text = el.textContent;
    el.dataset.scrambleReady = "1";
    el.textContent = "";
    const real = document.createElement("span");
    real.className = "visually-hidden";
    real.textContent = text;
    const shown = document.createElement("span");
    shown.setAttribute("aria-hidden", "true");
    for (const ch of text) {
      const box = document.createElement("span");
      box.className = "sc";
      const size = document.createElement("span");
      size.className = "sc-size";
      size.textContent = ch;
      const glyph = document.createElement("span");
      glyph.className = "sc-glyph";
      glyph.textContent = ch;
      box.append(size, glyph);
      shown.append(box);
    }
    el.append(real, shown);
  }

  function scramble(el, { delay = 0, step = 32, base = 140 } = {}) {
    if (reduceMotion) return;
    prepare(el);
    const glyphs = Array.from(el.querySelectorAll(".sc-glyph"));
    const start = performance.now() + delay;
    cancelAnimationFrame(el._fx);
    let last = 0;
    const frame = (now) => {
      let busy = false;
      if (now - last > 45) {   // a new random glyph about 20 times a second
        last = now;
        glyphs.forEach((g, i) => {
          const real = g.previousSibling.textContent;
          if (now >= start + base + i * step || !real.trim()) {
            g.textContent = real;
          } else {
            g.textContent = now < start ? real : GLYPHS[(Math.random() * GLYPHS.length) | 0];
            busy = true;
          }
        });
      } else {
        busy = true;
      }
      if (busy) el._fx = requestAnimationFrame(frame);
    };
    el._fx = requestAnimationFrame(frame);
  }

  // [data-hover-scramble] text scrambles when the pointer enters its host: the nearest
  // link, button or window around it (or the element itself with data-hover-scramble="self").
  for (const el of document.querySelectorAll("[data-hover-scramble]")) {
    prepare(el);
    const host = el.dataset.hoverScramble === "self" ? el : el.closest("a, button, .win") || el;
    host.addEventListener("pointerenter", (e) => { if (e.pointerType !== "touch") scramble(el); });
  }

  window.FX = { scramble, prepare };

  // ----------------------------------------------------------------- cursor

  if (!finePointer) return;

  const mode = document.body.dataset.cursor === "lite" ? "lite" : "full";
  const TARGETS = "a[href], button:not(:disabled), select, summary, [role='tab'], .win-handle.is-draggable, [data-cursor-label]";
  const TEXTUAL = "input, textarea, .CodeMirror, [contenteditable='true']";
  const PAD = 5;          // how far the brackets sit outside a framed element
  const IDLE = 9;         // half-size of the brackets around a bare pointer
  const TRAIL_EVERY = 110;   // pixels of travel between trail markers
  const TRAIL_MAX = 8;

  const layer = document.createElement("div");
  layer.className = `cursor is-${mode}`;
  layer.setAttribute("aria-hidden", "true");
  const corners = ["tl", "tr", "bl", "br"].map((name) => {
    const c = document.createElement("span");
    c.className = `cursor-corner ${name}`;
    layer.append(c);
    return c;
  });
  const label = document.createElement("span");
  label.className = "cursor-label";
  layer.append(label);

  const trail = document.createElement("div");
  trail.className = "cursor-trail";
  trail.setAttribute("aria-hidden", "true");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "cursor-line");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  svg.append(line);
  trail.append(svg);
  if (mode === "full" && !reduceMotion) document.body.append(trail);
  document.body.append(layer);
  document.documentElement.classList.add(`has-cursor-${mode}`);

  const mouse = { x: -100, y: -100, inside: false, down: false };
  const box = { x: -100, y: -100, w: 0, h: 0 };   // where the brackets are drawn now
  let target = null;          // the element being framed, if any
  let overText = false;
  let lastMark = null;        // {x, y, el} of the newest trail marker
  let travelled = 0;
  let running = false;

  function labelFor(el) {
    if (!el) return "";
    if (el.dataset.cursorLabel) return el.dataset.cursorLabel;
    if (el.classList.contains("win-handle")) return "Drag";
    if (el.matches("a[href^='http']")) return "Open ↗";
    return "";
  }

  function wanted() {
    if (target && target.isConnected) {
      // A link that covers a whole card asks for the card to be framed (data-cursor-frame).
      const r = (target.closest("[data-cursor-frame]") || target).getBoundingClientRect();
      return { x: r.left - PAD, y: r.top - PAD, w: r.width + 2 * PAD, h: r.height + 2 * PAD };
    }
    const s = mouse.down ? IDLE - 3 : IDLE;
    return { x: mouse.x - s, y: mouse.y - s, w: 2 * s, h: 2 * s };
  }

  function draw() {
    const [tl, tr, bl, br] = corners;
    tl.style.transform = `translate3d(${box.x}px, ${box.y}px, 0)`;
    tr.style.transform = `translate3d(${box.x + box.w}px, ${box.y}px, 0)`;
    bl.style.transform = `translate3d(${box.x}px, ${box.y + box.h}px, 0)`;
    br.style.transform = `translate3d(${box.x + box.w}px, ${box.y + box.h}px, 0)`;
    label.style.transform = `translate3d(${mouse.x}px, ${mouse.y + 24}px, 0) translateX(-50%)`;
    if (lastMark && lastMark.el.isConnected) {
      line.setAttribute("x1", lastMark.x);
      line.setAttribute("y1", lastMark.y);
      line.setAttribute("x2", mouse.x);
      line.setAttribute("y2", mouse.y);
      svg.classList.add("is-on");
    } else {
      svg.classList.remove("is-on");
    }
  }

  function tick() {
    const goal = wanted();
    const k = reduceMotion ? 1 : 0.28;   // ease towards the goal each frame
    let moving = false;
    for (const key of ["x", "y", "w", "h"]) {
      const d = goal[key] - box[key];
      box[key] = Math.abs(d) < 0.3 ? goal[key] : box[key] + d * k;
      if (box[key] !== goal[key]) moving = true;
    }
    draw();
    // Keep animating while the brackets catch up or a trail line is showing; then rest.
    if (moving || (lastMark && lastMark.el.isConnected)) requestAnimationFrame(tick);
    else running = false;
  }

  function wake() {
    if (!running) {
      running = true;
      requestAnimationFrame(tick);
    }
  }

  function dropMark(x, y) {
    const mark = document.createElement("div");
    mark.className = "cursor-mark";
    mark.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    const sq = document.createElement("span");
    sq.className = "cursor-mark-box";
    const xy = document.createElement("span");
    xy.className = "cursor-mark-xy";
    xy.textContent = `${Math.round(x)}\n${Math.round(y)}`;
    mark.append(sq, xy);
    trail.append(mark);
    mark.addEventListener("animationend", () => mark.remove());
    const marks = trail.querySelectorAll(".cursor-mark");
    if (marks.length > TRAIL_MAX) marks[0].remove();
    lastMark = { x, y, el: mark };
  }

  function retarget(el) {
    overText = !!(el && el.closest(TEXTUAL));
    const next = overText ? null : el && el.closest(TARGETS);
    if (next !== target) {
      target = next;
      const text = labelFor(target);
      label.textContent = text;
      layer.classList.toggle("has-label", !!text);
      layer.classList.toggle("is-framing", !!target);
    }
    layer.classList.toggle("is-text", overText);
  }

  addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch") return;
    const first = !mouse.inside;
    if (!first && mode === "full" && !reduceMotion && !target) {
      travelled += Math.hypot(e.clientX - mouse.x, e.clientY - mouse.y);
      if (travelled >= TRAIL_EVERY) {
        travelled = 0;
        dropMark(e.clientX, e.clientY);
      }
    }
    mouse.x = e.clientX;
    mouse.y = e.clientY;
    if (first) {   // appear where the pointer is, without sliding in from a corner
      const g = wanted();
      Object.assign(box, g);
    }
    mouse.inside = true;
    layer.classList.add("is-visible");
    retarget(e.target instanceof Element ? e.target : null);
    wake();
  }, { passive: true });

  addEventListener("pointerdown", (e) => {
    if (e.pointerType === "touch") return;
    mouse.down = true;
    layer.classList.add("is-down");
    wake();
  });
  addEventListener("pointerup", () => {
    mouse.down = false;
    layer.classList.remove("is-down");
    wake();
  });
  // The framed element can move under a still pointer (scrolling, a dragged window).
  addEventListener("scroll", wake, { passive: true, capture: true });
  document.addEventListener("mouseout", (e) => {
    if (e.relatedTarget) return;   // still inside the page, just moving between elements
    mouse.inside = false;
    layer.classList.remove("is-visible");
  });
  // A click can replace the framed element (a dialog opens, a tab is re-rendered).
  document.addEventListener("click", () => setTimeout(() => {
    if (target && !target.isConnected) retarget(document.elementFromPoint(mouse.x, mouse.y));
    const text = labelFor(target);   // a button's label can change when it's clicked (Play / Pause)
    label.textContent = text;
    layer.classList.toggle("has-label", !!text);
    wake();
  }, 0));
})();
