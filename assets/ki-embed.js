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

  // ── Einwilligung merken (pro Anbieter) ───────────────────────────────────
  // Klickt der Nutzer einmal „laden", merken wir das in localStorage und laden
  // diesen Anbieter beim nächsten Besuch/weiteren Beiträgen automatisch –
  // kein erneutes Akzeptieren nötig. Gilt hier nur für X (kein Auto-Play-Risiko).
  var CONSENT_KEY = 'ki_embed_consent';
  function getConsent() { try { return JSON.parse(localStorage.getItem(CONSENT_KEY) || '{}'); } catch (e) { return {}; } }
  function saveConsent(c) { try { localStorage.setItem(CONSENT_KEY, JSON.stringify(c)); } catch (e) {} }
  function hasConsent(p) { return !!getConsent()[p]; }
  function setConsent(p) { var c = getConsent(); c[p] = 1; saveConsent(c); }
  function consentDecided() { return !!getConsent().__decided; }
  function allowAllPreviews() { var c = getConsent(); c.twitter = 1; c.youtube = 1; c.soundcloud = 1; c.vimeo = 1; c.__decided = 1; saveConsent(c); }
  function declinePreviews() { saveConsent({ __decided: 1 }); }

  var PROVIDER = {
    youtube:    { name: 'YouTube',     transfer: 'Google (USA)' },
    soundcloud: { name: 'SoundCloud',  transfer: 'SoundCloud' },
    vimeo:      { name: 'Vimeo',       transfer: 'Vimeo (USA)' },
    twitter:    { name: 'X (Twitter)', transfer: 'X / Twitter' }
  };

  var ICON = '<svg viewBox="0 -960 960 960" width="34" height="34" fill="currentColor" aria-hidden="true"><path d="M320-200v-560l440 280-440 280Z"></path></svg>';

  function shell(kind, label, pad, inner, bg) {
    var p = PROVIDER[kind] || { name: kind, transfer: kind };
    var ratio = pad ? ('padding-top:' + pad + ';') : 'min-height:120px;';
    // Optionales Vorschaubild (z. B. YouTube-Standbild): liegt UNTER dem
    // Consent-Overlay. Es wird per <img> geladen – beim YouTube-Thumbnail
    // bedeutet das einen Bild-Abruf von i.ytimg.com (Google) vor dem Klick.
    // Der eigentliche Player startet weiterhin erst nach aktivem Klick.
    var bgImg = bg
      ? '<img src="' + h(bg) + '" alt="" loading="lazy" referrerpolicy="no-referrer" ' +
        'onerror="this.style.display=\'none\'" ' +
        'style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;">' +
        '<div style="position:absolute;inset:0;background:rgba(8,10,14,0.55);z-index:0;"></div>'
      : '';
    // Bei vorhandenem Standbild den Consent-Text dezenter (kleiner) zeigen.
    var phBg = bg ? 'background:transparent;' : '';
    return '' +
      '<div class="ki-embed' + (bg ? ' ki-embed-thumb' : '') + '" data-embed-loaded="0" role="button" tabindex="0" ' +
        'aria-label="Inhalt von ' + h(p.name) + ' laden" ' +
        'style="position:relative;width:100%;' + ratio + 'cursor:pointer;background:#0e1014;' +
        'border:1px solid rgba(127,127,127,0.22);border-radius:8px;overflow:hidden;">' + bgImg + inner +
        '<div class="ki-embed-ph" style="position:absolute;inset:0;z-index:1;display:flex;flex-direction:column;' +
          'align-items:center;justify-content:center;gap:8px;text-align:center;padding:18px;color:#cbd5e1;' + phBg + '">' +
          (label ? '<span style="position:absolute;top:8px;left:8px;background:rgba(8,10,14,0.55);' +
            'font-size:9px;font-weight:700;letter-spacing:0.08em;padding:2px 7px;border-radius:3px;' +
            'font-family:\'Space Grotesk\',sans-serif;text-transform:uppercase;">' + h(label) + '</span>' : '') +
          '<span style="display:flex;align-items:center;justify-content:center;width:58px;height:58px;' +
            'border-radius:50%;background:' + (bg ? 'rgba(220,38,38,0.92)' : 'rgba(29,155,240,0.15)') + ';' +
            'color:' + (bg ? '#fff' : '#1d9bf0') + ';box-shadow:' + (bg ? '0 4px 18px rgba(0,0,0,0.45)' : 'none') + ';">' + ICON + '</span>' +
          '<span style="font-family:\'Space Grotesk\',sans-serif;font-weight:700;font-size:14px;color:#e7e9ea;' +
            (bg ? 'text-shadow:0 1px 6px rgba(0,0,0,0.7);' : '') + '">' +
            h(p.name) + ' laden</span>' +
          '<span style="font-size:11px;line-height:1.5;color:' + (bg ? '#cbd5e1' : '#7b8794') + ';max-width:300px;' +
            (bg ? 'text-shadow:0 1px 6px rgba(0,0,0,0.7);' : '') + '">Mit dem Laden ' +
            'stimmst du zu, dass Daten an ' + h(p.transfer) + ' übertragen werden. ' +
            'Siehe <a href="/Datenschutz.html" style="color:#7cc4ff;text-decoration:underline;" ' +
            'onclick="event.stopPropagation()">Datenschutz</a>.</span>' +
        '</div>' +
      '</div>';
  }

  var KIEmbed = {
    youtube: function (id, o) {
      o = o || {};
      // Lite-Embed: YouTube-Standbild als Vorschau, Player erst bei Klick.
      // o.thumb = false schaltet das Bild ab (strikter 2-Klick ohne Google-Kontakt).
      var thumb = (o.thumb === false) ? null
        : (o.thumb || ('https://i.ytimg.com/vi/' + id + '/hqdefault.jpg'));
      return shell('youtube', o.label || 'VIDEO', '56.25%',
        '<span data-embed-kind="youtube" data-embed-id="' + h(id) + '" style="display:none"></span>',
        thumb);
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

  // Öffentlich, damit Seiten nach dynamisch eingefügten <blockquote> die
  // 2-Klick-Umwandlung anstoßen können (MutationObserver erfasst direkt per
  // innerHTML gesetzte Blockquotes nicht zuverlässig).
  KIEmbed.wrapTweets = function (root) { wrapTweets(root || document); };

  function iframeFor(meta, autoplay) {
    var kind = meta.getAttribute('data-embed-kind');
    var f = document.createElement('iframe');
    f.setAttribute('frameborder', '0');
    f.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;border:0;';
    if (kind === 'youtube') {
      f.src = 'https://www.youtube-nocookie.com/embed/' + meta.getAttribute('data-embed-id') + '?rel=0' + (autoplay ? '&autoplay=1' : '');
      f.allow = 'accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture';
      f.allowFullscreen = true;
    } else if (kind === 'vimeo') {
      f.src = 'https://player.vimeo.com/video/' + meta.getAttribute('data-embed-id') + (autoplay ? '?autoplay=1' : '');
      f.allow = 'autoplay;fullscreen;picture-in-picture';
      f.allowFullscreen = true;
    } else if (kind === 'soundcloud') {
      var url = meta.getAttribute('data-embed-url');
      f.src = autoplay && url.indexOf('auto_play') === -1 ? (url + '&auto_play=true') : url;
      f.allow = 'autoplay';
      f.setAttribute('scrolling', 'no');
      f.style.cssText = 'position:static;width:100%;height:' + (meta.getAttribute('data-embed-h') || 120) + 'px;border:0;border-radius:6px;';
    }
    return f;
  }

  function activate(box, autoplay) {
    if (!box || box.getAttribute('data-embed-loaded') === '1') return;
    var meta = box.querySelector('[data-embed-kind]');
    if (!meta) return;
    box.setAttribute('data-embed-loaded', '1');
    var ph = box.querySelector('.ki-embed-ph');
    if (ph) ph.remove();
    if (meta.getAttribute('data-embed-kind') === 'soundcloud') box.style.paddingTop = '0';
    box.appendChild(iframeFor(meta, autoplay !== false));
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

  // ── Tweet-Vorschaubild ───────────────────────────────────────────────────
  // Das Bild wird im Admin (CORS-fähig) geholt und in media.json gespeichert.
  // Hier auf der Besucherseite wird NUR das fertige Bild angezeigt – kein
  // Fremd-Abruf beim Besucher, kein CORS-Problem.
  function applyPreviewImage(ph, img) {
    if (!img) return;
    ph.style.padding = '0';
    ph.style.minHeight = '210px';
    ph.style.overflow = 'hidden';
    var im = document.createElement('img');
    im.src = img; im.loading = 'lazy'; im.alt = ''; im.referrerPolicy = 'no-referrer';
    im.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;opacity:0;transition:opacity .3s;';
    im.onload = function () { im.style.opacity = '1'; };
    im.onerror = function () { im.remove(); ov.remove(); ph.style.padding = '22px 18px'; ph.style.minHeight = ''; };
    var ov = document.createElement('div');
    ov.style.cssText = 'position:absolute;inset:0;background:linear-gradient(180deg,rgba(8,10,14,0.12) 0%,rgba(8,10,14,0.10) 45%,rgba(8,10,14,0.55) 100%);z-index:0;';
    ph.insertBefore(ov, ph.firstChild);
    ph.insertBefore(im, ph.firstChild);
  }
  function tweetIdFrom(href) { var m = (href || '').match(/status(?:es)?\/(\d+)/); return m ? m[1] : ''; }

  function wrapTweets(root) {
    var quotes = (root || document).querySelectorAll('blockquote.twitter-tweet:not([data-ki-wrapped])');
    for (var i = 0; i < quotes.length; i++) {
      (function (bq) {
        bq.setAttribute('data-ki-wrapped', '1');
        var link = bq.querySelector('a');
        var href = link ? link.getAttribute('href') : '#';
        var tid = tweetIdFrom(href);
        var manualImg = bq.getAttribute('data-ki-preview') || '';
        // Einwilligung schon erteilt? Tweet direkt laden, keinen Platzhalter zeigen.
        if (hasConsent('twitter')) { loadTwitter(); return; }
        bq.style.display = 'none';
        var ph = document.createElement('div');
        ph.className = 'ki-embed-tw';
        ph.setAttribute('role', 'button');
        ph.setAttribute('tabindex', '0');
        ph.style.cssText = 'position:relative;width:100%;max-width:520px;margin:0 auto;cursor:pointer;background:#0e1014;' +
          'border:1px solid rgba(127,127,127,0.22);border-radius:10px;padding:22px 18px;text-align:center;color:#cbd5e1;' +
          'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;';
        ph.innerHTML =
          '<div style="position:relative;z-index:2;display:inline-flex;flex-direction:column;gap:5px;align-items:center;' +
            'background:rgba(8,10,14,0.62);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);' +
            'border:1px solid rgba(255,255,255,0.10);border-radius:12px;padding:14px 18px;max-width:88%;">' +
            '<div style="font-family:\'Space Grotesk\',sans-serif;font-weight:700;font-size:14px;color:#fff;">' +
              '▶ Beitrag von X laden</div>' +
            '<div style="font-size:11px;line-height:1.5;color:#cfd7df;max-width:320px;margin:0 auto;">' +
              'Mit dem Laden stimmst du zu, dass Daten an X / Twitter übertragen werden. ' +
              '<a href="/Datenschutz.html" style="color:#7cc4ff;text-decoration:underline;">Datenschutz</a> · ' +
              '<a href="' + h(href) + '" target="_blank" rel="noopener" style="color:#7cc4ff;text-decoration:underline;" ' +
              'onclick="event.stopPropagation()">Direkt auf X öffnen</a></div>' +
          '</div>';
        function go() { setConsent('twitter'); ph.remove(); bq.style.display = ''; loadTwitter(); }
        ph.addEventListener('click', go);
        ph.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
        bq.parentNode.insertBefore(ph, bq);
        // Vorschaubild (im Admin geholt, in media.json gespeichert) anzeigen
        if (manualImg) applyPreviewImage(ph, manualImg);
      })(quotes[i]);
    }
  }

  // ── Delegierte Klicks für Medien-Platzhalter (auch dynamisch eingefügt) ──
  document.addEventListener('click', function (e) {
    var box = e.target.closest ? e.target.closest('.ki-embed') : null;
    if (box && !e.target.closest('a')) { setConsent(boxKind(box)); activate(box); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var box = e.target.closest ? e.target.closest('.ki-embed') : null;
    if (box) { e.preventDefault(); setConsent(boxKind(box)); activate(box); }
  });
  function boxKind(box) { var m = box.querySelector('[data-embed-kind]'); return m ? m.getAttribute('data-embed-kind') : ''; }

  // ── Auto-Laden nach Einwilligung: Medien lazy beim Scrollen (ohne Autoplay) ──
  var io = ('IntersectionObserver' in window) ? new IntersectionObserver(function (entries) {
    entries.forEach(function (en) { if (en.isIntersecting) { io.unobserve(en.target); activate(en.target, false); } });
  }, { rootMargin: '300px 0px' }) : null;
  function autoLoadMedia(root) {
    var boxes = (root || document).querySelectorAll('.ki-embed[data-embed-loaded="0"]');
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i], m = box.querySelector('[data-embed-kind]');
      if (m && hasConsent(m.getAttribute('data-embed-kind'))) {
        if (io) io.observe(box); else activate(box, false);
      }
    }
  }
  function loadAllConsented() {
    // X: Platzhalter entfernen, Blockquotes anzeigen, Widget laden
    if (hasConsent('twitter')) {
      var phs = document.querySelectorAll('.ki-embed-tw');
      for (var i = 0; i < phs.length; i++) phs[i].remove();
      var bqs = document.querySelectorAll('blockquote.twitter-tweet');
      for (var j = 0; j < bqs.length; j++) bqs[j].style.display = '';
      if (bqs.length) loadTwitter();
    }
    autoLoadMedia(document);
  }

  // ── Consent-Banner (einmalig, wie eine Cookie-Abfrage) ───────────────────
  var bannerShown = false;
  function pageHasEmbeds() {
    return !!document.querySelector('.ki-embed, blockquote.twitter-tweet, .ki-embed-tw, [data-embed-kind]');
  }
  function maybeShowBanner() {
    if (bannerShown || consentDecided()) return;
    if (!pageHasEmbeds()) return;
    bannerShown = true;
    var bar = document.createElement('div');
    bar.id = 'ki-consent-bar';
    bar.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:18px;z-index:9999;' +
      'width:calc(100% - 32px);max-width:560px;background:#0e1014;color:#cbd5e1;border:1px solid rgba(127,127,127,0.28);' +
      'border-radius:14px;padding:18px 20px;box-shadow:0 16px 50px rgba(0,0,0,0.55);font-family:\'Work Sans\',sans-serif;' +
      'animation:kiConsentIn .3s ease;';
    bar.innerHTML =
      '<div style="font-family:\'Space Grotesk\',sans-serif;font-weight:700;font-size:15px;color:#e7e9ea;margin-bottom:6px;">' +
        'Externe Inhalte anzeigen?</div>' +
      '<div style="font-size:12.5px;line-height:1.55;color:#9aa7b4;margin-bottom:14px;">' +
        'Diese Seite bindet Beiträge von X, YouTube und SoundCloud ein. Erlaubst du die automatische Anzeige, ' +
        'werden Vorschauen beim Scrollen geladen – dabei werden Daten an die jeweiligen Anbieter übertragen. ' +
        'Du kannst das jederzeit im <a href="/Datenschutz.html" style="color:#7cc4ff;text-decoration:underline;">Datenschutz</a> widerrufen.</div>' +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;">' +
        '<button id="ki-consent-yes" style="flex:1;min-width:150px;cursor:pointer;border:none;border-radius:9px;padding:11px 16px;' +
          'font-family:\'Space Grotesk\',sans-serif;font-weight:700;font-size:13px;background:#1d9bf0;color:#fff;">Vorschauen automatisch laden</button>' +
        '<button id="ki-consent-no" style="flex:1;min-width:120px;cursor:pointer;border:1px solid rgba(127,127,127,0.35);border-radius:9px;' +
          'padding:11px 16px;font-family:\'Space Grotesk\',sans-serif;font-weight:600;font-size:13px;background:transparent;color:#cbd5e1;">Nur auf Klick</button>' +
      '</div>';
    document.body.appendChild(bar);
    if (!document.getElementById('ki-consent-style')) {
      var st = document.createElement('style'); st.id = 'ki-consent-style';
      st.textContent = '@keyframes kiConsentIn{from{opacity:0;transform:translate(-50%,16px)}to{opacity:1;transform:translate(-50%,0)}}';
      document.head.appendChild(st);
    }
    function close() { var b = document.getElementById('ki-consent-bar'); if (b) b.remove(); }
    document.getElementById('ki-consent-yes').addEventListener('click', function () { allowAllPreviews(); close(); loadAllConsented(); });
    document.getElementById('ki-consent-no').addEventListener('click', function () { declinePreviews(); close(); });
  }

  // Öffentlich: Einwilligung widerrufen (z. B. Button auf der Datenschutz-Seite)
  KIEmbed.resetConsent = function () { try { localStorage.removeItem(CONSENT_KEY); } catch (e) {} location.reload(); };

  function init() {
    wrapTweets(document);
    autoLoadMedia(document);
    maybeShowBanner();
    if (window.MutationObserver) {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++)
          for (var j = 0; j < muts[i].addedNodes.length; j++) {
            var n = muts[i].addedNodes[j];
            if (n.nodeType === 1 && n.querySelectorAll) { wrapTweets(n); autoLoadMedia(n); maybeShowBanner(); }
          }
      }).observe(document.body, { childList: true, subtree: true });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
