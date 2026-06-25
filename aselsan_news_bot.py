import html
import json
import os
import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


TV_BASE_URL = "https://tr.tradingview.com"
TV_NEWS_URL = "https://tr.tradingview.com/news-flow/?symbol=BIST%3AASELS"
NEWS_API_URL = "https://news-mediator.tradingview.com/public/news-flow/v2/news"
NEWS_API_PARAMS = {
    "filter": "lang:tr",
    "client": "screener",
    "user_prostatus": "free",
}
SOURCE_VERSION = "aselsan-tradingview-v2"
SYMBOL = "BIST:ASELS"
SYMBOL_KEYWORDS = ("ASELS", "ASELSAN", "BIST:ASELS")

CACHE_FILE = os.environ.get("CACHE_FILE", "tv_news_cache.json")
NEWS_LIMIT = int(os.environ.get("NEWS_LIMIT", "60"))
CACHE_LIMIT = int(os.environ.get("CACHE_LIMIT", "200"))
PER_RUN_SEND_LIMIT = int(os.environ.get("PER_RUN_SEND_LIMIT", "20"))
TELEGRAM_SEND_DELAY = float(os.environ.get("TELEGRAM_SEND_DELAY", "4"))
MAX_TELEGRAM_ATTEMPTS = int(os.environ.get("MAX_TELEGRAM_ATTEMPTS", "5"))
ARTICLE_TEXT_LIMIT = int(os.environ.get("ARTICLE_TEXT_LIMIT", "2800"))
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}

token = os.environ.get("TELEGRAM_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")
message_thread_id = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID")

if not DRY_RUN and (not token or not chat_id):
    raise SystemExit("TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID eksik.")
if message_thread_id:
    try:
        message_thread_id = int(message_thread_id)
    except ValueError:
        raise SystemExit("TELEGRAM_MESSAGE_THREAD_ID sayisal olmalidir.")


def normalize_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalized_link(value):
    if not value:
        return ""
    parsed = urlparse(value)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def news_key(news):
    return normalized_link(news.get("link")) or normalize_space(news.get("title")).lower()


def unique_keys(keys):
    seen = set()
    result = []
    for key in keys:
        key = normalize_space(key)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
        if len(result) >= CACHE_LIMIT:
            break
    return result


def dedupe_news(news_items):
    seen = set()
    result = []
    for news in news_items:
        key = news_key(news)
        title_key = normalize_space(news.get("title")).lower()
        if not key or key in seen or title_key in seen:
            continue
        seen.add(key)
        if title_key:
            seen.add(title_key)
        result.append(news)
    return result


def load_state(path):
    state = {"source_version": "", "last_seen_key": "", "seen_keys": []}
    if not os.path.exists(path):
        return state
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"Cache okunamadi, guvenli baslangic yapilacak: {exc}")
        return state

    if isinstance(data, dict):
        source_version = data.get("source_version")
        if isinstance(source_version, str):
            state["source_version"] = source_version.strip()
        seen_keys = data.get("seen_keys", [])
        if isinstance(seen_keys, list):
            state["seen_keys"] = [
                item.strip()
                for item in seen_keys
                if isinstance(item, str) and item.strip()
            ]
        last_seen_key = data.get("last_seen_key")
        if isinstance(last_seen_key, str):
            state["last_seen_key"] = last_seen_key.strip()
        if not state["last_seen_key"] and state["seen_keys"]:
            state["last_seen_key"] = state["seen_keys"][0]
        return state

    if isinstance(data, list):
        loaded = []
        for item in data:
            if isinstance(item, str) and item.strip():
                loaded.append(item.strip())
            elif isinstance(item, dict):
                value = item.get("id") or item.get("link") or item.get("title")
                if isinstance(value, str) and value.strip():
                    loaded.append(value.strip())
        state["source_version"] = SOURCE_VERSION
        state["seen_keys"] = loaded
        if loaded:
            state["last_seen_key"] = loaded[0]

    return state


def save_state(last_seen_key, keys):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source_version": SOURCE_VERSION,
                "last_seen_key": last_seen_key,
                "seen_keys": unique_keys(keys),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def has_symbol_text(value):
    upper = normalize_space(value).upper()
    return any(keyword in upper for keyword in SYMBOL_KEYWORDS)


