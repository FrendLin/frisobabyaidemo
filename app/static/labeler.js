const state = {
  directory: "",
  images: [],
  filtered: [],
  currentIndex: -1,
  brands: [],
  materials: [],
  saveTimer: null,
};

const el = (id) => document.getElementById(id);
const scanForm = el("scanForm");
const directoryInput = el("directoryInput");
const pickDirButton = el("pickDirButton");
const scanButton = el("scanButton");
const workspace = el("workspace");
const thumbList = el("thumbList");
const viewerImage = el("viewerImage");
const viewerMeta = el("viewerMeta");
const saveStatus = el("saveStatus");
const brandOptions = el("brandOptions");
const materialOptions = el("materialOptions");
const manifestUrl = el("manifestUrl");
const progressFill = el("progressFill");
const progressText = el("progressText");
const filterMode = el("filterMode");
const filterBrand = el("filterBrand");
const filterMaterial = el("filterMaterial");

let config = { brand_catalog: [], material_types: [] };

async function loadConfig() {
  const response = await fetch("/api/labeler/config");
  config = await response.json();
  renderBrandChips();
  renderMaterialChips();
  renderFilterOptions();
}

function renderBrandChips() {
  brandOptions.innerHTML = "";
  config.brand_catalog.forEach((group) => {
    const wrap = document.createElement("div");
    wrap.className = "chip-group";
    const title = document.createElement("span");
    title.className = "chip-group-title";
    title.textContent = group.group;
    wrap.appendChild(title);
    group.items.forEach((name) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = name;
      chip.dataset.brand = name;
      chip.addEventListener("click", () => selectBrand(name));
      wrap.appendChild(chip);
    });
    brandOptions.appendChild(wrap);
  });
}

function renderMaterialChips() {
  materialOptions.innerHTML = "";
  config.material_types.forEach((name) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = name;
    chip.dataset.material = name;
    chip.addEventListener("click", () => selectMaterial(name));
    materialOptions.appendChild(chip);
  });
}

function renderFilterOptions() {
  config.brand_catalog.forEach((group) => {
    group.items.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      filterBrand.appendChild(opt);
    });
  });
  config.material_types.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    filterMaterial.appendChild(opt);
  });
}

pickDirButton.addEventListener("click", async () => {
  pickDirButton.disabled = true;
  pickDirButton.textContent = "等待系统选择…";
  try {
    const response = await fetch("/api/labeler/pick-directory", { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      alert(`选择目录失败：${data.detail || response.status}`);
      return;
    }
    if (data.cancelled || !data.directory) return;
    directoryInput.value = data.directory;
    el("sourceHint").textContent = `已选择：${data.directory}`;
    await scanDirectory(data.directory);
  } finally {
    pickDirButton.disabled = false;
    pickDirButton.textContent = "选择目录并扫描";
  }
});

scanForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await scanDirectory(directoryInput.value.trim());
});

