/* MiniLang Playground: game layer.
   Levels (challenges and bug hunts), stars, XP and achievements.
   The server runs and scores every attempt (POST /check); this file only keeps
   score and draws the game UI. Progress lives in localStorage. */
(() => {
  "use strict";

  const ML = window.MiniLang;
  if (!ML) return;
  const { $, $$, el } = ML.dom;

  const LEVELS = JSON.parse($("#levels-data").textContent);
  const BY_ID = Object.fromEntries(LEVELS.map((lv) => [lv.id, lv]));
  const TRACKS = [
    { id: "challenge", name: "Challenges", blurb: "Write programs that pass hidden tests. Extra stars go to small and fast code." },
    { id: "bug", name: "Bug hunts", blurb: "Broken programs, in pipeline order: lexer, parser, compiler, VM, logic. Extra stars go to the smallest fix." },
  ];
  const STAGE_NAMES = { lex: "lexer error", parse: "parse error", compile: "compile error", runtime: "runtime error", logic: "wrong output" };

  const fmt = (n) => Number(n).toLocaleString();
  const CHECK_KEYS = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘ ⇧ ↵" : "Ctrl ⇧ ↵";

  // ----------------------------------------------------------------- progress

  const STORE_KEY = "minilang.progress.v1";
  const blankProgress = () => ({ version: 1, levels: {}, achievements: {}, errorsSeen: [] });

  function loadProgress() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY));
      if (saved && saved.version === 1) return { ...blankProgress(), ...saved };
    } catch { /* storage blocked or corrupt: start fresh */ }
    return blankProgress();
  }

  let progress = loadProgress();

  function saveProgress() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(progress)); } catch { /* storage blocked */ }
  }

  function levelProgress(id) {
    if (!progress.levels[id]) progress.levels[id] = { stars: [false, false, false], best: null, code: null, attempts: 0 };
    return progress.levels[id];
  }

  const starsOf = (id) => (progress.levels[id] ? progress.levels[id].stars : [false, false, false]);
  const starCount = (id) => starsOf(id).filter(Boolean).length;
  const solved = (id) => starsOf(id)[0];
  const totalStars = () => LEVELS.reduce((sum, lv) => sum + starCount(lv.id), 0);

  function trackLevels(track) {
    return LEVELS.filter((lv) => lv.track === track);
  }

  function isUnlocked(id) {
    const list = trackLevels(BY_ID[id].track);
    const i = list.findIndex((lv) => lv.id === id);
    return i === 0 || solved(list[i - 1].id);
  }

  function nextLevel(id) {
    const list = trackLevels(BY_ID[id].track);
    const i = list.findIndex((lv) => lv.id === id);
    return list[i + 1] || null;
  }

  // ------------------------------------------------------------ XP and ranks

  const STAR_XP = 50;
  const RANKS = [
    [0, "Token Tinkerer"], [100, "Parse Padawan"], [300, "Tree Climber"], [600, "Bytecode Builder"],
    [1000, "Stack Wrangler"], [1500, "Jump Juggler"], [2100, "VM Whisperer"], [2800, "Compiler Wizard"],
  ];

  const ACHIEVEMENTS = [
    { id: "hello", name: "Hello, VM", desc: "Run a program without any errors.", xp: 25 },
    { id: "pipeline", name: "Full Pipeline", desc: "Open the Tokens, AST, Bytecode and Output of one run.", xp: 25 },
    { id: "rewind", name: "Time Traveller", desc: "Step backwards through an execution.", xp: 25 },
    { id: "deep", name: "Down the Rabbit Hole", desc: "Reach a call depth of 5 or more.", xp: 50 },
    { id: "optimizer", name: "Optimizer's Friend", desc: "Have the optimizer remove 10 or more instructions.", xp: 50 },
    { id: "crash", name: "Crash Test Dummy", desc: "Hit a runtime error.", xp: 25 },
    { id: "collector", name: "Error Collector", desc: "Meet a lexer, parse, compile and runtime error.", xp: 75 },
    { id: "stuck", name: "Stuck in a Loop", desc: "Run into the VM's step limit.", xp: 25 },
    { id: "loops", name: "Loop de Loop", desc: "Run a program that uses for, while, break and continue.", xp: 50 },
    { id: "first-star", name: "First Star", desc: "Earn a star on any level.", xp: 25 },
    { id: "flawless", name: "Flawless", desc: "Earn all three stars on one level.", xp: 50 },
    { id: "champion", name: "Challenge Champion", desc: "Solve every challenge.", xp: 100 },
    { id: "exterminator", name: "Exterminator", desc: "Fix every bug hunt.", xp: 100 },
    { id: "perfectionist", name: "Perfectionist", desc: "Earn every star in the game.", xp: 200 },
  ];
  const ACH_BY_ID = Object.fromEntries(ACHIEVEMENTS.map((a) => [a.id, a]));

  function totalXp() {
    const fromAchievements = Object.keys(progress.achievements)
      .reduce((sum, id) => sum + (ACH_BY_ID[id] ? ACH_BY_ID[id].xp : 0), 0);
    return totalStars() * STAR_XP + fromAchievements;
  }

  function rankFor(xp) {
    let i = 0;
    while (i + 1 < RANKS.length && xp >= RANKS[i + 1][0]) i++;
    const [floor, title] = RANKS[i];
    const next = RANKS[i + 1] || null;
    return {
      level: i + 1, title, floor,
      next: next ? next[0] : null,
      nextTitle: next ? next[1] : null,
      fraction: next ? (xp - floor) / (next[0] - floor) : 1,
    };
  }

  // ------------------------------------------------------------------ toasts

  function toast(title, body, kind = "info") {
    const region = $("#toasts");
    while (region.children.length >= 4) region.firstElementChild.remove();
    const node = el("div", { class: `toast toast-${kind}`, role: "status" },
      el("p", { class: "toast-title" }, title),
      body ? el("p", { class: "toast-body" }, body) : null);
    region.append(node);
    setTimeout(() => {
      node.classList.add("is-leaving");
      setTimeout(() => node.remove(), 250);
    }, 4200);
  }

  /** Run fn, then announce any rank change it caused. */
  function withRankWatch(fn) {
    const before = rankFor(totalXp());
    fn();
    const after = rankFor(totalXp());
    if (after.level > before.level) toast(`Level up! You're now level ${after.level}`, after.title, "rank");
    updateHud();
  }

  function unlock(id) {
    if (progress.achievements[id] || !ACH_BY_ID[id]) return;
    progress.achievements[id] = Date.now();
    saveProgress();
    const a = ACH_BY_ID[id];
    toast(`Achievement: ${a.name}`, `${a.desc} +${a.xp} XP`, "achievement");
  }

  // --------------------------------------------------------------------- HUD

  function starIcons(stars, cls = "") {
    return el("span", { class: `stars ${cls}`, "aria-label": `${stars.filter(Boolean).length} of 3 stars` },
      stars.map((on) => el("span", { class: `star${on ? " is-on" : ""}`, "aria-hidden": "true" }, "★")));
  }

  function updateHud() {
    const xp = totalXp();
    const rank = rankFor(xp);
    $("#levels-count").textContent = `${totalStars()}/${LEVELS.length * 3}`;
    $("#levels-btn").setAttribute("aria-label", `Levels, ${totalStars()} of ${LEVELS.length * 3} stars`);
    $("#xp-level").textContent = `Lv ${rank.level}`;
    $("#xp-fill").style.transform = `scaleX(${rank.fraction})`;
    $("#xp-text").textContent = `${fmt(xp)} XP`;
    $("#xp-btn").title = rank.next
      ? `${rank.title}. ${fmt(rank.next - xp)} XP to level ${rank.level + 1}`
      : `${rank.title}. Top rank reached`;
    if (active) {
      const badge = $("#badge-level");
      badge.hidden = false;
      badge.textContent = "★".repeat(starCount(active)) + "☆".repeat(3 - starCount(active));
      badge.setAttribute("aria-label", `${starCount(active)} of 3 stars`);
    }
  }

  // ------------------------------------------------------------- level mode

  let active = null;         // id of the level being played, or null in the playground
  let playground = null;     // the playground's code and title, restored on exit
  let lastCheck = null;      // last /check response for the active level
  let checking = false;

  function enterLevel(id) {
    const lv = BY_ID[id];
    if (!lv || !isUnlocked(id)) return;
    if (!active) playground = { source: ML.getSource(), title: ML.getTitle() };
    active = id;
    lastCheck = null;
    const saved = levelProgress(id).code;
    ML.loadSource(saved !== null && saved !== undefined ? saved : lv.starter, `${lv.code} · ${lv.title}`);
    ML.setRunContext({ level: id });

    document.body.classList.add("is-level-mode");
    $("#tab-level").hidden = false;
    $("#check").hidden = false;
    $("#level-actions").hidden = false;
    $("#example-picker").hidden = true;

    renderLevelPanel();
    updateHud();
    ML.selectTab("level");
    closeDialog($("#levels-dialog"));
    ML.refreshEditor();
  }

  function exitLevel() {
    if (!active) return;
    active = null;
    lastCheck = null;
    ML.setRunContext(null);
    if (playground) ML.loadSource(playground.source, playground.title);
    document.body.classList.remove("is-level-mode");
    $("#tab-level").hidden = true;
    $("#badge-level").hidden = true;
    $("#check").hidden = true;
    $("#level-actions").hidden = true;
    $("#example-picker").hidden = false;
    ML.selectTab("output");
    ML.refreshEditor();
  }

  $("#level-exit").addEventListener("click", exitLevel);
  $("#level-reset").addEventListener("click", () => {
    const lv = BY_ID[active];
    if (!lv || !confirm(`Reset ${lv.code} to its starting code? Your changes to this level will be lost.`)) return;
    levelProgress(active).code = null;
    saveProgress();
    ML.loadSource(lv.starter, `${lv.code} · ${lv.title}`);
    lastCheck = null;
    renderLevelPanel();
    ML.selectTab("level");
  });

  // Remember each level's code as you type.
  let saveTimer = null;
  ML.on("change", () => {
    if (!active) return;
    const id = active;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      levelProgress(id).code = ML.getSource();
      saveProgress();
    }, 400);
  });

  // ----------------------------------------------------------------- check

  async function check() {
    if (!active || checking) return;
    checking = true;
    const button = $("#check");
    button.disabled = true;
    button.classList.add("is-busy");
    $(".btn-check-label", button).textContent = "Checking…";

    const id = active;
    const source = ML.getSource();
    let response = null;
    try {
      const res = await fetch("/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level: id, source }),
      });
      const body = await res.json().catch(() => null);
      response = res.ok && body && "stars" in body
        ? body
        : { failed: (body && body.error) || `The server answered with HTTP ${res.status}.` };
    } catch {
      response = { failed: "The page couldn't reach app.py. Check that the server is still running." };
    }

    checking = false;
    button.disabled = false;
    button.classList.remove("is-busy");
    $(".btn-check-label", button).textContent = "Check";
    if (active !== id) return; // the player left the level while it was checking

    lastCheck = response;
    if (!response.failed) recordCheck(id, source, response);
    renderLevelPanel();
    ML.selectTab("level");
    // Scroll only the Level panel (scrollIntoView would also scroll the page itself).
    const scroller = $("#level-body");
    const report = $(".report", scroller);
    if (report) {
      const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
      scroller.scrollTo({ top: report.offsetTop - 16, behavior: smooth ? "smooth" : "auto" });
    }
  }

  function recordCheck(id, source, result) {
    const lv = BY_ID[id];
    const lp = levelProgress(id);

    // Everything that adds XP happens inside withRankWatch, so a level-up is noticed.
    withRankWatch(() => {
      lp.code = source;
      lp.attempts += 1;
      const newStars = result.stars.map((on, i) => on && !lp.stars[i]);
      lp.stars = lp.stars.map((on, i) => on || result.stars[i]); // each star, once earned, stays
      if (result.passed) {
        const m = result.metrics;
        const b = lp.best;
        lp.best = {
          size: b && b.size !== null ? Math.min(b.size, m.size) : m.size,
          steps: b ? Math.min(b.steps, m.steps) : m.steps,
          changes: m.changes === null ? null : b && b.changes !== null ? Math.min(b.changes, m.changes) : m.changes,
        };
      }
      saveProgress();

      const gained = newStars.filter(Boolean).length;
      if (gained) {
        const next = nextLevel(id);
        const unlocks = result.stars[0] && next && newStars[0] ? ` ${next.code} unlocked.` : "";
        toast(`${"★".repeat(starCount(id))}${"☆".repeat(3 - starCount(id))}  ${lv.code} · ${lv.title}`,
          `+${gained * STAR_XP} XP for ${gained} new star${gained === 1 ? "" : "s"}.${unlocks}`, "star");
      }
      if (result.stars[0]) unlock("first-star");
      if (starCount(id) === 3) unlock("flawless");
      if (trackLevels("challenge").every((l) => solved(l.id))) unlock("champion");
      if (trackLevels("bug").every((l) => solved(l.id))) unlock("exterminator");
      if (LEVELS.every((l) => starCount(l.id) === 3)) unlock("perfectionist");
    });
  }

  $("#check").addEventListener("click", check);
  ML.on("check-shortcut", check);

  // ------------------------------------------------------------ level panel

  function renderLevelPanel() {
    const body = $("#level-body");
    const lv = BY_ID[active];
    if (!lv) return body.replaceChildren();
    const lp = levelProgress(lv.id);
    const trackName = lv.track === "bug" ? "Bug hunt" : "Challenge";

    const facts = [];
    if (lv.inputs.length) {
      facts.push(el("li", null, "Ready-made variables: ",
        lv.inputs.map((name, i) => [i ? ", " : "", el("code", null, name)]),
        ". They're set before your first line runs."));
    }
    if (lv.epilogue) {
      facts.push(el("li", null, "After your code, each test runs a line like ", el("code", null, lv.epilogue), "."));
    }
    facts.push(el("li", null, `Check runs ${lv.tests_count} tests with different inputs, so hard-coding the answer won't pass.`));

    const expected = lv.example.expected;
    body.replaceChildren(...[
      el("header", { class: "level-head" },
        el("div", { class: "level-kicker" },
          el("span", { class: `track-chip track-${lv.track}` }, `${trackName} ${lv.code}`),
          lv.bug_stage ? el("span", { class: "stage-chip" }, `Starts with: ${STAGE_NAMES[lv.bug_stage]}`) : null),
        el("div", { class: "level-title-row" },
          el("h3", { class: "level-title" }, lv.title),
          starIcons(lp.stars, "stars-lg"))),
      el("p", { class: "level-brief" }, lv.brief),
      el("ul", { class: "level-facts" }, facts),

      el("section", { class: "level-section" },
        el("h4", { class: "section-label" }, "Example"),
        el("div", { class: "example" },
          el("div", null, el("span", { class: "example-key" }, "Input"),
            el("code", null, lv.example.label || "none")),
          el("div", null, el("span", { class: "example-key" }, "Expected output"),
            expected.length ? el("pre", { class: "example-out" }, expected.join("\n"))
              : el("span", { class: "muted" }, "nothing")))),

      el("section", { class: "level-section" },
        el("h4", { class: "section-label" }, "Stars"),
        el("ol", { class: "criteria" },
          lv.criteria.map((text, i) => el("li", { class: lp.stars[i] ? "is-earned" : null },
            el("span", { class: `star${lp.stars[i] ? " is-on" : ""}`, "aria-hidden": "true" }, "★"),
            el("span", null, text),
            lp.stars[i] ? el("span", { class: "visually-hidden" }, " (earned)") : null))),
        lp.best ? el("p", { class: "level-best" }, bestText(lv, lp.best)) : null),

      el("details", { class: "hint" },
        el("summary", null, "Need a hint?"),
        el("p", null, lv.hint)),

      el("div", { class: "level-cta" },
        el("button", { type: "button", class: "btn-check btn-check-inline", onclick: check }, "Check solution"),
        el("span", { class: "muted" }, "or press ", el("kbd", { class: "kbd" }, CHECK_KEYS), ". Run tries just the example.")),

      lastCheck ? checkReport(lv, lastCheck) : null,
    ].filter(Boolean)); // replaceChildren would print a null as the text "null"
  }

  function bestText(lv, best) {
    const parts = [];
    if (lv.track === "bug" && best.changes !== null) parts.push(`${best.changes} changed line${best.changes === 1 ? "" : "s"}`);
    if (best.size !== null) parts.push(`${best.size} instructions`);
    parts.push(`${fmt(best.steps)} VM steps`);
    return `Your best: ${parts.join(" · ")}`;
  }

  function checkReport(lv, result) {
    if (result.failed) {
      return el("section", { class: "report report-fail", role: "alert" },
        el("p", { class: "report-title" }, "Couldn't check your code"),
        el("p", null, result.failed));
    }
    const passedCount = result.tests.filter((t) => t.passed).length;
    const m = result.metrics;
    const p = result.par;
    const rows = [];
    if (lv.track === "bug") rows.push(["Changed lines", m.changes, p.changes, result.stars[1]]);
    else rows.push(["Bytecode size", m.size, p.size, result.stars[1]]);
    rows.push(["VM steps", m.steps, p.steps, result.stars[2]]);

    return el("section", { class: `report ${result.passed ? "report-pass" : "report-fail"}`, "aria-live": "polite" },
      el("div", { class: "report-head" },
        el("p", { class: "report-title" },
          result.passed ? `All ${result.tests.length} tests passed` : `${passedCount} of ${result.tests.length} tests passed`),
        starIcons(result.stars)),

      el("ul", { class: "test-list" }, result.tests.map(testRow)),

      result.passed
        ? el("table", { class: "metrics" },
            el("thead", null, el("tr", null,
              el("th", { scope: "col" }, ""), el("th", { scope: "col" }, "You"),
              el("th", { scope: "col" }, "Par"), el("th", { scope: "col" }, "Star"))),
            el("tbody", null, rows.map(([name, you, par, earned]) =>
              el("tr", null,
                el("th", { scope: "row" }, name),
                el("td", null, you === null ? "–" : fmt(you)),
                el("td", null, fmt(par)),
                el("td", null, el("span", { class: `star${earned ? " is-on" : ""}` }, "★"),
                  el("span", { class: "visually-hidden" }, earned ? "earned" : "not earned"))))))
        : el("p", { class: "report-note" }, "Fix the failing tests to earn the first star. The size and speed stars only count once every test passes."),

      result.passed && nextLevel(lv.id)
        ? el("button", { type: "button", class: "btn-next", onclick: () => enterLevel(nextLevel(lv.id).id) },
            `Next: ${nextLevel(lv.id).code} · ${nextLevel(lv.id).title} →`)
        : result.passed
          ? el("button", { type: "button", class: "btn-next", onclick: openLevels },
              `Every ${lv.track === "bug" ? "bug hunt" : "challenge"} done. Pick another level →`)
          : null);
  }

  function testRow(t) {
    const icon = el("span", { class: `test-icon ${t.passed ? "is-pass" : "is-fail"}`, "aria-hidden": "true" }, t.passed ? "✓" : "✕");
    const head = el("div", { class: "test-head" }, icon,
      el("code", null, t.label || "no inputs"),
      el("span", { class: "visually-hidden" }, t.passed ? "passed" : "failed"));
    if (t.passed) return el("li", { class: "test is-pass" }, head);

    const detail = [];
    if (t.error) {
      const where = t.error.in_test_code ? " in the test code" : t.error.line ? ` on line ${t.error.line}` : "";
      detail.push(el("p", { class: "test-error" },
        `${(STAGE_NAMES[t.error.stage] || "error").replace(/^./, (c) => c.toUpperCase())}${where}: ${t.error.message}`));
    }
    detail.push(el("div", { class: "test-diff" },
      el("div", null, el("span", { class: "example-key" }, "Expected"),
        el("pre", null, t.expected.length ? t.expected.join("\n") : "(nothing)")),
      el("div", null, el("span", { class: "example-key" }, "Your output"),
        el("pre", null, t.output.length ? t.output.join("\n") : "(nothing)"))));
    return el("li", { class: "test is-fail" }, head, detail);
  }

  // ----------------------------------------------------------- level picker

  function openLevels() {
    renderLevelList();
    openDialog($("#levels-dialog"));
  }

  function renderLevelList() {
    $("#levels-sub").textContent = `${totalStars()} of ${LEVELS.length * 3} stars earned`;
    $("#levels-playground").hidden = !active;
    $("#levels-list").replaceChildren(...TRACKS.map((track) => {
      const list = trackLevels(track.id);
      return el("section", { class: "track" },
        el("div", { class: "track-head" },
          el("h3", { class: "track-name" }, track.name),
          el("p", { class: "track-blurb" }, track.blurb)),
        el("ol", { class: "level-grid" }, list.map((lv, i) => {
          const unlocked = isUnlocked(lv.id);
          const stars = starsOf(lv.id);
          const status = !unlocked ? `Solve ${list[i - 1].code} to unlock`
            : stars[0] ? `${stars.filter(Boolean).length} of 3 stars`
              : levelProgress(lv.id).attempts ? "Not solved yet" : "New";
          return el("li", null,
            el("button", {
              type: "button",
              class: `level-card${unlocked ? "" : " is-locked"}${lv.id === active ? " is-current" : ""}${stars[0] ? " is-solved" : ""}`,
              disabled: !unlocked,
              "aria-label": `${lv.code} ${lv.title}. ${status}`,
              onclick: () => enterLevel(lv.id),
            },
            el("span", { class: "card-top" },
              el("span", { class: "card-code" }, lv.code),
              unlocked ? starIcons(stars) : el("span", { class: "lock", "aria-hidden": "true" })),
            el("span", { class: "card-title" }, lv.title),
            el("span", { class: "card-status" }, status)));
        })));
    }));
    // Lock icons: static markup, set here because el() only creates HTML elements, not SVG.
    for (const lock of $$(".lock", $("#levels-list"))) {
      lock.innerHTML = '<svg viewBox="0 0 16 16" width="13" height="13"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';
    }
  }

  $("#levels-btn").addEventListener("click", openLevels);
  $("#levels-playground").addEventListener("click", () => {
    exitLevel();
    closeDialog($("#levels-dialog"));
  });

  // ---------------------------------------------------------------- profile

  function renderProfile() {
    const xp = totalXp();
    const rank = rankFor(xp);
    const solvedCount = LEVELS.filter((lv) => solved(lv.id)).length;
    const unlockedCount = ACHIEVEMENTS.filter((a) => progress.achievements[a.id]).length;

    $("#profile-body").replaceChildren(
      el("div", { class: "rank" },
        el("span", { class: "rank-badge" }, `Lv ${rank.level}`),
        el("div", { class: "rank-info" },
          el("p", { class: "rank-title" }, rank.title),
          el("div", { class: "rank-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100",
            "aria-valuenow": String(Math.round(rank.fraction * 100)), "aria-label": "Progress to the next level" },
            el("span", { class: "rank-fill", style: `transform: scaleX(${rank.fraction})` })),
          el("p", { class: "rank-next" }, rank.next
            ? `${fmt(xp)} XP · ${fmt(rank.next - xp)} XP to level ${rank.level + 1}, ${rank.nextTitle}`
            : `${fmt(xp)} XP · top rank reached`))),
      el("dl", { class: "stats" },
        el("div", null, el("dt", null, "Stars"), el("dd", null, `${totalStars()} / ${LEVELS.length * 3}`)),
        el("div", null, el("dt", null, "Levels solved"), el("dd", null, `${solvedCount} / ${LEVELS.length}`)),
        el("div", null, el("dt", null, "Achievements"), el("dd", null, `${unlockedCount} / ${ACHIEVEMENTS.length}`))),
      el("h3", { class: "section-label" }, "Achievements"),
      el("ul", { class: "achievements" }, ACHIEVEMENTS.map((a) => {
        const got = Boolean(progress.achievements[a.id]);
        return el("li", { class: `achievement${got ? " is-unlocked" : ""}` },
          el("span", { class: "ach-icon", "aria-hidden": "true" }, got ? "★" : "·"),
          el("div", null,
            el("p", { class: "ach-name" }, a.name, el("span", { class: "visually-hidden" }, got ? " (unlocked)" : " (locked)")),
            el("p", { class: "ach-desc" }, a.desc)),
          el("span", { class: "ach-xp" }, `+${a.xp} XP`));
      })));
  }

  $("#xp-btn").addEventListener("click", () => {
    renderProfile();
    openDialog($("#profile-dialog"));
  });

  $("#progress-reset").addEventListener("click", () => {
    if (!confirm("Reset all stars, XP, achievements and saved level code? This can't be undone.")) return;
    progress = blankProgress();
    saveProgress();
    if (active) exitLevel();
    updateHud();
    renderProfile();
    toast("Progress reset", "Every level is back to the start.");
  });

  // --------------------------------------------------------------- dialogs

  function openDialog(dialog) {
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function closeDialog(dialog) {
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  for (const dialog of $$("dialog")) {
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog || e.target.closest("[data-close]")) closeDialog(dialog); // backdrop or ✕
    });
  }

  // ---------------------------------------------------------- achievements

  let currentTab = "output";
  let tabsSeen = null; // tabs opened since the last run; null until something has run

  ML.on("result", ({ result }) => {
    tabsSeen = new Set([currentTab]);
    withRankWatch(() => {
      if (result.ok) unlock("hello");

      const stage = result.error && result.error.stage;
      if (["lex", "parse", "compile", "runtime"].includes(stage)) {
        if (!progress.errorsSeen.includes(stage)) {
          progress.errorsSeen.push(stage);
          saveProgress();
        }
        if (progress.errorsSeen.length === 4) unlock("collector");
      }
      if (stage === "runtime") unlock("crash");
      if (stage === "runtime" && /step limit/.test(result.error.message)) unlock("stuck");

      const opt = result.optimizer || {};
      if (opt.before && opt.after !== null && opt.before - opt.after >= 10) unlock("optimizer");

      if ((result.trace || []).some((s) => (s.frames || []).length >= 5)) unlock("deep");

      if (result.ok && result.tokens) {
        const words = new Set(result.tokens.filter((t) => t.type === "KEYWORD").map((t) => t.value));
        if (["for", "while", "break", "continue"].every((w) => words.has(w))) unlock("loops");
      }
    });
  });

  ML.on("tab", (tab) => {
    currentTab = tab;
    if (!tabsSeen) return;
    tabsSeen.add(tab);
    if (["tokens", "ast", "bytecode", "output"].every((t) => tabsSeen.has(t))) withRankWatch(() => unlock("pipeline"));
  });

  ML.on("step-back", () => withRankWatch(() => unlock("rewind")));

  updateHud();
})();
