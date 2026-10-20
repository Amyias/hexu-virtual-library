import { attachMusicGlass } from "./music-glass.js";

const icon = (path) => `<svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
const playIcon = icon('<path d="M8 5.5v13l11-6.5z"/>');
const pauseIcon = icon(
  '<rect x="6.5" y="5" width="4" height="14" rx="1"/><rect x="13.5" y="5" width="4" height="14" rx="1"/>',
);

const TRACKS = [
  { title: "Saint Barbara Theme", file: "/public/audio/01_Saint_Barbara_Theme.mp3" },
  { title: "The Trek", file: "/public/audio/02_The_Trek.mp3" },
];

function clock(value) {
  const seconds = Number.isFinite(value) ? Math.floor(value) : 0;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** One audio element for the reading session. Returning a book invalidates pending play calls. */
export function createReadingMusic() {
  const panel = document.createElement("section");
  panel.id = "readingMusic";
  panel.hidden = true;
  panel.setAttribute("aria-label", "阅读音乐播放器");
  panel.innerHTML = `<div class="music-heading"><span class="music-disc" aria-hidden="true">♫</span><div><small>READING SOUNDTRACK</small><strong id="musicTitle"></strong><span id="musicStatus" role="status"></span></div></div><div class="music-controls"><button id="musicPrevious" aria-label="上一首" title="上一首">‹</button><button id="musicToggle" aria-label="播放音乐">▶</button><button id="musicNext" aria-label="下一首" title="下一首">›</button><label class="music-volume">音量<input id="musicVolume" type="range" min="0" max="100" step="1" aria-label="音乐音量"></label></div><div class="music-timeline"><span id="musicTime">0:00 / 0:00</span><input id="musicSeek" type="range" min="0" max="1000" value="0" step="1" aria-label="音乐播放进度" disabled></div>`;
  const audio = document.createElement("audio");
  audio.id = "readingAudio";
  audio.preload = "none";
  panel.append(audio);
  document.body.append(panel);
  const glass = attachMusicGlass(panel);
  panel.querySelector(".music-disc").innerHTML = icon(
    '<path d="M9 5v12.1a3.2 3.2 0 1 1-2-3V6l13-3v12.1a3.2 3.2 0 1 1-2-3V5.5z"/>',
  );
  panel
    .querySelector(".music-heading")
    .insertAdjacentHTML(
      "beforeend",
      '<span class="music-meter" aria-hidden="true"><i></i><i></i><i></i><i></i></span>',
    );
  const $ = (id) => panel.querySelector("#" + id);
  $("musicPrevious").innerHTML = icon('<path d="M5 6h2v12H5zm13 0v12L8 12z"/>');
  $("musicNext").innerHTML = icon('<path d="M17 6h2v12h-2zM6 6l10 6-10 6z"/>');
  let active = false,
    wantsPlayback = false,
    track = 0,
    generation = 0,
    status = "";
  let volume = 22;
  try {
    const saved = localStorage.getItem("hexu-music-volume");
    if (saved !== null && Number.isFinite(Number(saved)))
      volume = Math.max(0, Math.min(100, Number(saved)));
  } catch {
    /* Playback works even when browser storage is unavailable. */
  }
  audio.volume = volume / 100;
  $("musicVolume").value = String(volume);
  $("musicVolume").style.setProperty("--range-progress", `${volume}%`);

  function render() {
    $("musicTitle").textContent = TRACKS[track].title;
    $("musicStatus").textContent = status;
    const playing = active && !audio.paused;
    panel.classList.toggle("is-playing", playing);
    $("musicToggle").innerHTML = playing ? pauseIcon : playIcon;
    $("musicToggle").setAttribute("aria-label", playing ? "暂停音乐" : "播放音乐");
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    $("musicTime").textContent = `${clock(audio.currentTime)} / ${clock(duration)}`;
    $("musicSeek").disabled = duration <= 0;
    $("musicSeek").value = String(
      duration > 0 ? Math.round((audio.currentTime / duration) * 1000) : 0,
    );
    $("musicSeek").style.setProperty("--range-progress", `${Number($("musicSeek").value) / 10}%`);
  }
  async function play() {
    if (!active) return;
    wantsPlayback = true;
    const attempt = ++generation;
    if (!audio.getAttribute("src")) audio.src = TRACKS[track].file;
    status = "正在加载音乐";
    render();
    try {
      await audio.play();
      if (attempt !== generation) {
        if (!active) {
          audio.pause();
          audio.currentTime = 0;
        }
        return;
      }
      status = "阅读中 · 顺序循环";
      render();
    } catch (error) {
      if (attempt !== generation || !active) return;
      status =
        error.name === "NotAllowedError" ? "点击 ▶ 开启阅读音乐" : "音乐未能播放，点击 ▶ 重试";
      render();
    }
  }
  function pause() {
    generation++;
    wantsPlayback = false;
    audio.pause();
    status = "已暂停";
    render();
  }
  function changeTrack(delta) {
    generation++;
    const resume = active && wantsPlayback;
    audio.pause();
    track = (track + delta + TRACKS.length) % TRACKS.length;
    audio.src = TRACKS[track].file;
    audio.load();
    status = resume ? "正在加载音乐" : "已暂停";
    render();
    if (resume) void play();
  }
  function mount(host = document.body) {
    if (panel.parentElement === host) return;
    if (host === document.body) host.append(panel);
    else host.insertBefore(panel, host.querySelector(".novel-layout"));
    glass.refresh();
  }
  function start() {
    if (active) return; // Repeated cover updates must not undo the reader's pause choice.
    active = true;
    panel.hidden = false;
    glass.refresh();
    void play();
  }
  function stop() {
    active = false;
    wantsPlayback = false;
    generation++;
    audio.pause();
    audio.currentTime = 0;
    status = "";
    panel.hidden = true;
    render();
    mount();
  }
  $("musicToggle").onclick = () => {
    if (audio.paused) void play();
    else pause();
  };
  $("musicPrevious").onclick = () => changeTrack(-1);
  $("musicNext").onclick = () => changeTrack(1);
  $("musicVolume").oninput = (event) => {
    audio.volume = Number(event.target.value) / 100;
    event.target.style.setProperty("--range-progress", `${event.target.value}%`);
    try {
      localStorage.setItem("hexu-music-volume", event.target.value);
    } catch {
      /* Optional preference. */
    }
  };
  $("musicSeek").oninput = (event) => {
    if (Number.isFinite(audio.duration) && audio.duration > 0)
      audio.currentTime = (Number(event.target.value) / 1000) * audio.duration;
    render();
  };
  audio.addEventListener("ended", () => {
    if (active && wantsPlayback) changeTrack(1);
  });
  audio.addEventListener("playing", () => {
    if (!active || !wantsPlayback) {
      audio.pause();
      return;
    }
    status = "阅读中 · 顺序循环";
    render();
  });
  audio.addEventListener("error", () => {
    if (active) {
      status = "音乐文件加载失败，可切换另一首";
      render();
    }
  });
  for (const event of ["timeupdate", "loadedmetadata", "durationchange", "pause"])
    audio.addEventListener(event, render);
  // Keep arrow keys and drag gestures inside the player instead of turning the book cover.
  panel.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") event.stopPropagation();
  });
  window.addEventListener("pagehide", stop);
  render();
  return {
    start,
    stop,
    mount,
    getState: () => ({
      active,
      playing: active && !audio.paused,
      track,
      title: TRACKS[track].title,
      time: audio.currentTime,
      volume: audio.volume,
      status,
    }),
  };
}
