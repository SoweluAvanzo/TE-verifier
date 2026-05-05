// Webapp orchestration for the YAML editor (/yaml).
// Verdict rendering is in verdict.js (shared with the form-driven UI).

const yamlInput = document.getElementById("yaml-input");
const verifyBtn = document.getElementById("verify-btn");
const verifyStatus = document.getElementById("verify-status");
const reportSection = document.getElementById("report-section");

document.querySelectorAll(".example-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const name = btn.dataset.example;
    verifyStatus.textContent = `Loading example "${name}"…`;
    try {
      const res = await fetch(`/api/example/${encodeURIComponent(name)}`);
      const data = await res.json();
      if (data.error) {
        verifyStatus.textContent = `error: ${data.error}`;
        return;
      }
      yamlInput.value = data.yaml;
      verifyStatus.textContent = `Loaded "${name}.yaml". Click Verify to run the six checks.`;
    } catch (e) {
      verifyStatus.textContent = `error: ${e}`;
    }
  });
});

verifyBtn.addEventListener("click", async () => {
  const yaml = yamlInput.value;
  if (!yaml.trim()) {
    verifyStatus.textContent = "Paste or load a TE-IR YAML first.";
    return;
  }
  verifyStatus.textContent = "Verifying…";
  reportSection.classList.add("hidden");
  try {
    const res = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml }),
    });
    const data = await res.json();
    if (data.error) {
      verifyStatus.textContent = `Error: ${data.error}`;
      return;
    }
    reportSection.classList.remove("hidden");
    window.renderReport(data); // verdict.js
    verifyStatus.textContent = "Done.";
    reportSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    verifyStatus.textContent = `Error: ${e}`;
  }
});
