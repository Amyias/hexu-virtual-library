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
  const $ = (id) => panel.querySelector("#" + id);
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

  function render() {
    $("musicTitle").textContent = TRACKS[track].title;
    $("musicStatus").textContent = status;
    const playing = active && !audio.paused;
    panel.classList.toggle("is-playing", playing);
    $("musicToggle").textContent = playing ? "Ⅱ" : "▶";
    $("musicToggle").setAttribute("aria-label", playing ? "暂停音乐" : "播放音乐");
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    $("musicTime").textContent = `${clock(audio.currentTime)} / ${clock(duration)}`;
    $("musicSeek").disabled = duration <= 0;
    $("musicSeek").value = String(
      duration > 0 ? Math.round((audio.currentTime / duration) * 1000) : 0,
    );
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
  }
  function start() {
    if (active) return; // Repeated cover updates must not undo the reader's pause choice.
    active = true;
    panel.hidden = false;
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
