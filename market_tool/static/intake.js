const tabs = [...document.querySelectorAll(".mode-tab")];
const panels = [...document.querySelectorAll(".mode-panel")];
const feedback = document.querySelector("#form-feedback");
const fileInput = document.querySelector("#property-file");
const fileName = document.querySelector("#file-name");
const dropZone = document.querySelector(".drop-zone");

function selectMode(mode) {
  tabs.forEach((tab) => {
    const selected = tab.dataset.mode === mode;
    tab.classList.toggle("is-active", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  panels.forEach((panel) => {
    panel.hidden = panel.dataset.panel !== mode && panel.dataset.mode !== mode;
  });
  feedback.hidden = true;
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectMode(tab.dataset.mode));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(index + offset + tabs.length) % tabs.length];
    selectMode(next.dataset.mode);
    next.focus();
  });
});

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files[0]?.name || "No file selected";
});

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("is-dragging");
});
dropZone.addEventListener("dragleave", () =>
  dropZone.classList.remove("is-dragging"),
);
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("is-dragging");
  if (event.dataTransfer.files.length) {
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event("change"));
  }
});

function showFeedback(message, isError) {
  feedback.textContent = message;
  feedback.classList.toggle("is-error", isError);
  feedback.hidden = false;
}

document.querySelectorAll(".intake-form").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector(".submit-button");
    const initialText = button.firstChild.textContent;
    button.disabled = true;
    button.firstChild.textContent = "Saving… ";
    feedback.hidden = true;
    try {
      const response = await fetch("/api/import", {
        method: "POST",
        body: new FormData(form),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Import failed.");
      showFeedback(result.message, false);
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      showFeedback(error.message || "Could not reach the local app.", true);
    } finally {
      button.disabled = false;
      button.firstChild.textContent = initialText;
    }
  });
});