async function scanDirectory(directory) {
  if (!directory) return;
  scanButton.disabled = true;
  try {
    const params = new URLSearchParams({ directory });
    const response = await fetch(`/api/labeler/scan?${params}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      alert(`扫描失败：${err.detail || response.status}`);
      return;
    }
    const data = await response.json();
    state.directory = data.directory;
    state.images = data.images;
    workspace.hidden = false;
    applyFilterAndRender();
    updateProgress(data.progress);
    if (state.filtered.length) selectImage(0);
  } finally {
    scanButton.disabled = false;
  }
}

[filterMode, filterBrand, filterMaterial].forEach((control) =>
  control.addEventListener("change", () => {
    applyFilterAndRender();
    if (state.filtered.length) selectImage(0);
    else clearViewer();
  })
);

function applyFilterAndRender() {
  const mode = filterMode.value;
  const brand = filterBrand.value;
  const material = filterMaterial.value;
  state.filtered = state.images.filter((row) => {
    if (mode === "labeled" && !row.labeled) return false;
    if (mode === "unlabeled" && row.labeled) return false;
    if (brand && !(row.brands || []).includes(brand)) return false;
    if (material && !(row.material_types || []).includes(material)) return false;
    return true;
  });
  renderThumbs();
}

function renderThumbs() {
  thumbList.innerHTML = "";
  state.filtered.forEach((row, index) => {
    const li = document.createElement("li");
    li.className = "thumb";
    if (index === state.currentIndex) li.classList.add("active");
    if (row.labeled) li.classList.add("done");
    const tag = row.labeled
      ? `${(row.brands || []).join("、")} · ${(row.material_types || []).join("、")}`
      : "未标注";
    li.innerHTML = `<strong>${row.name}</strong><small>${tag}</small>`;
    li.title = row.relpath;
    li.addEventListener("click", () => selectImage(index));
    thumbList.appendChild(li);
  });
}

function updateProgress(progress) {
  const pct = progress.total ? Math.round((progress.labeled / progress.total) * 100) : 0;
  progressFill.style.width = `${pct}%`;
  progressText.textContent = `${progress.labeled} / ${progress.total} 已标注（${pct}%）`;
}

function recomputeProgress() {
  const total = state.images.length;
  const labeled = state.images.filter((row) => row.labeled).length;
  updateProgress({ total, labeled });
}

function clearViewer() {
  state.currentIndex = -1;
  viewerImage.innerHTML = `<p class="viewer-empty">没有符合筛选条件的图片</p>`;
  viewerMeta.textContent = "";
}

function selectImage(index) {
  if (index < 0 || index >= state.filtered.length) return;
  state.currentIndex = index;
  const row = state.filtered[index];
  const params = new URLSearchParams({ directory: state.directory, relpath: row.relpath });
  viewerImage.innerHTML = `<img src="/api/labeler/image?${params}" alt="${row.name}" onerror="this.replaceWith(Object.assign(document.createElement('p'),{className:'viewer-empty',textContent:'图片无法加载（可能已损坏）'}))" />`;
  viewerMeta.textContent = `${row.relpath} · ${(row.size / 1024).toFixed(1)} KB`;
  state.brands = [...(row.brands || (row.brand ? [row.brand] : []))];
  state.materials = [
    ...(row.material_types || (row.material_type ? [row.material_type] : [])),
  ];
  manifestUrl.value = row.manifest_url || "";
  saveStatus.textContent = row.labeled ? "已标注" : "";
  saveStatus.className = "save-status";
  highlightChips();
  renderThumbs();
}

function highlightChips() {
  brandOptions.querySelectorAll(".chip").forEach((chip) => {
    chip.classList.toggle("selected", state.brands.includes(chip.dataset.brand));
  });
  materialOptions.querySelectorAll(".chip").forEach((chip) => {
    chip.classList.toggle(
      "selected",
      state.materials.includes(chip.dataset.material)
    );
  });
}

function selectBrand(name) {
  state.brands = state.brands.includes(name)
    ? state.brands.filter((item) => item !== name)
    : [...state.brands, name];
  highlightChips();
  autoSave();
}

function selectMaterial(name) {
  state.materials = state.materials.includes(name)
    ? state.materials.filter((item) => item !== name)
    : [...state.materials, name];
  highlightChips();
  autoSave();
}

manifestUrl.addEventListener("change", () => autoSave());

function autoSave() {
  // 品牌与物料均选定后自动保存；否则仅在有 manifest 变更时也落库。
  if (state.saveTimer) clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveCurrent(false), 250);
}

async function saveCurrent(advance) {
  if (state.currentIndex < 0) return false;
  const row = state.filtered[state.currentIndex];
  setSaveStatus("saving");
  try {
    const response = await fetch("/api/labeler/label", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        directory: state.directory,
        relpath: row.relpath,
        brands: state.brands,
        material_types: state.materials,
        manifest_url: manifestUrl.value.trim() || null,
      }),
    });
    if (!response.ok) throw new Error((await response.json()).detail || "保存失败");
    const data = await response.json();
    Object.assign(row, {
      brands: data.record.brands,
      material_types: data.record.material_types,
      brand: data.record.brand,
      material_type: data.record.material_type,
      manifest_url: data.record.manifest_url,
      updated_at: data.record.updated_at,
      labeled: Boolean(
        data.record.brands.length && data.record.material_types.length
      ),
    });
    const master = state.images.find((item) => item.relpath === row.relpath);
    if (master) Object.assign(master, row);
    setSaveStatus("saved");
    recomputeProgress();
    renderThumbs();
    if (advance) goNext();
    return true;
  } catch (error) {
    setSaveStatus("error", error.message);
    return false;
  }
}

function setSaveStatus(kind, message) {
  const map = { saving: "保存中…", saved: "已保存", error: `保存失败：${message || ""} 点此重试` };
  saveStatus.textContent = map[kind] || "";
  saveStatus.className = `save-status ${kind}`;
  saveStatus.onclick = kind === "error" ? () => saveCurrent(false) : null;
}

function goNext() {
  if (state.currentIndex + 1 < state.filtered.length) selectImage(state.currentIndex + 1);
}

el("saveNextButton").addEventListener("click", () => saveCurrent(true));
el("prevButton").addEventListener("click", () => {
  if (state.currentIndex > 0) selectImage(state.currentIndex - 1);
});

el("exportCsv").addEventListener("click", () => downloadExport("csv"));
el("exportJson").addEventListener("click", () => downloadExport("json"));

function downloadExport(fmt) {
  const params = new URLSearchParams({
    directory: state.directory,
    fmt,
    mode: filterMode.value,
  });
  if (filterBrand.value) params.set("brand", filterBrand.value);
  if (filterMaterial.value) params.set("material_type", filterMaterial.value);
  window.location.href = `/api/labeler/export?${params}`;
}

el("syncManifest").addEventListener("click", async () => {
  const response = await fetch("/api/labeler/sync-manifest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory: state.directory, append_missing: false }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    alert(`同步失败：${data.detail || response.status}`);
    return;
  }
  const r = data.result;
  alert(
      `同步完成：更新 ${r.updated} 条，未匹配 ${r.unmatched_urls.length} 条，` +
      `跳过非皇家 ${r.skipped_non_royal} 条、多标签 ${r.skipped_multilabel} 条、` +
      `未完成 ${r.skipped_incomplete} 条。`
  );
});

loadConfig();
