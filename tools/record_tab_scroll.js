// Запись вкладки с плавным скроллом (LinkedIn Jobs / Indeed / любой сайт) — вставить в консоль DevTools.
// 1) Открой страницу с вакансиями, разверни окно. 2) F12 → Console → вставь скрипт → Enter
//    (если Chrome просит — сначала напечатай  allow pasting  и Enter). 3) Нажми розовую кнопку «● REC»,
//    в окне выбора выбери ЭТУ вкладку → «Поделиться». Дальше всё само: скролл ~9 с и скачивание .webm.
// Аватарки и имя в шапке и окно сообщений скрываются, чтобы в запись не попали личные данные.
(() => {
  const css = document.createElement('style');
  css.textContent = `
    header img, nav img, #global-nav img, .global-nav__me, .global-nav__me-photo,
    [data-gnav-element-name="AccountMenu"], #msg-overlay, [class*="msg-overlay"], aside[class*="msg"],
    [class*="artdeco-toasts"], #gnav-main-container [aria-label*="Account" i] { visibility: hidden !important; }
    html { scroll-behavior: auto !important; }`;
  document.head.appendChild(css);

  // самый «длинный» прокручиваемый блок со списком (у LinkedIn список слева — свой скролл), иначе страница
  const scrollers = [...document.querySelectorAll('*')].filter(el => {
    const s = getComputedStyle(el);
    return /(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 300 && el.clientHeight > 300;
  }).sort((a, b) => b.querySelectorAll('li').length - a.querySelectorAll('li').length);
  const box = scrollers[0] || document.scrollingElement;
  const ease = t => 0.5 - 0.5 * Math.cos(Math.PI * t);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const scrollBy = (dy, ms) => new Promise(done => {
    const y0 = box.scrollTop, t0 = performance.now();
    const step = now => {
      const t = Math.min(1, (now - t0) / ms);
      box.scrollTop = y0 + dy * ease(t);
      t < 1 ? requestAnimationFrame(step) : done();
    };
    requestAnimationFrame(step);
  });

  const btn = document.createElement('button');
  btn.textContent = '● REC';
  btn.style.cssText = 'position:fixed;z-index:2147483647;right:24px;bottom:24px;padding:14px 22px;' +
    'font:700 18px system-ui;color:#fff;background:#fe2c55;border:0;border-radius:30px;cursor:pointer';
  document.body.appendChild(btn);
  btn.onclick = async () => {
    btn.remove();
    let stream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 30, width: { ideal: 2560 }, height: { ideal: 1440 } },
        audio: false, preferCurrentTab: true, selfBrowserSurface: 'include'
      });
    } catch (e) { alert('Запись отменена: ' + e.message); return; }
    const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9') ? 'video/webm;codecs=vp9' : 'video/webm';
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 16e6 });
    const chunks = [];
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob(chunks, { type: 'video/webm' }));
      a.download = location.hostname.replace('www.', '').split('.')[0] + '_scroll.webm';
      document.body.appendChild(a); a.click();
    };
    await sleep(900);                 // подождать, пока исчезнет плашка «Идёт запись»
    rec.start(200);
    await sleep(1200);                // стоим на первом экране
    await scrollBy(box.clientHeight * 0.9, 2600);
    await sleep(800);
    await scrollBy(box.clientHeight * 0.9, 2600);
    await sleep(1000);
    rec.stop();
  };
  return 'Готово: нажми розовую кнопку «● REC» справа внизу';
})();
