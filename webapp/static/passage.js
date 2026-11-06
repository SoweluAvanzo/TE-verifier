/* webapp/static/passage.js: fills the source viewer (templates/passage.html).
   Everything is set through textContent: stored text is never read as HTML. */
(function () {
  const id = document.body.dataset.passageId;
  const status = document.getElementById("passage-status");
  const set = (name, value) => { document.getElementById(name).textContent = value || ""; };

  function link(name, href) {
    const a = document.getElementById(name);
    if (href) { a.href = href; a.hidden = false; }
  }

  function show(p) {
    document.title = `${p.cite}: source`;
    set("p-title", p.title);
    set("p-byline", [p.authors, p.year, p.venue].filter(Boolean).join(", "));
    set("p-where", [p.section, p.locator, p.page ? `p. ${p.page}` : ""].filter(Boolean).join(", "));
    set("p-evidence", p.evidence_type);
    set("p-group", p.source_group);
    set("p-how", p.how_to_read);
    set("p-context", p.context);
    const box = document.getElementById("p-text");
    for (const s of p.section_passages) {
      const el = document.createElement("p");
      el.textContent = s.text;
      if (s.passage_id === p.passage_id) {
        el.className = "passage-current";
        el.id = "current";
      }
      box.appendChild(el);
    }
    if (p.previous_id) link("p-prev", `/literature/passage/${p.previous_id}`);
    if (p.next_id) link("p-next", `/literature/passage/${p.next_id}`);
    link("p-original", p.original_url);
    status.hidden = true;
    document.getElementById("passage").hidden = false;
    document.getElementById("current")?.scrollIntoView({ block: "center" });
  }

  fetch(`/agent/literature/passages/${encodeURIComponent(id)}`, { credentials: "same-origin" })
    .then(async (res) => {
      if (res.status === 401) { window.location.href = "/login"; return; }
      if (res.status === 404) {
        status.textContent = "This passage no longer exists: the library was re-indexed after this link was written.";
        return;
      }
      if (!res.ok) throw new Error(String(res.status));
      show(await res.json());
    })
    .catch(() => { status.textContent = "The passage could not be loaded. Try again shortly."; });
})();
