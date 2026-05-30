/* ==========================================================================
   KI-News – Klick-zum-Laden für eingebettete Medien (2-Klick-Lösung, DSGVO)
   Lädt YouTube / SoundCloud / Vimeo / X erst nach aktivem Klick des Nutzers.
   Vorher: neutraler Platzhalter, KEINE Verbindung zum Anbieter, keine Cookies.

   Verwendung in vorhandenem Code:
     KIEmbed.youtube(videoId, {label:'VIDEO'})  -> HTML-String (Platzhalter)
     KIEmbed.soundcloud(playerUrl, {height:80}) -> HTML-String
     KIEmbed.vimeo(videoId)                      -> HTML-String
   X/Twitter-Blockquotes (<blockquote class="twitter-tweet">) werden automatisch
   erkannt und in Platzhalter verwandelt – einfach widgets.js NICHT mehr laden.
   ========================================================================== */
(function () {
  function h(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var PROVIDER = {
    youtube:    { name: 'YouTube',     transfer: 'Google (USA)' },
    soundcloud: { name: 'SoundCloud',  transfer: 'SoundCloud' },
    vimeo:      { name: 'Vimeo',       transfer: 'Vimeo (USA)' },
    twitter:    { name: 'X (Twitter)', transfer: 'X / Twitter' }
  };

  var ICON = '<svg viewBox="0 -960 960 960" width="34" height="34" fill="currentColor" aria-hidden="true"><path d="M320-200v-560l440 280-440 280Z"></path></svg>';

  function shell(kind, label, pad, inner) {
    var p = PROVIDER[kind] || { name: kind, transfer: kind };
    var ratio = pad ? ('padding-top:' + pad + ';') : 'min-height:120px;';
    return '' +
      '<div class="ki-embed" data-embed-loaded="0" role="button" tabindex="0" ' +
        'aria-label="Inhalt von ' + h(p.name) + ' laden" ' +
        'style="position:relative;width:100%;' + ratio + 'cursor:pointer;background:#0e1014;' +
        'border:1px solid rgba(127,127,127,0.22);border-radius:8px;overflow:hidden;">' + inner +
        '<div class="ki-embed-ph" style="position:absolute;inset:0;display:flex;flex-direction:column;' +
          'align-items:center;justify-content:center;gap:8px;text-align:center;padding:18px;color:#cbd5e1;">' +
          (label ? '<span style="position:absolute;top:8px;left:8px;background:rgba(127,127,127,0.18);' +
            'font-size:9px;font-weight:700;letter-spacing:0.08em;padding:2px 7px;border-radius:3px;' +
            'font-family:\'Space Grotesk\',sans-serif;text-transform:uppercase;">' + h(label) + '</span>' : '') +
          '<span style="display:flex;align-items:center;justify-content:center;width:58px;height:58px;' +
            'border-radius:50%;background:rgba(29,155,240,0.15);color:#1d9bf0;">' + ICON + '</span>' +
          '<span style="font-family:\'Space Grotesk\',sans-serif;font-weight:700;font-size:14px;color:#e7e9ea;">' +
            h(p.name) + ' laden</span>' +
          '<span style="font-size:11px;line-height:1.5;color:#7b8794;max-width:300px;">Mit dem Laden ' +
            'stimmst du zu, dass Daten an ' + h(p.transfer) + ' übertragen werden. ' +
            'Siehe <a href="/Datenschutz.html" style="color:#1d9bf0;text-decoration:underline;" ' +
            'onclick="event.stopPropagation()">Datenschutz</a>.</span>' +
        '</div>' +
      '</div>';
  }

  var KIEmbed = {
    youtube: function (id, o) {
      o = o || {};
      return shell('youtube', o.label || 'VIDEO', '56.25%',
        '<span data-embed-kind="youtube" data-embed-id="' + h(id) + '" style="display:none"></span>');
    },
    vimeo: function (id, o) {
      o = o || {};
      return shell('vimeo', o.label || 'VIDEO', '56.25%',
        '<span data-embed-kind="vimeo" data-embed-id="' + h(id) + '" style="display:none"></span>');
    },
    soundcloud: function (url, o) {
      o = o || {};
      var hgt = o.height || 120;
      return shell('soundcloud', o.label || 'PODCAST', null,
        '<span data-embed-kind="soundcloud" data-embed-url="' + h(url) + '" data-embed-h="' + hgt + '" style="display:none"></span>');
    }
  };
  window.KIEmbed = KIEmbed;

  function iframeFor(meta) {
    var kind = meta.getAttribute('data-embed-kind');
    var f = document.createElement('iframe');
    f.setAttribute('frameborder', '0');
    f.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;border:0;';
    if (kind === 'youtube') {
      f.src = 'https://www.youtube-nocookie.com/embed/' + meta.getAttribute('data-embed-id') + '?autoplay=1&rel=0';
      f.allow = 'accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture';
      f.allowFullscreen = true;
    } else if (kind === 'vimeo') {
      f.src = 'https://player.vimeo.com/video/' + meta.getAttribute('data-embed-id') + '?autoplay=1';
      f.allow = 'autoplay;fullscreen;picture-in-picture';
      f.allowFullscreen = true;
    } else if (kind === 'soundcloud') {
      var url = meta.getAttribute('data-embed-url');
      f.src = url + (url.indexOf('auto_play') === -1 ? '&auto_play=true' : '');
      f.allow = 'autoplay';
      f.setAttribute('scrolling', 'no');
      f.style.cssText = 'position:static;width:100%;height:' + (meta.getAttribute('data-embed-h') || 120) + 'px;border:0;border-radius:6px;';
    }
    return f;
  }

  function activate(box) {
    if (!box || box.getAttribute('data-embed-loaded') === '1') return;
    var meta = box.querySelector('[data-embed-kind]');
    if (!meta) return;
    box.setAttribute('data-embed-loaded', '1');
    var ph = box.querySelector('.ki-embed-ph');
    if (ph) ph.remove();
    if (meta.getAttribute('data-embed-kind') === 'soundcloud') box.style.paddingTop = '0';
    box.appendChild(iframeFor(meta));
  }

  // ── X / Twitter: Blockquotes erst auf Klick laden ──
  var twLoaded = false;
  function loadTwitter() {
    if (twLoaded) { if (window.twttr && twttr.widgets) twttr.widgets.load(); return; }
    twLoaded = true;
    var s = document.createElement('script');
    s.async = true; s.charset = 'utf-8';
    s.src = 'https://platform.twitter.com/widgets.js';
    document.body.appendChild(s);
  }

  function wrapTweets(root) {
    var quotes = (root || document).querySelectorAll('blockquote.twitter-tweet:not([data-ki-wrapped])');
    for (var i = 0; i < quotes.length; i++) {
      (function (bq) {
        bq.setAttribute('data-ki-wrapped', '1');
        var link = bq.querySelector('a');
        var href = link ? link.getAttribute('href') : '#';
        bq.style.display = 'none';
        var ph = document.createElement('div');
        ph.className = 'ki-embed-tw';
        ph.setAttribute('role', 'button');
        ph.setAttribute('tabindex', '0');
        ph.style.cssText = 'width:100%;max-width:520px;margin:0 auto;cursor:pointer;background:#0e1014;' +
          'border:1px solid rgba(127,127,127,0.22);border-radius:10px;padding:22px 18px;text-align:center;color:#cbd5e1;';
        ph.innerHTML =
          '<div style="font-family:\'Space Grotesk\',sans-serif;font-weight:700;font-size:14px;color:#e7e9ea;margin-bottom:6px;">' +
            'Beitrag von X laden</div>' +
          '<div style="font-size:11px;line-height:1.5;color:#7b8794;max-width:340px;margin:0 auto;">' +
            'Mit dem Laden stimmst du zu, dass Daten an X / Twitter übertragen werden. ' +
            '<a href="/Datenschutz.html" style="color:#1d9bf0;text-decoration:underline;">Datenschutz</a> · ' +
            '<a href="' + h(href) + '" target="_blank" rel="noopener" style="color:#1d9bf0;text-decoration:underline;" ' +
            'onclick="event.stopPropagation()">Direkt auf X öffnen</a></div>';
        function go() { ph.remove(); bq.style.display = ''; loadTwitter(); }
        ph.addEventListener('click', go);
        ph.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
        bq.parentNode.insertBefore(ph, bq);
      })(quotes[i]);
    }
  }

  // ── Delegierte Klicks für Medien-Platzhalter (auch dynamisch eingefügt) ──
  document.addEventListener('click', function (e) {
    var box = e.target.closest ? e.target.closest('.ki-embed') : null;
    if (box && !e.target.closest('a')) activate(box);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var box = e.target.closest ? e.target.closest('.ki-embed') : null;
    if (box) { e.preventDefault(); activate(box); }
  });

  function init() {
    wrapTweets(document);
    if (window.MutationObserver) {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++)
          for (var j = 0; j < muts[i].addedNodes.length; j++) {
            var n = muts[i].addedNodes[j];
            if (n.nodeType === 1 && n.querySelectorAll) wrapTweets(n);
          }
      }).observe(document.body, { childList: true, subtree: true });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
