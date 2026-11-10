"""聚合检索：所有启用书源并发搜索，合并同一本书、按可信度排序，并记录书源健康度。

与旧实现的三点不同：
1. 不再只取前 5 个自定义源——所有启用且支持搜索的源都参与；
2. 每个源独立超时，慢源不会拖住整次检索，结果先到先出；
3. 同一本书在多源命中时合并成一条，附带每个源的下载入口，按书名精确度、
   作者命中、源健康度与响应速度排序，下载失败可自动换下一个源。
"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait

SOURCE_TIMEOUT = 12.0
MAX_WORKERS = 12
MAX_SOURCES = 40
MAX_GROUPS = 60


def _normalize(text):
    import re
    import unicodedata
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(text or "")).casefold())


def rank_bonus(health):
    """书源健康度折算成 0～20 分的排序加分；连续失败会被压下去，成功一次就回来。"""
    if not health:
        return 6
    ok, fail, streak = int(health.get("ok") or 0), int(health.get("fail") or 0), int(health.get("consecutive_fail") or 0)
    score = 8 + min(10, ok) - min(12, streak * 4)
    if ok and not fail:
        score += 2
    return max(-8, min(20, score))


def group_candidates(candidates, query, health=None):
    """同名同作者的结果合并成一条：多源命中说明这本书更可信，也允许换源下载。"""
    health = health or {}
    wanted = _normalize(query)
    groups, order = {}, []
    for item in candidates:
        key = (_normalize(item.get("title"))[:40], _normalize(item.get("author"))[:16])
        if key not in groups:
            groups[key] = {"title": item.get("title") or "", "author": item.get("author") or "",
                           "sources": [], "score": 0.0, "best": None}
            order.append(key)
        entry = groups[key]
        source = {name: item.get(name) for name in ("source_id", "source", "source_key", "source_url", "exact")}
        if not any(existing.get("source_id") == source["source_id"] and existing.get("source_key") == source["source_key"]
                   for existing in entry["sources"]):
            entry["sources"].append(source)
    for key in order:
        entry = groups[key]
        title = _normalize(entry["title"])
        author = _normalize(entry["author"])
        score = 0.0
        score += 42 if title == wanted else 0
        score += 26 if wanted and title.startswith(wanted) and title != wanted else 0
        score += 18 if wanted and wanted in title else 0
        score += 6 if len(entry["sources"]) > 1 else 0
        score += min(12, (len(entry["sources"]) - 1) * 5)
        score += 4 if author and author not in {"未知作者", "见来源页"} else 0
        best_score, best = -999, None
        for source in entry["sources"]:
            bonus = rank_bonus(health.get(source.get("source_id")))
            value = bonus + (3 if source.get("exact") else 0)
            if value > best_score:
                best_score, best = value, source
        entry["score"] = round(score + best_score, 1)
        entry["best"] = best
        entry["count"] = len(entry["sources"])
    return sorted((groups[key] for key in order), key=lambda item: item["score"], reverse=True)[:MAX_GROUPS]


class SearchJobs:
    """一次检索一个任务：先到先出，客户端轮询拿增量结果，也可以取消。"""

    def __init__(self, library):
        self.library = library
        self.lock = threading.Lock()
        self.jobs = {}

    def start(self, query, source_id="all"):
        providers = self.library.search_providers(source_id)
        identifier = uuid.uuid4().hex
        job = {"id": identifier, "query": query, "source": source_id, "state": "searching",
               "total": len(providers), "done": 0, "results": [], "groups": [],
               "errors": [], "finished": [], "cancel": threading.Event(), "started": time.time()}
        with self.lock:
            self.jobs[identifier] = job
            for stale in [key for key, value in self.jobs.items()
                          if value["state"] in {"completed", "cancelled"} and time.time() - value["started"] > 600]:
                self.jobs.pop(stale, None)
        threading.Thread(target=self._run, args=(job, providers), daemon=True).start()
        return self.get(identifier)

    def get(self, identifier, cancel=False):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job:
                raise KeyError(identifier)
            if cancel:
                job["cancel"].set()
            view = {key: value for key, value in job.items() if key != "cancel"}
            view["groups"] = group_candidates(job["results"], job["query"], self.library.health_map())
            return view

    def _run(self, job, providers):
        def search(provider):
            started = time.monotonic()
            try:
                found = provider.search(job["query"]) or []
                self.library.record_health(provider.id, True, int((time.monotonic() - started) * 1000), "")
                return provider, found, None
            except Exception as error:
                message = str(error)[:160] if isinstance(error, (ValueError, KeyError, TypeError)) else "检索失败"
                self.library.record_health(provider.id, False, int((time.monotonic() - started) * 1000), message)
                return provider, [], {"source_id": provider.id, "source_name": getattr(provider, "name", provider.id), "message": message}
        pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        owners = {pool.submit(search, provider): provider for provider in providers}
        deadline = time.monotonic() + SOURCE_TIMEOUT + 4
        pending = set(owners)
        while pending and not job["cancel"].is_set() and time.monotonic() <= deadline:
            reached, pending = wait(pending, timeout=0.3, return_when="FIRST_COMPLETED")
            for future in reached:
                provider, found, error = future.result()
                with self.lock:
                    job["results"].extend(found)
                    if error:
                        job["errors"].append(error)
                    job["finished"].append(provider.id)
                    job["done"] = len(job["finished"])
        for future in list(pending):
            provider = owners[future]
            future.cancel()
            with self.lock:
                job["errors"].append({"source_id": provider.id, "source_name": getattr(provider, "name", provider.id),
                                      "message": "书源响应超时，请稍后重试或单独选择该书源"})
                job["finished"].append(provider.id)
                job["done"] = len(job["finished"])
            self.library.record_health(provider.id, False, int(SOURCE_TIMEOUT * 1000), "响应超时")
        pool.shutdown(wait=False)
        with self.lock:
            job["state"] = "cancelled" if job["cancel"].is_set() else "completed"
            job["groups"] = group_candidates(job["results"], job["query"], self.library.health_map())
