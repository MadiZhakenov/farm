// TikTok scene finder (1265) — запускается вручную в консоли твоего Chrome на открытой странице TikTok
// (хэштег /tag/..., профиль /@..., поиск /search/video?q=...). Берёт ролики, которые видны на странице,
// по одному с паузой смотрит длительность и просмотры, оставляет цельные сцены 10–30 с без эдитов,
// копит список между запусками (localStorage) и копирует таблицу в буфер обмена.
// Ничего не скачивает — только ссылки.
//
// Как запустить: открой страницу → прокрути немного вниз → F12 → Console → вставь весь файл → Enter.
// (Если Chrome просит — сначала напечатай в консоли: allow pasting)
// Ещё команды в консоли после запуска:  sceneFinder.show()  sceneFinder.copy()  sceneFinder.clear()

// copy() из консоли Chrome доступна только в момент вставки — запоминаем её сразу, до первого await
const __devCopy = typeof copy === 'function' ? copy : null;

(async () => {
  const CFG = {
    minDur: 10, maxDur: 30,      // длительность, с
    minViews: 50000,             // мин. просмотры
    delayMs: 2500,               // пауза между роликами — медленно, как человек
    maxPerRun: 40,               // сколько роликов проверить за запуск
    scrolls: 3,                  // сколько раз докрутить страницу перед сбором
  };
  const KEY = 'scene_finder_1265';
  const EDIT = /edit|\|\||montage|fmv|amv|velocity|capcut|slowmo|transition/i;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch { return {}; } };
  const save = db => localStorage.setItem(KEY, JSON.stringify(db));
  const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'K' : String(n);

  const api = window.sceneFinder = {
    rows() {
      return Object.values(load()).filter(r => r.ok).sort((a, b) => b.views - a.views);
    },
    show() {
      console.table(api.rows().map(r => ({ views: fmt(r.views), dur: r.dur + ' с', author: r.author, desc: r.desc, url: r.url })));
    },
    text() {
      return ['views\tdur\tauthor\tdesc\turl', ...api.rows().map(r => [r.views, r.dur, r.author, r.desc, r.url].join('\t'))].join('\n');
    },
    copy() {
      const tsv = api.text();
      const devCopy = typeof copy === 'function' ? copy : __devCopy;
      try {
        devCopy(tsv);
        console.log(`📋 скопировано строк: ${api.rows().length} — вставь в Excel/Google Sheets или пришли мне`);
      } catch {
        console.log(tsv);
        console.log('📋 не вышло скопировать автоматически — введи в консоли: sceneFinder.copy()  (или выдели текст выше)');
      }
    },
    clear() { localStorage.removeItem(KEY); console.log('список очищен'); },
  };

  for (let i = 0; i < CFG.scrolls; i++) { window.scrollBy(0, 2500); await sleep(1500); }
  const db = load();
  const ids = [...new Set([...document.querySelectorAll('a[href*="/video/"]')]
    .map(a => (a.href.split('?')[0].split('/video/')[1] || '').replace(/\D/g, '')))]
    .filter(id => id && !db[id]).slice(0, CFG.maxPerRun);
  console.log(`🔎 новых роликов на странице: ${ids.length} (уже проверено раньше: ${Object.keys(db).length})`);

  let found = 0;
  const skip = { 'длиннее 30 с': 0, 'короче 10 с': 0, 'мало просмотров': 0, 'эдит': 0, 'не открылся': 0 };
  for (const [k, id] of ids.entries()) {
    let r;
    try {
      r = await fetch('/@_/video/' + id, { credentials: 'include' });
    } catch (e) { console.warn('сеть недоступна — стоп'); break; }
    const html = await r.text();
    if (r.status !== 200 || /Access Denied|captcha/i.test(html.slice(0, 3000))) {
      console.warn('⛔ TikTok ограничил запросы — стоп. Подожди и запусти позже.'); break;
    }
    const m = html.match(/<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([\s\S]*?)<\/script>/);
    let it = null;
    try { it = JSON.parse(m[1]).__DEFAULT_SCOPE__['webapp.video-detail'].itemInfo.itemStruct; } catch {}
    if (!it) { db[id] = { id, ok: false }; skip['не открылся']++; continue; }
    const dur = it.video.duration, views = it.stats.playCount, desc = (it.desc || '').replace(/\s+/g, ' ').slice(0, 90);
    const why = dur > CFG.maxDur ? 'длиннее 30 с' : dur < CFG.minDur ? 'короче 10 с'
      : views < CFG.minViews ? 'мало просмотров' : EDIT.test(desc) ? 'эдит' : null;
    if (why) skip[why]++;
    const ok = !why;
    db[id] = { id, ok, dur, views, author: it.author.uniqueId, desc,
               url: `https://www.tiktok.com/@${it.author.uniqueId}/video/${id}` };
    if (ok) { found++; console.log(`✅ ${dur} с · ${fmt(views)} · @${it.author.uniqueId} · ${desc}`); }
    save(db);
    if (k < ids.length - 1) await sleep(CFG.delayMs);
  }
  save(db);
  console.log(`готово: подходящих в этот раз ${found}, всего в списке ${api.rows().length}`);
  console.log('отсеяно: ' + Object.entries(skip).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join(', '));
  api.show();
  api.copy();
})();
