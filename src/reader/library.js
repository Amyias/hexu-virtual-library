import { wakeStripRE, normalize } from '../voice/intent.js';

export function bookQuery(text) {
  return text.replace(wakeStripRE, '').replace(/[《》“”"，。！？,.!?]/g, '').trim()
    .replace(/^(?:(?:我想要|我想|我要|我需要|请|麻烦|帮我|给我|寻找|搜索|下载|阅读|找一下|找一找|找|读|看|一本|的)\s*)+/, '')
    .replace(/(?:这本小说|这本书|的正文|在哪里|在哪)$/, '').trim();
}

export function createLocalLibrary({ books, onSelect, notice }) {
  const samples = books.filter(book => book.placeholder).sort((a, b) => Number(b.shelf === 2) - Number(a.shelf === 2));
  const assigned = new Map();
  const panel = document.createElement('section'); panel.id = 'localLibrary'; panel.hidden = true;
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true'); panel.setAttribute('aria-label', '本地正文书库');
  panel.innerHTML = `<div class="library-dialog"><div class="library-heading"><div><small>YOUR READING COLLECTION</small><h2>本地正文书库</h2></div><button id="closeLibrary" aria-label="关闭正文书库">✕</button></div><p id="libraryStatus" role="status">正在连接本地正文库…</p><form id="librarySearch"><input id="libraryQuery" aria-label="搜索正文书名" placeholder="例如：狂人日记、红楼梦"><select id="librarySource" aria-label="选择书源"><option value="all">所有书源</option></select><button id="searchOnline">在线找正文</button></form><form id="libraryUrlImport"><input id="libraryBookUrl" type="url" aria-label="书籍或目录网址" placeholder="粘贴已导入书源的书籍或目录网址" required><button id="previewBookUrl">读取书籍网址</button></form><div id="downloadRow" hidden><span id="downloadStatus" aria-live="polite"></span><button id="cancelDownload">取消</button></div><div id="libraryResults"></div><div class="library-subheading"><h3>已入库 · 可离线阅读</h3><label class="file-button">导入 TXT / EPUB<input id="importBookFile" type="file" accept=".txt,.epub" hidden></label></div><div id="localBooks"></div><details class="source-import"><summary>书源管理与导入</summary><p>从 <a href="https://www.yckceo.com/yuedu/shuyuan/index.html" target="_blank" rel="noopener noreferrer">源仓库</a> 下载书源 JSON 后导入。支持 CSS、XPath、JSONPath 和纯 JavaScript 规则；书源导入后可在下方勾选启用。仅有目录规则的源可用上方网址入口。Android／Java 专用接口、登录和验证码流程暂不支持。仅获取站点公开提供的免费正文。</p><label class="file-button">导入书源 JSON<input id="importSourceFile" type="file" accept=".json" hidden></label><pre id="sourceReport" role="status"></pre><div id="sourceList"></div></details><details><summary>书库位置</summary><code id="libraryDirectory"></code><p>数据库与 UTF-8 正文保存在程序目录之外，升级不会覆盖。备份时复制整个书库目录。</p></details></div>`;
  document.body.append(panel);
  const button = document.createElement('button'); button.id = 'libraryButton'; button.textContent = '正文书库 ↗';
  document.querySelector('.suggestions').append(button);
  const $ = id => panel.querySelector('#' + id);
  let ready = false, working = false, jobId = null, generation = 0;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function request(path, body, timeout = 45000) {
    const response = await fetch('/library/' + path, { method: body === undefined ? 'GET' : 'POST', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', signal: AbortSignal.timeout(timeout) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '书库请求失败'); return payload;
  }
  function bind(metadata) {
    const book = samples[metadata.slot];
    if (!book) throw new Error('书架可用位置不足');
    Object.assign(book, { title: metadata.title, author: metadata.author, synopsis: metadata.synopsis, category: '本地正文 · ' + metadata.source, localBookId: metadata.id, localAliases: metadata.aliases || [] });
    assigned.set(metadata.id, book); return book;
  }
  function select(metadata) { const book = bind(metadata); panel.hidden = true; onSelect(book); }
  function row(item, action, label) {
    const element = document.createElement('div'); element.className = 'book-result';
    const info = document.createElement('div'), title = document.createElement('strong'), detail = document.createElement('small');
    title.textContent = item.title; detail.textContent = `${item.author} · ${item.source}${item.chapter_count ? ` · ${item.chapter_count} 章` : ''}`;
    info.append(title, detail); const button = document.createElement('button'); button.textContent = label; button.onclick = () => action(item);
    element.append(info, button); return element;
  }
  async function refresh() {
    const result = await request('books');
    result.books.forEach(bind);
    $('localBooks').replaceChildren(...result.books.map(item => row(item, select, '从书架取阅')));
    if (!result.books.length) $('localBooks').textContent = '书库还是空的。搜索一本免费正文，或导入本地 TXT / EPUB。';
    $('libraryStatus').textContent = `已入库 ${result.books.length} 本 · 正文与阅读进度保存在本机`;
    const sources = await request('sources');
    const previous = $('librarySource').value;
    $('librarySource').replaceChildren(new Option('所有可搜索书源', 'all'), ...sources.sources.filter(item => item.enabled && item.capabilities.search).map(item => new Option(item.name, item.id)));
    $('sourceList').replaceChildren(...sources.sources.map(item => {
      const entry = document.createElement('div'); entry.className = 'source-entry';
      const label = document.createElement('label'), toggle = document.createElement('input');
      toggle.type = 'checkbox'; toggle.checked = item.enabled; toggle.disabled = !!item.builtin;
      toggle.setAttribute('aria-label', '启用书源：' + item.name);
      label.append(toggle, document.createTextNode(item.name));
      const detail = document.createElement('small'); detail.textContent = item.builtin ? '内置 · 按书名搜索' : [item.capabilities.search ? '按书名搜索' : '不提供搜索', item.capabilities.url_import ? '网址导入' : ''].filter(Boolean).join(' · ');
      toggle.onchange = async () => {
        toggle.disabled = true;
        try { await request('sources/' + item.id, { enabled: toggle.checked }); await refresh(); }
        catch (error) { toggle.checked = item.enabled; toggle.disabled = false; notice(error.message); }
      };
      entry.append(label, detail); return entry;
    }));
    if ([...$('librarySource').options].some(item => item.value === previous)) $('librarySource').value = previous;
  }
  async function initialize() {
    try { const info = await request('ready'); ready = info.ready; $('libraryDirectory').textContent = info.directory; await refresh(); }
    catch (error) { $('libraryStatus').textContent = error.message; }
  }
  async function download(candidate) {
    if (working) { notice('已有检索或下载正在进行，请等待或取消'); return; }
    working = true; const current = ++generation; $('downloadRow').hidden = false; $('cancelDownload').disabled = false; $('downloadStatus').textContent = '正在创建下载任务…';
    try {
      const job = await request('download', candidate); jobId = job.id;
      while (current === generation) {
        const status = await request('jobs/' + job.id);
        $('downloadStatus').textContent = status.message + (status.total ? `（${status.done}/${status.total}）` : '');
        if (status.state === 'completed') { await refresh(); notice(`《${status.book.title}》正文已下载并上架`); select(status.book); break; }
        if (status.state === 'failed' || status.state === 'cancelled') throw new Error(status.message);
        await wait(800);
      }
    } catch (error) { if (current === generation) { $('downloadStatus').textContent = error.message; notice(error.message); } }
    finally { if (current === generation) { working = false; jobId = null; $('cancelDownload').disabled = true; } }
  }
  async function search(text, auto = false) {
    if (working) { notice('小和正在检索或下载，请等待或取消'); return; }
    if (!ready) await initialize();
    panel.hidden = false;
    const query = bookQuery(text); $('libraryQuery').value = query;
    if (!ready || !query) return;
    const local = find(query);
    if (auto && local) { panel.hidden = true; onSelect(local); return; }
    working = true; const current = ++generation;
    $('searchOnline').disabled = true; $('libraryResults').textContent = '正在检索书源，找到后可下载完整正文…';
    try {
      const result = await request('search?q=' + encodeURIComponent(query) + '&source=' + encodeURIComponent($('librarySource').value));
      if (current !== generation) return;
      result.results.forEach(item => { item.aliases = [query]; });
      $('libraryResults').replaceChildren(...result.local.map(item => row(item, select, '阅读本地正文')), ...result.results.map(item => row(item, download, '下载并上架')));
      const exact = result.results.filter(item => item.exact || normalize(item.title) === normalize(query));
      const localExact = result.local.filter(item => [item.title, ...(item.aliases || [])].some(title => normalize(title) === normalize(query)));
      const preferred = exact.length === 1 ? exact[0] : result.results.length === 1 ? result.results[0] : null;
      if (!result.results.length && !result.local.length) $('libraryResults').textContent = '没有找到可下载正文。可换源或导入 TXT / EPUB。' + result.errors.map(item => item.message).join('；');
      else if (result.errors.length) { const note = document.createElement('p'); note.textContent = '部分书源暂不可用：' + result.errors.map(item => item.message).join('；'); $('libraryResults').append(note); }
      working = false;
      if (auto && localExact.length === 1) select(localExact[0]);
      else if (auto && preferred && !result.local.length) { $('cancelDownload').disabled = false; await download(preferred); }
    } catch (error) { if (current === generation) $('libraryResults').textContent = error.message; }
    finally { if (current === generation) working = false; $('searchOnline').disabled = working; }
  }
  button.onclick = () => { panel.hidden = false; if (!ready) initialize(); else refresh().catch(error => notice(error.message)); };
  $('closeLibrary').onclick = () => { panel.hidden = true; };
  $('librarySearch').onsubmit = event => { event.preventDefault(); search($('libraryQuery').value); };
  $('libraryUrlImport').onsubmit = async event => {
    event.preventDefault();
    if (working) { notice('请等待当前检索或下载完成'); return; }
    working = true; $('previewBookUrl').disabled = true;
    $('libraryResults').textContent = '正在根据书源读取书籍信息…';
    try {
      const candidate = await request('url', { url: $('libraryBookUrl').value.trim() });
      $('libraryResults').replaceChildren(row(candidate, download, '下载并上架'));
    } catch (error) { $('libraryResults').textContent = error.message; }
    finally { working = false; $('previewBookUrl').disabled = false; }
  };
  $('cancelDownload').onclick = async () => { if (jobId) { await request('jobs/' + jobId, {}).catch(() => {}); generation++; working = false; jobId = null; $('downloadStatus').textContent = '已请求取消，已入库的书不受影响'; $('searchOnline').disabled = false; } };
  $('importBookFile').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error('文件超过 8 MiB');
      $('libraryStatus').textContent = '正在导入并解析章节…';
      const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const book = await request('import', { filename: file.name, data: btoa(binary) }); await refresh(); notice(`《${book.title}》已导入并上架`);
    } catch (error) { notice(error.message); $('libraryStatus').textContent = error.message; }
    event.target.value = '';
  };
  $('importSourceFile').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    try { if (file.size > 1024 * 1024) throw new Error('书源文件超过 1 MiB'); const result = await request('sources', { sources: JSON.parse((await file.text()).replace(/^\uFEFF/, '')) });
      $('sourceReport').textContent = `成功导入 ${result.accepted.length} 个（已启用 ${result.accepted.filter(item => item.enabled).length} 个），未导入 ${result.rejected.length} 个\n` + [
        ...result.accepted.map(item => `${item.name}：${item.enabled ? '已启用' : '已停用'} · ${[item.capabilities.search ? '支持搜索' : '', item.capabilities.url_import ? '支持网址导入' : ''].filter(Boolean).join('、')}`),
        ...result.rejected.map(item => `${item.name}：${item.message}`)].join('\n'); await refresh(); }
    catch (error) { $('sourceReport').textContent = error.message; }
    event.target.value = '';
  };
  initialize();
  function find(text) { return [...assigned.values()].find(book => [book.title, ...book.localAliases].some(title => normalize(title) === normalize(bookQuery(text)))); }
  return { search, refresh, find, get busy() { return working; }, get opened() { return !panel.hidden; }, close() { panel.hidden = true; }, getState: () => ({ ready, count: assigned.size, working, jobId }) };
}
