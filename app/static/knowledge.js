(() => {
  let documents = [];
  let selected = new Set();
  let initialized = false;
  let pending = null;
  let importing = false;

  function setBusy(busy) {
    for (const id of ["knowledge-send", "knowledge-local-search", "knowledge-file-input"]) byId(id).disabled = busy || importing;
    byId("knowledge-stop").hidden = !busy;
    byId("knowledge-stop").disabled = false;
    byId("knowledge-path-form").querySelectorAll("input,button").forEach((item) => { item.disabled = busy || importing; });
    byId("knowledge-documents").querySelectorAll("input").forEach((item) => { item.disabled = busy; });
  }

  async function refresh() {
    try {
      const data = await api("/api/knowledge/documents");
      documents = data.documents;
      if (!initialized) { selected = new Set(documents.map((item) => item.id)); initialized = true; }
      byId("knowledge-count").textContent = documents.length;
      const list = byId("knowledge-documents"); list.replaceChildren();
      if (!documents.length) list.append(element("p", "small muted", "尚未导入资料，请添加文本型 PDF。"));
      for (const document of documents) {
        const card = element("article", "knowledge-document"); const label = element("label");
        const input = element("input"); input.type = "checkbox"; input.checked = selected.has(document.id); input.disabled = state.busy;
        input.addEventListener("change", () => input.checked ? selected.add(document.id) : selected.delete(document.id));
        label.append(input, element("strong", "", document.title));
        card.append(label, element("p", "", `${document.format.toUpperCase()} · ${document.page_count} 页/段 · ${document.chunk_count} 个片段 · 已就绪`));
        const open = element("button", "text-button", "查看原始文档 ↗"); open.addEventListener("click", () => openSource({document_id: document.id, title: document.title, page: 1, page_label: document.format === "pdf" ? "PDF 第 1 页" : "文本第 1 段", excerpt: ""}));
        card.append(open); list.append(card);
      }
    } catch (error) { byId("knowledge-import-status").textContent = error.message; }
  }

  async function importDocument(path, file) {
    if (state.busy || importing) return toast("请等待当前任务完成。");
    importing = true; setBusy(state.busy);
    byId("knowledge-import-status").textContent = "正在本地解析文档并建立检索索引…";
    try {
      let document;
      if (file) { const body = new FormData(); body.append("file", file); document = await api("/api/knowledge/uploads", {method: "POST", body}); }
      else document = await post("/api/knowledge/import", {path});
      selected.add(document.id);
      await refresh();
      byId("knowledge-import-status").textContent = document.duplicate ? "该文档已在知识库中，无需重复导入。" : `已导入 ${document.page_count} 页/段、${document.chunk_count} 个片段。`;
      toast(document.duplicate ? "资料已存在，已选中。" : "资料已就绪，可以开始提问。");
    } catch (error) { byId("knowledge-import-status").textContent = error.message; toast(error.message); }
    finally { importing = false; setBusy(state.busy); }
  }

  async function openSource(citation) {
    try {
      const data = await api(`/api/knowledge/documents/${citation.document_id}/pages/${citation.page}`);
      byId("knowledge-source-title").textContent = data.document.title;
      byId("knowledge-source-label").textContent = `${data.page_label} · ${data.document.filename}`;
      byId("knowledge-source-text").textContent = citation.excerpt || "此处打开的是整页原文。";
      byId("knowledge-source-page-text").textContent = data.text;
      byId("knowledge-source-image").parentElement.hidden = !data.image_url;
      if (data.image_url) byId("knowledge-source-image").src = data.image_url;
      byId("knowledge-source-download").href = data.document.source_url;
      byId("knowledge-source-dialog").showModal();
    } catch (error) { toast(error.message); }
  }

  function showEvidence(hits, emptyMessage) {
    const list = byId("knowledge-evidence-list"); list.replaceChildren();
    if (!hits.length) { list.append(element("p", "knowledge-status", emptyMessage || "所选资料没有检索到相关依据。")); return; }
    for (const hit of hits) {
      if (!hit.citation_id) continue;
      state.citations.set(hit.citation_id, hit);
      const card = element("article", "knowledge-hit");
      const label = element("div", "knowledge-hit-label"); label.append(element("span", "", hit.page_label), element("span", "", "原文证据"));
      const open = element("button", "text-button", "查看原始页与完整文本 ↗"); open.addEventListener("click", () => openSource(hit));
      card.append(label, element("h3", "", hit.title), element("pre", "", hit.excerpt), open); list.append(card);
    }
  }

  function addKnowledgeMessage(role, text, citations = []) {
    byId("knowledge-welcome")?.remove();
    const article = element("article", `chat-message ${role}`); article.append(element("div", "message-label", role === "user" ? "你 · 专业问题" : "BIFB · 有据问答"));
    const body = element("div", "message-body"); renderMarkdown(body, text); article.append(body);
    if (citations.length) {
      const links = element("div", "citation-links");
      for (const citation of citations) { const button = element("button", "", citation.page_label + " · 原文"); button.addEventListener("click", () => openSource(citation)); links.append(button); }
      article.append(links);
    }
    byId("knowledge-messages").append(article); byId("knowledge-messages").scrollTop = byId("knowledge-messages").scrollHeight;
    return article;
  }

  function selectedIds() {
    const ids = [...selected].filter((id) => documents.some((item) => item.id === id));
    if (!ids.length) throw new Error("请至少勾选一篇参考资料。");
    return ids;
  }

  async function localSearch() {
    if (state.busy || importing) return;
    const query = byId("knowledge-input").value.trim();
    if (!query) return toast("请输入要检索的专业问题。");
    try {
      const document_ids = selectedIds();
      byId("knowledge-progress").textContent = "正在本地检索原文，不调用 LLM…";
      const result = await post("/api/knowledge/search", {query, document_ids});
      showEvidence(result.hits, result.message);
      byId("knowledge-progress").textContent = `找到 ${result.hits.length} 个原文片段。检索分数只表示相关度，请核验适用条件。`;
    } catch (error) { toast(error.message); byId("knowledge-progress").textContent = error.message; }
  }

  async function ask(event) {
    event.preventDefault();
    if (state.busy || importing || !state.sessionId) return toast("请等待当前任务或服务连接完成。");
    const message = byId("knowledge-input").value.trim(); if (!message) return;
    try {
      const ids = selectedIds();
      setBusy(true); window.setBusy(true);
      const data = await post(`/api/sessions/${state.sessionId}/chat`, {message, knowledge_mode: true, knowledge_document_ids: ids});
      state.flowRun = false; state.knowledgeRun = true;
      addKnowledgeMessage("user", message); addMessage("user", message);
      pending = addKnowledgeMessage("assistant", "正在检索资料并核对原文…"); pending.classList.add("pending");
      state.pending = addMessage("assistant", "正在检索专业资料…", "pending");
      byId("knowledge-input").value = "";
      byId("knowledge-progress").textContent = "Agent 正在检索所选资料…";
      connectEvents(data.run_id);
    } catch (error) { window.setBusy(false); toast(error.message); }
  }

  function onEvent(event) {
    if (event.type === "tool_result" && event.tool === "search_knowledge" && event.result.status !== "error") showEvidence(event.result.hits || [], event.result.message);
    if (!state.knowledgeRun) return;
    if (["status", "thinking", "plan", "tool_start"].includes(event.type)) byId("knowledge-progress").textContent = event.message || "正在核对专业依据…";
    if (event.type === "final") {
      pending?.remove(); pending = null;
      const article = addKnowledgeMessage("assistant", event.message, event.citations || []); appendArtifacts(article, event.artifacts);
      if (event.citations?.length) showEvidence(event.citations);
      byId("knowledge-progress").textContent = event.citations?.length ? `回答引用了 ${event.citations.length} 个已核验编号的原文片段。` : "本轮回答未引用文献依据，请注意证据范围。";
    }
    if (event.type === "error") { pending?.remove(); pending = null; addKnowledgeMessage("assistant", event.message); byId("knowledge-progress").textContent = event.message; }
  }

  byId("knowledge-file-input").addEventListener("change", (event) => { const file = event.target.files[0]; if (file) importDocument(null, file); event.target.value = ""; });
  byId("knowledge-path-form").addEventListener("submit", (event) => { event.preventDefault(); importDocument(byId("knowledge-path").value.trim()); });
  byId("knowledge-form").addEventListener("submit", ask);
  byId("knowledge-local-search").addEventListener("click", localSearch);
  byId("knowledge-stop").addEventListener("click", stopAnalysis);
  byId("knowledge-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); byId("knowledge-form").requestSubmit(); } });
  document.querySelectorAll("[data-knowledge-prompt]").forEach((button) => button.addEventListener("click", () => { byId("knowledge-input").value = button.dataset.knowledgePrompt; byId("knowledge-input").focus(); }));
  byId("knowledge-source-close").addEventListener("click", () => byId("knowledge-source-dialog").close());
  window.KnowledgeUI = {refresh, openSource, onEvent, setBusy};
  refresh();
})();
