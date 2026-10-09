import { createBarGlass } from "./ui/bar-glass.js";
import { createWindowChrome } from "./ui/window-chrome.js";

// The bar first, and independently of the scene: it is the window's title bar, and it has to be
// usable — draggable, closable — while the model is still loading.
const bar = document.getElementById("bar");
if (bar) {
  createBarGlass(bar);
  createWindowChrome({ bar });
}

// Show a useful boot failure even when a dependency import or GLB fetch fails.
const loading = document.getElementById("loading");
if (location.protocol === "file:") {
  loading.querySelector("p").textContent =
    "模块化版本需要本地服务：请在项目目录执行 npm start，再打开 http://localhost:8080";
} else {
  import("./app.js")
    .then(({ startLibrary }) => startLibrary())
    .catch((error) => {
      console.error("Library startup failed", error);
      loading.style.display = "grid";
      loading.classList.add("error");
      loading.querySelector("strong").textContent = "空间加载未完成";
      loading.querySelector("p").textContent =
        error.message + "。请检查模型文件是否完整，然后刷新页面。";
    });
}
