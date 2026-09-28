/* ki-logos.js (28.09.26): Hersteller-Logos zum schnellen Zuordnen ohne Lesen.
   Quelle: Simple Icons (CC0-1.0), https://simpleicons.org - Markenzeichen gehoeren den
   jeweiligen Firmen und werden nur zur Kennzeichnung genutzt. Dateien in assets/logos/.
   window.kiLogoUrl(name)  -> Pfad zur SVG oder ""
   window.kiLogoEl(name, px) -> <span class="ki-logo"><img></span> oder null */
(function () {
  'use strict';
  var ROOT = (typeof window.KI_ROOT === 'string') ? window.KI_ROOT : (/\/artikel\//.test(location.pathname) ? '../' : '');
  var ALIAS = [
    [/openai|chatgpt|\bgpt[\s-]?\d|\bsora\b|\bo\d\b/, 'openai'],
    [/claude/, 'claude'],
    [/anthropic/, 'anthropic'],
    [/gemini|gemma|\bveo\b|imagen|lyria/, 'googlegemini'],
    [/google|deepmind|alphabet/, 'google'],
    [/\bmeta\b|facebook|llama|meta-llama|\bmuse\b/, 'meta'],
    [/nvidia|nemotron/, 'nvidia'],
    [/mistral|magistral|codestral|devstral|voxtral|pixtral/, 'mistralai'],
    [/\bx-?ai\b|\bgrok\b/, 'x'],
    [/qwen|alibaba/, 'qwen'],
    [/deepseek/, 'deepseek'],
    [/hugging\s?face/, 'huggingface'],
    [/microsoft|copilot(?!.*github)|\bphi-?\d/, 'microsoft'],
    [/github/, 'githubcopilot'],
    [/\bapple\b/, 'apple'],
    [/amazon|\baws\b|nova/, 'amazon'],
    [/eleven\s?labs|\beleven\b/, 'elevenlabs'],
    [/perplexity|\bsonar\b/, 'perplexity'],
    [/\bibm\b|granite/, 'ibm'],
    [/\bintel\b/, 'intel'],
    [/\bamd\b/, 'amd'],
    [/xiaomi|mimo/, 'xiaomi'],
    [/baidu|ernie/, 'baidu'],
    [/bytedance|seedance|seedream|doubao|tiktok/, 'bytedance'],
    [/samsung/, 'samsung'],
    [/moonshot|\bkimi\b/, 'moonshotai'],
    [/minimax|hailuo/, 'minimax'],
    [/cursor/, 'cursor'],
    [/tesla/, 'tesla']
  ];
  function slug(name) {
    var n = String(name || '').toLowerCase();
    if (!n) return '';
    for (var i = 0; i < ALIAS.length; i++) if (ALIAS[i][0].test(n)) return ALIAS[i][1];
    return '';
  }
  window.kiLogoUrl = function (name) {
    var s = slug(name);
    return s ? ROOT + 'assets/logos/' + s + '.svg' : '';
  };
  window.kiLogoEl = function (name, px) {
    var url = window.kiLogoUrl(name);
    if (!url) return null;
    var size = px || 22;
    var wrap = document.createElement('span');
    wrap.className = 'ki-logo';
    wrap.style.cssText = 'display:inline-grid;place-items:center;flex:0 0 auto;width:' + size + 'px;height:' + size +
      'px;border-radius:50%;background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.08)';
    var img = document.createElement('img');
    img.src = url;
    img.alt = '';
    img.width = img.height = Math.round(size * 0.62);
    img.decoding = 'async';
    img.addEventListener('error', function () { wrap.remove(); }, { once: true });
    wrap.appendChild(img);
    return wrap;
  };
  /* 29.09.26: kiLogosAuto(selector) - setzt ein kleines Logo vor jede passende Ueberschrift,
     auch fuer spaeter nachgeladene Inhalte (MutationObserver). Nur ein Logo je Element. */
  window.kiLogosAuto = function (selector, px) {
    var sel = selector || 'main h2, main h3';
    function deko(root) {
      var els = (root.querySelectorAll ? root.querySelectorAll(sel) : []);
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (el.__kiLogo || el.closest('nav, header, .ki-nav, #kl-nav, .ki-logo')) continue;
        el.__kiLogo = true;
        var logo = window.kiLogoEl(el.textContent.slice(0, 160), px || 20);
        if (!logo) continue;
        logo.style.marginRight = '8px';
        logo.style.verticalAlign = '-3px';
        el.insertBefore(logo, el.firstChild);
      }
    }
    function start() {
      deko(document);
      try {
        var t = null;
        new MutationObserver(function () { if (t) return; t = setTimeout(function () { t = null; deko(document); }, 250); })
          .observe(document.body, { childList: true, subtree: true });
      } catch (e) {}
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  };
})();
