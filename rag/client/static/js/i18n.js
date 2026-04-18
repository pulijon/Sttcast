/**
 * i18n.js — Minimal internationalisation engine for Sttcast RAG client
 *
 * Usage:
 *   window.t('key.path')                 → translated string
 *   window.t('key', { param: 'value' })  → translated string with interpolation
 *   window.i18n.setLocale('en')          → change UI language
 *   window.i18n.getCurrentLang()         → 'es' | 'en' | …
 *
 * HTML attributes:
 *   data-i18n="key"              → sets element textContent
 *   data-i18n-html="key"        → sets element innerHTML (use sparingly)
 *   data-i18n-placeholder="key" → sets placeholder attribute
 *   data-i18n-title="key"       → sets title attribute
 *   data-i18n-aria-label="key"  → sets aria-label attribute
 *
 * Adding a new language:
 *   1. Create  static/js/locales/<lang>.json  with all keys translated.
 *   2. Add '<lang>' to the SUPPORTED_LANGS array below.
 *   3. Add a flag button in index.html:
 *        <button class="lang-btn" data-lang="<lang>" title="…">🏴</button>
 */
(function () {
    'use strict';

    // ── Configuration ───────────────────────────────────────────────────────
    var STORAGE_KEY    = 'sttcast_ui_lang';
    var SUPPORTED_LANGS = ['es', 'en'];   // ← add new language codes here
    var DEFAULT_LANG   = 'es';

    // ── State ────────────────────────────────────────────────────────────────
    var currentLang  = DEFAULT_LANG;
    var translations = {};
    var globalParams = {};        // params available in every t() call (e.g. podcast_name)

    // ── Core translation function ────────────────────────────────────────────
    /**
     * Resolve a dotted key path in `translations` and interpolate {placeholders}.
     * Falls back to the last segment of the key if not found.
     */
    function t(key, params) {
        var keys  = key.split('.');
        var value = translations;
        for (var i = 0; i < keys.length; i++) {
            if (value == null || typeof value !== 'object') { value = undefined; break; }
            value = value[keys[i]];
        }
        if (typeof value !== 'string') {
            // Return the last segment of the key as a visible fallback
            return keys[keys.length - 1];
        }
        var merged = Object.assign({}, globalParams, params || {});
        return value.replace(/\{(\w+)\}/g, function (_, k) {
            return merged[k] !== undefined ? String(merged[k]) : '{' + k + '}';
        });
    }

    // ── DOM update ───────────────────────────────────────────────────────────
    function applyTranslations() {
        document.querySelectorAll('[data-i18n]').forEach(function (el) {
            el.textContent = t(el.getAttribute('data-i18n'));
        });
        document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
            el.innerHTML = t(el.getAttribute('data-i18n-html'));
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
            el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
        });
        document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
            el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
        });
        document.querySelectorAll('[data-i18n-aria-label]').forEach(function (el) {
            el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria-label')));
        });

        // Document title (via data-i18n-title on the <html> element)
        var titleKey = document.documentElement.getAttribute('data-i18n-title');
        if (titleKey) {
            document.title = t(titleKey);
        }

        // Sync <html lang="…">
        document.documentElement.lang = currentLang;

        // Update active state on flag buttons
        document.querySelectorAll('.lang-btn').forEach(function (btn) {
            var active = btn.dataset.lang === currentLang;
            btn.classList.toggle('lang-btn-active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    }

    // ── Locale loader ────────────────────────────────────────────────────────
    function getBasePath() {
        return window.location.pathname.startsWith('/sttcast') ? '/sttcast' : '';
    }

    async function loadLocale(lang) {
        try {
            var url  = getBasePath() + '/static/js/locales/' + lang + '.json';
            var resp = await fetch(url);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return await resp.json();
        } catch (e) {
            console.error('[i18n] Failed to load locale "' + lang + '":', e);
            return null;
        }
    }

    // ── Public API ───────────────────────────────────────────────────────────
    async function setLocale(lang) {
        if (!SUPPORTED_LANGS.includes(lang)) lang = DEFAULT_LANG;

        // Already active? Just re-apply (useful after dynamic DOM changes)
        if (lang === currentLang && Object.keys(translations).length > 0) {
            applyTranslations();
            return;
        }

        var data = await loadLocale(lang);
        if (!data) {
            console.warn('[i18n] Could not load locale "' + lang + '" — keeping current');
            return;
        }

        translations = data;
        currentLang  = lang;
        try { localStorage.setItem(STORAGE_KEY, lang); } catch (_) {}

        applyTranslations();

        // Notify the rest of the app so dynamic strings can be refreshed
        window.dispatchEvent(new CustomEvent('localeChanged', { detail: { lang: lang } }));
    }

    function getCurrentLang() { return currentLang; }

    // ── Language detection ───────────────────────────────────────────────────
    function detectBrowserLang() {
        var nav   = (navigator.language || navigator.userLanguage || '').split('-')[0].toLowerCase();
        return SUPPORTED_LANGS.includes(nav) ? nav : DEFAULT_LANG;
    }

    // ── Initialisation ───────────────────────────────────────────────────────
    async function init() {
        // Make podcast_name available as a global interpolation param
        globalParams.podcast_name = window.PODCAST_NAME || '';

        var saved;
        try { saved = localStorage.getItem(STORAGE_KEY); } catch (_) {}
        var lang = (saved && SUPPORTED_LANGS.includes(saved)) ? saved : detectBrowserLang();
        await setLocale(lang);
    }

    // ── Expose globals ───────────────────────────────────────────────────────
    window.t     = t;
    window.i18n  = { t: t, setLocale: setLocale, getCurrentLang: getCurrentLang };

    // ── Event delegation for flag buttons ────────────────────────────────────
    // Works even if buttons are added after this script runs
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.lang-btn');
        if (btn && btn.dataset.lang) {
            setLocale(btn.dataset.lang);
        }
    });

    // ── Boot ─────────────────────────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
