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
      const escape = text => text.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
      document.querySelector("#clip-grid").innerHTML = job.outputs
        .map((clip, index) => {
          const meta = job.metadata?.[index];
          const suggestion = meta ? `<div class="clip-suggest"><strong>${escape(meta.title)}</strong>
            <p>${escape(meta.description)}</p><small>${escape(meta.hashtags)}</small>
            <button type="button" class="copy" data-text="${escape(`${meta.title}\n\n${meta.description}\n\n${meta.hashtags}`)}">Copiar texto</button></div>` : "";
          const plan = job.ai_plans?.[index];
          const planBox = plan ? `<div class="clip-plan"><strong>Plano da IA · clima ${escape(plan.mood)}</strong>
            ${plan.hook ? `<span>Gancho: ${escape(plan.hook)}</span>` : ""}
            ${plan.callouts.length ? `<span>Destaques: ${plan.callouts.map(c => `${c.t}s “${escape(c.text)}”`).join(" · ")}</span>` : ""}
            ${plan.zoom.length ? `<span>Zoom em: ${plan.zoom.map(t => `${t}s`).join(", ")}</span>` : ""}
            ${plan.emoji.length ? `<span>Emojis: ${plan.emoji.map(e => `${e.t}s ${e.emoji}`).join(" · ")}</span>` : ""}</div>` : "";
          return `<article class="clip-card">
          <video controls preload="metadata" src="${clip.url}"></video>
          <div class="clip-meta"><strong>Corte ${String(index + 1).padStart(2, "0")}</strong>
          <a class="download" href="${clip.download_url}">Baixar MP4</a></div>${suggestion}${planBox}</article>`;
        })
        .join("");
      document.querySelectorAll(".copy").forEach(button => button.addEventListener("click", async () => {
        await navigator.clipboard.writeText(button.dataset.text);
        button.textContent = "Copiado!";
      }));
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
    const optionNames = ["stylish_captions", "varied_fonts", "smooth_zoom", "clip_progress", "opening_title", "sound_effects", "hook_start", "end_cta",
      "camera_cuts", "caption_emoji", "censor", "background_music", "energy_score", "suggestions", "floating_captions",
      "sfx_hook", "sfx_whoosh", "sfx_riser", "fx_hook", "fx_shake", "fx_flash", "fx_keyword", "fx_vignette", "ncs_credit",
      "speed_ramp", "freeze_climax"];
    const options = Object.fromEntries(optionNames.map(name =>
      [name, document.querySelector(`#${name.replaceAll("_", "-")}`).checked]));
    const musicTrack = document.querySelector("#music-track").value;
    const musicVolume = Number(document.querySelector("#music-volume").value);
    const capabilities = await fetch("/openapi.json", { cache: "no-store" });
    const schema = capabilities.ok ? await capabilities.json() : null;
    const properties = schema?.components?.schemas?.CreateJobRequest?.properties;
    if (!optionNames.every(name => properties?.[name]) || !properties?.director
        || !properties?.music_track || !properties?.music_volume) {
      throw new Error("O servidor ainda não carregou as novas opções. Abra a versão atualizada do Corta Aí antes de gerar.");
    }
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        youtube_url: document.querySelector("#youtube-url").value,
        clip_count: Number(document.querySelector("#clip-count").value),
        clip_duration: Number(document.querySelector("#clip-duration").value),
        ...options,
        music_track: musicTrack,
        music_volume: musicVolume,
        caption_position: document.querySelector("#caption-position").value,
        director: document.querySelector("#director").value,
        title_text: options.opening_title ? document.querySelector("#title-text").value.trim() : "",
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.[0]?.msg || data.detail || "Dados inválidos");
    if (optionNames.some(name => data[name] !== options[name])
        || data.music_track !== musicTrack || data.music_volume !== musicVolume) {
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

const openingTitle = document.querySelector("#opening-title");
const titleText = document.querySelector("#title-text");
function syncTitleField() {
  titleText.disabled = !openingTitle.checked;
}
openingTitle.addEventListener("change", syncTitleField);
syncTitleField();

const backgroundMusic = document.querySelector("#background-music");
const musicTrack = document.querySelector("#music-track");
const musicVolume = document.querySelector("#music-volume");
const ncsCredit = document.querySelector("#ncs-credit");
function syncMusicFields() {
  const withMusic = backgroundMusic.checked;
  musicTrack.disabled = !withMusic;
  musicVolume.disabled = !withMusic;
  ncsCredit.disabled = !withMusic || musicTrack.value !== "";
}
backgroundMusic.addEventListener("change", syncMusicFields);
musicTrack.addEventListener("change", syncMusicFields);
syncMusicFields();

fetch("/api/music").then(response => (response.ok ? response.json() : null)).then(data => {
  if (!data?.tracks) return;
  for (const track of data.tracks) {
    if (!track.value) continue;
    const option = document.createElement("option");
    option.value = track.value;
    option.textContent = track.label;
    musicTrack.append(option);
  }
}).catch(() => {});
