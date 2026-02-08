// === State ===
let videos = [];
let selectedIds = new Set();
let downloadedIds = new Set();
let errorIds = new Set();
let allSelected = true;
let selectedFormat = "mp3";
let isDownloading = false;

// === DOM Refs ===
const urlInput = document.getElementById("url-input");
const extractBtn = document.getElementById("extract-btn");
const errorMsg = document.getElementById("error-message");
const inputSection = document.getElementById("input-section");
const loadingSection = document.getElementById("loading-section");
const resultsSection = document.getElementById("results-section");
const videoGrid = document.getElementById("video-grid");
const playlistTitleEl = document.getElementById("playlist-title");
const videoCountEl = document.getElementById("video-count");
const selectAllBtn = document.getElementById("select-all-btn");
const downloadSelectedBtn = document.getElementById("download-selected-btn");
const downloadBar = document.getElementById("download-bar");
const downloadStatus = document.getElementById("download-status");
const overallProgress = document.getElementById("download-overall-progress");
const overallProgressFill = document.getElementById("overall-progress-fill");
const newPlaylistBtn = document.getElementById("new-playlist-btn");

// === Section Management ===
function showSection(name) {
  inputSection.classList.toggle("hidden", name !== "input");
  loadingSection.classList.toggle("hidden", name !== "loading");
  resultsSection.classList.toggle("hidden", name !== "results");
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove("hidden");
}

function hideError() {
  errorMsg.classList.add("hidden");
}

// === Extract Playlist ===
extractBtn.addEventListener("click", extractPlaylist);
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") extractPlaylist();
});

async function extractPlaylist() {
  const url = urlInput.value.trim();
  if (!url) {
    showError("Please enter a URL");
    return;
  }
  if (!url.startsWith("http")) {
    showError("Please enter a valid URL starting with http:// or https://");
    return;
  }

  hideError();
  extractBtn.disabled = true;
  showSection("loading");

  try {
    const res = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Extraction failed");
    }

    const data = await res.json();
    videos = data.videos;
    selectedIds = new Set(videos.map((v) => v.video_id));
    downloadedIds = new Set();
    errorIds = new Set();
    allSelected = true;

    playlistTitleEl.textContent = data.title;
    videoCountEl.textContent = `${videos.length} video${videos.length !== 1 ? "s" : ""}`;

    renderVideoGrid();
    showSection("results");
  } catch (e) {
    showSection("input");
    showError(e.message);
  } finally {
    extractBtn.disabled = false;
  }
}

// === Render Video Grid ===
function renderVideoGrid() {
  videoGrid.innerHTML = "";

  videos.forEach((video) => {
    const card = document.createElement("div");
    card.className = "video-card selected";
    card.dataset.videoId = video.video_id;

    const thumbUrl =
      video.thumbnail ||
      `https://i.ytimg.com/vi/${video.video_id}/hqdefault.jpg`;

    card.innerHTML = `
      <div class="thumbnail-wrap">
        <img class="thumbnail"
             src="${escapeAttr(thumbUrl)}"
             alt="${escapeAttr(video.title)}"
             loading="lazy"
             onerror="this.style.display='none'">
        ${video.duration_str ? `<span class="duration-badge">${escapeHtml(video.duration_str)}</span>` : ""}
        <div class="check-circle">&#10003;</div>
        <div class="status-icon"></div>
      </div>
      <div class="info">
        <div class="title">${escapeHtml(video.title)}</div>
        <div class="meta">${video.uploader ? escapeHtml(video.uploader) : ""}</div>
      </div>
      <div class="progress-overlay"><div class="fill"></div></div>
      <div class="error-msg"></div>
    `;

    card.addEventListener("click", (e) => {
      if (e.target.closest(".status-icon")) return;
      if (isDownloading) return;
      toggleSelection(video.video_id, card);
    });

    videoGrid.appendChild(card);
  });

  updateSelectionUI();
}

function toggleSelection(videoId, card) {
  if (selectedIds.has(videoId)) {
    selectedIds.delete(videoId);
    card.classList.remove("selected");
  } else {
    selectedIds.add(videoId);
    card.classList.add("selected");
  }
  allSelected = selectedIds.size === videos.length;
  updateSelectionUI();
}

function updateSelectionUI() {
  selectAllBtn.textContent = allSelected ? "Deselect All" : "Select All";
  downloadSelectedBtn.textContent = `Download Selected (${selectedIds.size})`;
  downloadSelectedBtn.disabled = selectedIds.size === 0 || isDownloading;
}