def item_has_symbol(item):
    if has_symbol_text(item.get("title")):
        return True
    related = item.get("relatedSymbols")
    if not isinstance(related, list):
        return False
    for symbol_info in related:
        if isinstance(symbol_info, dict) and normalize_space(symbol_info.get("symbol")).upper() == SYMBOL:
            return True
    return False


def fetch_api_news():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": TV_BASE_URL,
        "Referer": TV_NEWS_URL,
    }
    response = requests.get(NEWS_API_URL, params=NEWS_API_PARAMS, headers=headers, timeout=20)
    response.raise_for_status()
    items = response.json().get("items", [])
    if not isinstance(items, list):
        return []

    found = []
    for item in items:
        if not isinstance(item, dict) or not item_has_symbol(item):
            continue
        title = normalize_space(item.get("title"))
        story_path = normalize_space(item.get("storyPath") or item.get("story_path") or item.get("url"))
        if not title or not story_path:
            continue
        link = story_path if story_path.startswith("http") else urljoin(TV_BASE_URL, story_path)
        found.append({"title": title, "link": link, "published": item.get("published"), "source": "api"})
        if len(found) >= NEWS_LIMIT:
            break
    return found


blocked_article_text = [
    "ICE Data Services",
    "FactSet",
    "Telif Hakki",
    "Telif Hakkı",
    "CUSIP",
    "SEC dosyalari",
    "SEC dosyaları",
    "TradingView, Inc",
    "Tum haklari saklidir",
    "Tüm hakları saklıdır",
]


def trim_article_text(value):
    value = normalize_space(value).replace(". ", ".\n\n")
    if len(value) <= ARTICLE_TEXT_LIMIT:
        return value
    return value[:ARTICLE_TEXT_LIMIT].rsplit(" ", 1)[0].strip() + "..."


def extract_article_text(page):
    soup = BeautifulSoup(page.content(), "html.parser")
    paragraphs = soup.select(
        "article p, div[class*='body'] p, div[class*='article'] p, "
        "div[class*='content'] p"
    )
    if not paragraphs:
        paragraphs = soup.find_all("p")

    clean = []
    for p_tag in paragraphs:
        text = normalize_space(p_tag.get_text(" ", strip=True))
        if len(text) < 40:
            continue
        if any(blocked in text for blocked in blocked_article_text):
            continue
        clean.append(text)
    return trim_article_text("\n\n".join(clean))


