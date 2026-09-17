const form = document.querySelector("#job-form");
const progressView = document.querySelector("#progress-view");
const results = document.querySelector("#results");
const progressBar = document.querySelector("#progress-bar");
const progressNumber = document.querySelector("#progress-number");
const statusMessage = document.querySelector("#status-message");
const errorBox = document.querySelector("#error-box");
let timer;

function showError(text) {
  errorBox.textContent = text;
  errorBox.classList.remove("hidden");
}

async function poll(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) throw new Error("Não foi possível consultar o processamento");
    const job = await response.json();
    progressBar.style.width = `${job.progress}%`;
    progressNumber.textContent = `${job.progress}%`;
    statusMessage.textContent = job.message;

    if (job.status === "completed") {
      clearTimeout(timer);
      progressView.classList.add("hidden");
      results.classList.remove("hidden");
      document.querySelector("#clip-grid").innerHTML = job.outputs
        .map((clip, index) => `<article class="clip-card">
          <video controls preload="metadata" src="${clip.url}"></video>
          <div class="clip-meta"><strong>Corte ${String(index + 1).padStart(2, "0")}</strong>
          <a class="download" href="${clip.download_url}">Baixar MP4</a></div></article>`)
        .join("");
      return;
    }
    if (job.status === "failed") {
      showError(job.error || "O processamento falhou");
      return;
    }
    timer = setTimeout(() => poll(jobId), 1200);
  } catch (error) {
    showError(error.message);
    timer = setTimeout(() => poll(jobId), 3000);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.classList.add("hidden");
  const button = form.querySelector("button");
  button.disabled = true;
  button.querySelector("span").textContent = "Criando processamento...";

  try {
    const stylishCaptions = document.querySelector("#stylish-captions").checked;
    const variedFonts = document.querySelector("#varied-fonts").checked;
    if (stylishCaptions || variedFonts) {
      const capabilities = await fetch("/openapi.json", { cache: "no-store" });
      const schema = capabilities.ok ? await capabilities.json() : null;
      const properties = schema?.components?.schemas?.CreateJobRequest?.properties;
      if (!properties?.varied_fonts || !properties?.stylish_captions) {
        throw new Error("O servidor ainda não carregou as opções de legenda. Reinicie o Corta Aí e atualize esta página antes de gerar.");
      }
    }
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        youtube_url: document.querySelector("#youtube-url").value,
        clip_count: Number(document.querySelector("#clip-count").value),
        clip_duration: Number(document.querySelector("#clip-duration").value),
        stylish_captions: stylishCaptions,
        varied_fonts: variedFonts,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.[0]?.msg || data.detail || "Dados inválidos");
    if (data.stylish_captions !== stylishCaptions || data.varied_fonts !== variedFonts) {
      throw new Error("O processamento não confirmou as opções selecionadas. Reinicie o Corta Aí e atualize esta página.");
    }
    form.classList.add("hidden");
    progressView.classList.remove("hidden");
    poll(data.id);
  } catch (error) {
    showError(error.message);
    button.disabled = false;
    button.querySelector("span").textContent = "Gerar meus cortes";
  }
});

document.querySelector("#new-job").addEventListener("click", () => {
  results.classList.add("hidden");
  form.classList.remove("hidden");
  const button = form.querySelector("button");
  button.disabled = false;
  button.querySelector("span").textContent = "Gerar meus cortes";
  progressBar.style.width = "0";
  progressNumber.textContent = "0%";
});