// === Select / Deselect All ===
selectAllBtn.addEventListener("click", () => {
  if (isDownloading) return;
  allSelected = !allSelected;
  const cards = videoGrid.querySelectorAll(".video-card");
  cards.forEach((card) => {
    const id = card.dataset.videoId;
    if (allSelected) {
      selectedIds.add(id);
      card.classList.add("selected");
    } else {
      selectedIds.delete(id);
      card.classList.remove("selected");
    }
  });
  updateSelectionUI();
});

// === New Playlist ===
newPlaylistBtn.addEventListener("click", () => {
  if (isDownloading) return;
  videos = [];
  selectedIds.clear();
  downloadedIds.clear();
  errorIds.clear();
  urlInput.value = "";
  downloadBar.classList.add("hidden");
  showSection("input");
});

// === Format Toggle ===
document.querySelectorAll(".format-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (isDownloading) return;
    document.querySelectorAll(".format-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    selectedFormat = btn.dataset.format;
  });
});

// === Download Selected ===
downloadSelectedBtn.addEventListener("click", () => {
  if (selectedIds.size === 0 || isDownloading) return;
  startDownloads([...selectedIds]);
});

async function startDownloads(videoIds) {
  isDownloading = true;
  downloadSelectedBtn.disabled = true;
  selectAllBtn.disabled = true;

  downloadBar.classList.remove("hidden");
  downloadStatus.textContent = "Starting downloads...";
  overallProgress.textContent = `0 / ${videoIds.length}`;
  overallProgressFill.style.width = "0%";
  overallProgressFill.classList.remove("complete");

  let completedCount = 0;
  let errorCount = 0;
  const totalCount = videoIds.length;

  for (const videoId of videoIds) {
    const video = videos.find((v) => v.video_id === videoId);
    if (!video) continue;

    updateCardState(videoId, "downloading", "&#8595;");
    downloadStatus.textContent = `Downloading: ${truncate(video.title, 40)}`;

    try {
      const res = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: video.url,
          fmt: selectedFormat,
          title: video.title,
        }),
      });

      if (!res.ok) {
        let detail = "Download failed";
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (_) {}
        throw new Error(detail);
      }

      const blob = await res.blob();

      // Get filename from Content-Disposition header
      const cd = res.headers.get("Content-Disposition");
      let filename = `${video.title}.${selectedFormat}`;
      if (cd) {
        const match = cd.match(/filename="(.+)"/);
        if (match) filename = match[1];
      }

      // Trigger browser download
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);

      completedCount++;
      downloadedIds.add(videoId);
      updateCardState(videoId, "complete", "&#10003;");
      updateCardProgress(videoId, 100);
      downloadStatus.textContent = `Downloaded: ${truncate(video.title, 40)}`;
    } catch (e) {
      errorCount++;
      errorIds.add(videoId);
      updateCardState(videoId, "error", "!");
      setCardError(videoId, e.message || "Download failed");
    }

    overallProgress.textContent = `${completedCount + errorCount} / ${totalCount}`;
    overallProgressFill.style.width = `${((completedCount + errorCount) / totalCount) * 100}%`;
  }

  // All done
  isDownloading = false;
  downloadSelectedBtn.disabled = false;
  selectAllBtn.disabled = false;

  if (errorCount === 0) {
    downloadStatus.textContent = `All ${completedCount} downloads complete!`;
    overallProgressFill.classList.add("complete");
  } else if (completedCount === 0) {
    downloadStatus.textContent = `All ${errorCount} downloads failed`;
  } else {
    downloadStatus.textContent = `${completedCount} downloaded, ${errorCount} failed`;
    overallProgressFill.classList.add("complete");
  }
}

// === Card Updates ===
function updateCardProgress(videoId, percent) {
  const card = document.querySelector(`[data-video-id="${videoId}"]`);
  if (!card) return;
  const fill = card.querySelector(".progress-overlay .fill");
  fill.style.width = `${percent}%`;
}

function updateCardState(videoId, state, iconHtml) {
  const card = document.querySelector(`[data-video-id="${videoId}"]`);
  if (!card) return;
  card.classList.remove("downloading", "complete", "error");
  card.classList.add(state);
  const icon = card.querySelector(".status-icon");
  if (icon && iconHtml) {
    icon.innerHTML = iconHtml;
  }
}

function setCardError(videoId, message) {
  const card = document.querySelector(`[data-video-id="${videoId}"]`);
  if (!card) return;
  const errorEl = card.querySelector(".error-msg");
  if (errorEl) {
    errorEl.textContent = message;
  }
}

// === Helpers ===
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function escapeAttr(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function truncate(str, maxLen) {
  if (!str) return "";
  return str.length > maxLen ? str.slice(0, maxLen) + "..." : str;
}