def fetch_dom_news(page):
    print(f"TradingView ASELS haber akisi aciliyor: {TV_NEWS_URL}")
    try:
        page.goto(TV_NEWS_URL, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_selector('a[href*="/news/"]', timeout=20000)
        for _ in range(3):
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(1200)
    except Exception as exc:
        print(f"Sayfa tam yuklenmemis olabilir; eldeki DOM ile devam ediliyor: {exc}")

    return page.evaluate(
        """({baseUrl, forbiddenLinkParts, skipTextParts, symbolKeywords, limit}) => {
            const results = [];
            const seen = new Set();
            const keywords = symbolKeywords.map((k) => k.toUpperCase());
            const clean = (value) => (value || "").replace(/\\s+/g, " ").trim();
            const hasSymbol = (value) => {
                const upper = (value || "").toUpperCase();
                return keywords.some((keyword) => upper.includes(keyword));
            };
            const isBadLine = (line) => {
                const lower = line.toLocaleLowerCase("tr-TR");
                if (line.length < 12) return true;
                if (skipTextParts.some((part) => lower.includes(part))) return true;
                if (/^(\\d+\\s*(dk|sa|saat|gun|gün)|\\d{1,2}:\\d{2})/i.test(lower)) return true;
                if (["ASELS", "BIST:ASELS", "ASELSAN"].includes(line.toUpperCase())) return true;
                return false;
            };

            const anchors = Array.from(document.querySelectorAll('a[href*="/news/"]'));
            const pageHasSymbolFilter = new URL(window.location.href).searchParams.has("symbol");
            for (const anchor of anchors) {
                const href = anchor.getAttribute("href") || "";
                if (!href || forbiddenLinkParts.some((part) => href.includes(part))) continue;

                const link = href.startsWith("http") ? href : new URL(href, baseUrl).href;
                const card = anchor.closest(
                    'article, [data-testid*="news"], div[class*="story"], div[class*="Story"], div[class*="card"], div[class*="Card"], div[class*="item"], div[class*="Item"]'
                ) || anchor.parentElement;

                const rawTexts = [
                    anchor.innerText,
                    anchor.textContent,
                    card ? card.innerText : "",
                    card ? card.textContent : "",
                ].filter(Boolean);

                const cardText = rawTexts.map(clean).join(" ");
                if (!pageHasSymbolFilter && !hasSymbol(cardText) && !hasSymbol(link)) continue;

                const lines = [];
                for (const text of rawTexts) {
                    for (const line of text.split("\\n").map(clean)) {
                        if (!isBadLine(line)) lines.push(line);
                    }
                }

                const preferred = lines.filter(hasSymbol);
                const candidates = preferred.length ? preferred : lines;
                if (!candidates.length) continue;

                let title = candidates.sort((a, b) => b.length - a.length)[0];
                if (title.length > 220) title = title.slice(0, 217).trim() + "...";

                const dedupeKey = link.split(/[?#]/)[0];
                const titleKey = title.toLocaleLowerCase("tr-TR");
                if (seen.has(dedupeKey) || seen.has(titleKey)) continue;
                seen.add(dedupeKey);
                seen.add(titleKey);
                results.push({title, link, source: "dom"});
                if (results.length >= limit) break;
            }
            return results;
        }""",
        {
            "baseUrl": TV_BASE_URL,
            "forbiddenLinkParts": ["/markets/", "/crypto/", "/stocks/", "/all/", "/authors/", "/symbols/", "/ideas/"],
            "skipTextParts": ["giris yap", "giriş yap", "premium", "ozel haber", "özel haber"],
            "symbolKeywords": list(SYMBOL_KEYWORDS),
            "limit": NEWS_LIMIT,
        },
    )


def telegram_retry_after(response):
    try:
        payload = response.json()
    except Exception:
        return 15
    parameters = payload.get("parameters") if isinstance(payload, dict) else {}
    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
    try:
        return max(1, int(retry_after))
    except (TypeError, ValueError):
        return 15


def send_telegram(text):
    if DRY_RUN:
        print(f"DRY_RUN: Telegram'a gonderilmeyecek ({len(text)} karakter).")
        return True

    tg_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id

    for attempt in range(1, MAX_TELEGRAM_ATTEMPTS + 1):
        try:
            response = requests.post(tg_url, json=payload, timeout=20)
        except requests.RequestException as exc:
            wait_seconds = min(60, 5 * attempt)
            print(f"Telegram istegi basarisiz (deneme {attempt}): {exc}; {wait_seconds}s beklenecek.")
            time.sleep(wait_seconds)
            continue

        if response.status_code == 429:
            wait_seconds = telegram_retry_after(response) + 1
            print(f"Telegram hiz limiti verdi; {wait_seconds}s beklenip tekrar denenecek.")
            time.sleep(wait_seconds)
            continue

        if 500 <= response.status_code < 600:
            wait_seconds = min(60, 5 * attempt)
            print(f"Telegram gecici hata verdi: {response.status_code}; {wait_seconds}s beklenecek.")
            time.sleep(wait_seconds)
            continue

        if response.status_code >= 400:
            print(f"Telegram kalici hata verdi, mesaj sonraki tura birakildi: {response.status_code} {response.text[:300]}")
            return False

        return True

    print("Telegram mesaji tekrar denemelerden sonra gonderilemedi; sonraki tura birakildi.")
    return False


def select_news_to_process(found_news, state):
    current_keys = [news_key(news) for news in found_news]
    latest_key = current_keys[0]
    old_news = state["seen_keys"]
    old_news_set = set(old_news)
    last_seen_key = state["last_seen_key"]

    if state["source_version"] != SOURCE_VERSION:
        print("Cache veri kaynagi eski veya farkli; eski haberleri gondermemek icin sadece yeni referans alinacak.")
        return [], 0, latest_key, current_keys, old_news, "bootstrap"

    if not last_seen_key:
        print("Ilk calistirma: en ustteki haber referans alindi; eski haberler gonderilmeyecek.")
        return [], 0, latest_key, current_keys, old_news, "bootstrap"

    if last_seen_key in current_keys:
        cutoff_index = current_keys.index(last_seen_key)
        print(f"Son gorulen haber bulundu. Yeni haber sayisi: {cutoff_index}")
    else:
        seen_indexes = [
            index
            for index, key in enumerate(current_keys)
            if key in old_news_set
        ]
        if seen_indexes:
            cutoff_index = min(seen_indexes)
            print(f"Son gorulen haber listede yok, ama daha once gorulmus bir haber bulundu. Yeni haber sayisi: {cutoff_index}")
        else:
            print("Son gorulen haber akista bulunamadi; tekrar atmamak icin sadece yeni referans alinacak.")
            return [], 0, latest_key, current_keys, old_news, "bootstrap"

    candidates = [
        news
        for news in reversed(found_news[:cutoff_index])
        if news_key(news) not in old_news_set
    ]
    return candidates[:PER_RUN_SEND_LIMIT], len(candidates), latest_key, current_keys, old_news, "normal"


def build_message(news, article_text):
    safe_title = html.escape(news["title"])
    safe_link = html.escape(news["link"], quote=True)
    if article_text:
        text = html.escape(article_text)
        message = (
            f"<b>{safe_title}</b>\n\n"
            f"{text}\n\n"
            f"<a href=\"{safe_link}\">TradingView'de oku</a>"
        )
    else:
        message = f"<b>{safe_title}</b>\n\n<a href=\"{safe_link}\">TradingView'de oku</a>"

    if len(message) <= 3900:
        return message

    available = max(200, 3900 - len(safe_title) - len(safe_link) - 80)
    short_text = html.escape(article_text[:available].rsplit(" ", 1)[0].strip() + "...") if article_text else ""
    return (
        f"<b>{safe_title}</b>\n\n"
        f"{short_text}\n\n"
        f"<a href=\"{safe_link}\">TradingView'de oku</a>"
    )


def main():
    cache_state = load_state(CACHE_FILE)

    try:
        api_news = fetch_api_news()
    except Exception as exc:
        print(f"TradingView API ASELS filtresi okunamadi, DOM taramasina devam edilecek: {exc}")
        api_news = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
        )
        page = context.new_page()
        dom_news = fetch_dom_news(page)
        found_news_links = dedupe_news(api_news + dom_news)[:NEWS_LIMIT]

        print(f"ASELS filtresinden gecen TradingView haber sayisi: {len(found_news_links)}")
        for item in found_news_links[:10]:
            print(f"- {item['title']} [{item.get('source', 'unknown')}]")

        if not found_news_links:
            print("ASELS haberi bulunamadi; cache degistirilmeyecek.")
            browser.close()
            return

        (
            news_to_process,
            candidate_count,
            latest_key,
            current_keys,
            old_news,
            mode,
        ) = select_news_to_process(found_news_links, cache_state)

        sent_keys = []
        for news in news_to_process:
            print(f"Gonderiliyor: {news['title'][:80]}")
            article_text = ""
            try:
                page.goto(news["link"], timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                article_text = extract_article_text(page)
            except Exception as exc:
                print(f"Haber detayi okunamadi, baslik ve link gonderilecek: {exc}")

            if not send_telegram(build_message(news, article_text)):
                print("Gonderim durduruldu; kalan haberler sonraki calismada denenecek.")
                break
            sent_keys.append(news_key(news))
            time.sleep(TELEGRAM_SEND_DELAY)

        browser.close()

    if mode == "bootstrap":
        save_state(latest_key, current_keys + old_news)
        print("TradingView ASELS cache'i referans noktasina guncellendi.")
        return

    if not news_to_process:
        save_state(latest_key, current_keys + old_news)
        print("Yeni ASELS haberi yok; cache tazelendi.")
        return

    if sent_keys and len(sent_keys) == candidate_count:
        save_state(latest_key, current_keys + old_news)
        print("Tum yeni ASELS haberleri gonderildi; cache en yeni habere ilerletildi.")
        return

    if sent_keys:
        save_state(sent_keys[-1], list(reversed(sent_keys)) + old_news)
        print(f"{len(sent_keys)} ASELS haberi gonderildi; cache son basarili mesaja kadar ilerletildi.")
        return

    save_state(cache_state["last_seen_key"], old_news)
    print("Hic ASELS haberi gonderilemedi; cache ilerletilmedi.")


if __name__ == "__main__":
    main()
