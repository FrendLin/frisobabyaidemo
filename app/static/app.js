const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".tab-panel");
const singleForm = document.getElementById("singleForm");
const imageInput = document.getElementById("imageInput");
const imagePreview = document.getElementById("imagePreview");
const dropZone = document.getElementById("dropZone");
const resultCard = document.getElementById("resultCard");
const reviewButton = document.getElementById("reviewButton");
const healthPill = document.getElementById("healthPill");
const healthText = document.getElementById("healthText");
const batchForm = document.getElementById("batchForm");
const batchInput = document.getElementById("batchInput");
const batchButton = document.getElementById("batchButton");
const batchStatus = document.getElementById("batchStatus");
const batchFileName = document.getElementById("batchFileName");
const batchQualityCheck = document.getElementById("batchQualityCheck");

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((item) => item.classList.toggle("active", item === tab));
    panels.forEach((panel) => {
      panel.classList.toggle("active", panel.id === `panel-${tab.dataset.tab}`);
    });
  });
});

function previewFile(file) {
  if (!file) return;
  imagePreview.src = URL.createObjectURL(file);
  imagePreview.alt = `待审核图片：${file.name}`;
  dropZone.classList.add("has-image");
}

imageInput.addEventListener("change", () => previewFile(imageInput.files[0]));
["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
});
dropZone.addEventListener("drop", (event) => {
  if (!event.dataTransfer.files.length) return;
  imageInput.files = event.dataTransfer.files;
  previewFile(imageInput.files[0]);
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function metricValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return number;
}

function formatScore(value, digits = 2) {
  const score = metricValue(value);
  if (score === null) return "--";
  return score.toFixed(digits).replace(/\.?0+$/, "");
}

function percent(value) {
  const score = metricValue(value);
  if (score === null) return "--";
  return `${Math.round(score * 100)}%`;
}

function blurJudgement(value) {
  const score = metricValue(value);
  if (score === null) return "未返回";
  return score > 55 ? "模糊" : "正常";
}

function brightnessJudgement(value) {
  const score = metricValue(value);
  if (score === null) return "未返回";
  if (score <= 0.35) return "昏暗";
  if (score >= 0.7) return "过曝";
  return "正常";
}

function qualityHtml(qualityCheck) {
  if (!qualityCheck) return "";
  const blurDescription =
    qualityCheck.blur_description || blurJudgement(qualityCheck.blur);
  const brightnessDescription =
    qualityCheck.brightness_description || brightnessJudgement(qualityCheck.brightness);
  return `
    <section class="quality-result" aria-label="图片质量检查结果">
      <div class="quality-heading">
        <div>
          <small>IMAGE QUALITY</small>
          <h4>图片质量检查</h4>
        </div>
        <span class="quality-state ${qualityCheck.acceptable ? "acceptable" : "attention"}">
          ${qualityCheck.acceptable ? "质量可用" : "建议复核"}
        </span>
      </div>
      <div class="quality-metrics">
        <article>
          <span>模糊程度</span>
          <strong>${formatScore(qualityCheck.blur)}</strong>
          <small>判断：${escapeHtml(blurDescription)}</small>
        </article>
        <article>
          <span>明亮度</span>
          <strong>${formatScore(qualityCheck.brightness, 3)}</strong>
          <small>判断：${escapeHtml(brightnessDescription)}</small>
        </article>
      </div>
      <p>判定口径：模糊度 &gt; 55 为模糊；明亮度 ≤ 0.35 为昏暗，≥ 0.7 为过曝。</p>
    </section>`;
}

function detectionCard(detection, mode) {
  const brand = detection.brand || "未知品牌";
  const material = detection.material_type || "未知类型";
  const tags = [];
  tags.push(
    detection.reliable
      ? '<span class="detection-tag reliable">达到阈值</span>'
      : '<span class="detection-tag low">置信度不足</span>'
  );
  if (mode === "review" && detection.matches_selection !== null) {
    tags.push(
      detection.matches_selection
        ? '<span class="detection-tag matched">匹配所选</span>'
        : '<span class="detection-tag mismatched">不匹配所选</span>'
    );
  }
  const evidence = (detection.evidence || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const region = detection.region
    ? `<p class="detection-region">位置：${escapeHtml(detection.region)}</p>`
    : "";
  return `
    <article class="detection-card">
      <div class="detection-head">
        <strong>${escapeHtml(brand)} · ${escapeHtml(material)}</strong>
        <span class="detection-confidence">置信度 ${percent(detection.confidence)}</span>
      </div>
      <div class="detection-tags">${tags.join("")}</div>
      ${region}
      ${evidence ? `<ul class="detection-evidence">${evidence}</ul>` : ""}
    </article>`;
}

function detectionsHtml(detections, mode) {
  if (!detections || !detections.length) {
    return '<p class="detection-empty">未识别到可归属的大型品牌物料。</p>';
  }
  return `<div class="detection-list">${detections
    .map((item) => detectionCard(item, mode))
    .join("")}</div>`;
}

function renderResult(result) {
  const reviewLabels = {
    passed: ["审核通过", "已识别到达到阈值且匹配所选条件的组合"],
    rejected: ["审核驳回", "识别到可靠组合，但没有匹配所选条件的项"],
    manual_review: ["转人工复核", "证据不足或置信度不够，需人工确认"],
  };
  const recognitionLabels = {
    recognized: ["识别结果", "已识别到以下可靠的「品牌 · 物料」组合"],
    manual_review: ["转人工复核", "未识别到达到阈值的可靠组合"],
  };
  const isReview = result.mode === "review";
  const [title, summary] = (isReview ? reviewLabels : recognitionLabels)[
    result.status
  ];

  const selectedParts = [];
  if (result.expected_brand) selectedParts.push(escapeHtml(result.expected_brand));
  if (result.expected_material_type)
    selectedParts.push(escapeHtml(result.expected_material_type));
  const selectedText = selectedParts.length
    ? selectedParts.join(" · ")
    : "未指定（自动识别）";

  const modeBadge = isReview
    ? '<span class="mode-badge review">审核模式</span>'
    : '<span class="mode-badge recognition">识别模式</span>';

  const reasons = (result.reasons || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");

  resultCard.innerHTML = `
    <div class="result-view">
      <div class="result-kicker">
        ${modeBadge}
        <span class="status-badge ${escapeHtml(result.status)}">${escapeHtml(title)}</span>
      </div>
      <h3>${escapeHtml(title)}</h3>
      <p class="result-summary">${escapeHtml(summary)}</p>
      <div class="selected-condition">
        <small>所选审核条件</small>
        <strong>${selectedText}</strong>
      </div>
      <div class="result-list">
        <h4>识别到的组合</h4>
        ${detectionsHtml(result.detections, result.mode)}
      </div>
      ${reasons ? `<div class="result-list"><h4>说明</h4><ul>${reasons}</ul></div>` : ""}
      ${qualityHtml(result.quality_check)}
    </div>`;
}

function renderError(message) {
  resultCard.innerHTML = `
    <div class="empty-result">
      <span class="result-orbit" aria-hidden="true"></span>
      <h3>暂时无法审核</h3>
      <p>${escapeHtml(message)}</p>
    </div>`;
}

singleForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  reviewButton.disabled = true;
  reviewButton.firstElementChild.textContent = "识别中…";
  try {
    const response = await fetch("/api/review", { method: "POST", body: new FormData(singleForm) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "审核请求失败");
    renderResult(payload);
  } catch (error) {
    renderError(error.message);
  } finally {
    reviewButton.disabled = false;
    reviewButton.firstElementChild.textContent = "开始审核";
  }
});

batchInput.addEventListener("change", () => {
  batchFileName.textContent = batchInput.files[0]?.name || "选择待审核 Excel";
});

batchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  batchButton.disabled = true;
  batchButton.firstElementChild.textContent = "批量处理中…";
  batchStatus.textContent = "正在下载图片并逐行审核，请勿关闭页面。";
  const formData = new FormData();
  formData.append("workbook", batchInput.files[0]);
  formData.append("quality_check", batchQualityCheck.checked ? "true" : "false");
  try {
    const response = await fetch("/api/batch", { method: "POST", body: formData });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "批量处理失败");
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "material_review_results.xlsx";
    link.click();
    URL.revokeObjectURL(link.href);
    batchStatus.textContent = "处理完成，结果文件已下载。";
  } catch (error) {
    batchStatus.textContent = error.message;
  } finally {
    batchButton.disabled = false;
    batchButton.firstElementChild.textContent = "上传并处理";
  }
});

fetch("/api/health")
  .then((response) => response.json())
  .then((health) => {
    const ready = health.status === "ok";
    healthPill.classList.add(ready ? "ready" : "degraded");
    healthText.textContent = ready ? "识别服务已就绪" : "待配置识别模型";
  })
  .catch(() => {
    healthPill.classList.add("degraded");
    healthText.textContent = "健康检查失败";
  });
