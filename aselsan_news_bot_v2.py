"""ASELSAN haber botu için temiz Telegram kart görünümü.

Mevcut veri toplama, tekrar filtresi ve cache mantığını korur; yalnız KAP detayını
ve Telegram mesaj biçimini okunabilir hale getirir.
"""

import html
import re

import requests
from bs4 import BeautifulSoup

import aselsan_news_bot as base


SOURCE_VERSION = "aselsan-multi-source-v2"
ORIGINAL_ENRICH = base.enrich

SOURCE_STYLE = {
    "bloomberght": ("📰", "PİYASA HABERİ", "Bloomberg HT"),
    "investing": ("📰", "PİYASA HABERİ", "Investing.com Türkiye"),
    "ntvpara": ("📰", "PİYASA HABERİ", "NTV Para"),
    "trthaber": ("📰", "EKONOMİ", "TRT Haber Ekonomi"),
    "tradingview": ("⚡", "PİYASA AKIŞI", "TradingView"),
}

KAP_SYSTEM_TOKEN = re.compile(
    r"(?:\[[A-Z0-9_ ]+\])|(?:\boda_[A-Za-z0-9_().\[\]-]+\b)",
    re.IGNORECASE,
)
KAP_SKIP_EXACT = {
    "ilgili şirketler", "related companies", "ilgili fonlar", "related funds",
    "türkçe", "turkish", "ingilizce", "english",
    "bildirim içeriği", "announcement content", "explanations",
}
KAP_BOILERPLATE_STARTS = (
    "yukarıdaki açıklamalarımızın",
    "we proclaim that our above disclosure",
    "burada yer alan yatırım bilgi",
    "işbu açıklamanın ingilizce tercümesi",
)
KAP_ODA_FIELDS = (
    ("oda_DefaultTransactionTransactionType", "İşlem Türü"),
    ("oda_RelatedMarket", "İlgili Pazar"),
    ("oda_SettlementDate", "Takas Tarihi"),
    ("oda_DateOfThePreviousNotificationAboutTheSameSubject", "Önceki Açıklama"),
)
KAP_KIND_RULES = (
    ("⚠️", "TEMERRÜT İŞLEMİ", ("temerrüt", "temerrut", "default transaction")),
    ("🤝", "YENİ İŞ / SÖZLEŞME", ("yeni iş ilişkisi", "sözleşme", "sozlesme", "sipariş", "siparis", "ihale")),
    ("📊", "FİNANSAL RAPOR", ("finansal rapor", "finansal tablo", "faaliyet raporu", "bilanço", "bilanco")),
    ("💸", "KÂR PAYI / TEMETTÜ", ("kar payı", "kâr payı", "temettü", "temettu")),
    ("💰", "SERMAYE İŞLEMİ", ("sermaye artır", "sermaye artir", "bedelli", "bedelsiz", "kayıtlı sermaye", "kayitli sermaye")),
    ("👤", "PAY İŞLEMİ", ("pay alım", "pay alim", "pay satım", "pay satim", "geri alım", "geri alim")),
    ("🏢", "KURUMSAL / YÖNETİM", ("yönetim kurulu", "yonetim kurulu", "kurumsal yönetim", "kurumsal yonetim")),
)


def clean(value):
    return base.clean(value)


def _excerpt(value, max_chars):
    value = clean(value)
    if len(value) <= max_chars:
        return value
    window = value[: max_chars + 1]
    sentence_cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_cut >= int(max_chars * 0.55):
        return window[: sentence_cut + 1].rstrip()
    word_cut = window.rfind(" ")
    if word_cut < int(max_chars * 0.55):
        word_cut = max_chars
    return window[:word_cut].rstrip(" ,;:-") + "…"


def _plain_compare(value):
    return re.sub(r"\s+", " ", clean(value)).strip().casefold().replace("i̇", "i")


def _strip_title_prefix(value, title):
    value, title = clean(value), clean(title)
    if not value or not title:
        return value
    value_cmp, title_cmp = value.casefold(), title.casefold()
    if value_cmp == title_cmp:
        return ""
    if value_cmp.startswith(title_cmp):
        remainder = value[len(title):].lstrip(" \t\r\n-—:|·")
        if len(remainder) >= 20:
            return remainder
    return value


def _prepare_news_texts(item):
    title = clean(item.get("title"))
    summary = _strip_title_prefix(item.get("summary"), title)
    detail = _strip_title_prefix(item.get("detail"), title)
    if summary and detail:
        summary_cmp, detail_cmp = _plain_compare(summary), _plain_compare(detail)
        if summary_cmp == detail_cmp:
            detail = ""
        elif detail_cmp.startswith(summary_cmp):
            detail = clean(detail[len(summary):]).lstrip(" .·-—:|")
        elif summary_cmp.startswith(detail_cmp):
            detail = ""
    return _excerpt(summary, 520), _excerpt(detail, 760)


def _provider_is_redundant(provider, label):
    provider_cmp, label_cmp = _plain_compare(provider), _plain_compare(label)
    if not provider_cmp or not label_cmp:
        return True
    return provider_cmp == label_cmp or provider_cmp in label_cmp or label_cmp in provider_cmp


def _strip_english_parenthetical(value):
    value = clean(value)
    match = re.search(r"\s+\(([^()]*)\)\s*$", value)
    if not match:
        return value
    inner = match.group(1).strip()
    if inner and re.fullmatch(r"[A-Za-z0-9 /&.,'’:+-]+", inner):
        return value[:match.start()].strip()
    return value


def _format_kap_date(value):
    value = clean(value)
    iso = re.fullmatch(r"(20\d{2})-(\d{2})-(\d{2})", value)
    if iso:
        return f"{iso.group(3)}.{iso.group(2)}.{iso.group(1)}"
    slash = re.fullmatch(r"(\d{2})/(\d{2})/(20\d{2})", value)
    if slash:
        return f"{slash.group(1)}.{slash.group(2)}.{slash.group(3)}"
    return value


def _extract_oda_value(flat_text, key):
    pattern = re.compile(
        rf"\b{re.escape(key)}(?:\[\d+\]|\d+)?\s+(.+?)(?=\s+oda_[A-Za-z0-9_().\[\]-]+\b|$)",
        re.IGNORECASE,
    )
    match = pattern.search(flat_text)
    return _strip_english_parenthetical(match.group(1)) if match else ""


def _normalize_kap_line(line):
    line = KAP_SYSTEM_TOKEN.sub(" ", clean(line))
    line = re.sub(r"\s+", " ", line).strip(" ·-|:")
    line = re.sub(r"\bHayır\s*\(No\)(?:\s*Hayır\s*\(No\))?\b", "Hayır", line, flags=re.IGNORECASE)
    line = re.sub(r"\bEvet\s*\(Yes\)(?:\s*Evet\s*\(Yes\))?\b", "Evet", line, flags=re.IGNORECASE)
    return _strip_english_parenthetical(line)


def _clean_explanation(value):
    value = clean(value)
    if not value:
        return ""
    lowered = value.lower()
    cut_points = [lowered.find(prefix) for prefix in KAP_BOILERPLATE_STARTS if lowered.find(prefix) >= 0]
    if cut_points:
        value = value[:min(cut_points)].strip(" .·")
    return value


def compact_kap_detail(soup):
    content = soup.select_one(".disclosureScrollableArea")
    if not content:
        return ""
    for node in content.select("script, style, input, button, svg, noscript"):
        node.decompose()

    flat_text = clean(content.get_text(" ", strip=True))
    fields = []
    for key, label in KAP_ODA_FIELDS:
        value = _extract_oda_value(flat_text, key)
        if not value:
            continue
        if label in {"Takas Tarihi", "Önceki Açıklama"}:
            value = _format_kap_date(value)
        fields.append(f"{label}: {value}")

    explanation = _clean_explanation(_extract_oda_value(flat_text, "oda_ExplanationTextBlock"))
    if explanation:
        fields.append(f"Açıklama: {explanation}")
    if fields:
        return "\n".join(fields)[:1600]

    raw_lines = content.get_text("\n", strip=True).splitlines()
    lines, seen = [], set()
    for raw in raw_lines:
        line = _normalize_kap_line(raw)
        if not line:
            continue
        lowered = line.lower()
        if lowered in KAP_SKIP_EXACT or any(lowered.startswith(prefix) for prefix in KAP_BOILERPLATE_STARTS):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        lines.append(line)
    if not lines:
        return ""

    explanation_index = next(
        (index for index, line in enumerate(lines) if line.lower().startswith("açıklamalar")),
        None,
    )
    useful = lines[explanation_index + 1:] if explanation_index is not None else lines
    sentence_like = [
        line for line in useful
        if len(line) >= 24 and not re.fullmatch(r"[A-Z0-9_(). -]{8,}", line)
    ]
    useful = sentence_like[-8:] if sentence_like else useful[-8:]
    return _excerpt(" ".join(useful), 1200)


def enrich(item, session=requests):
    if item.get("source") != "kap":
        return ORIGINAL_ENRICH(item, session)
    response = session.get(item["link"], headers=base.headers(), timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    detail = compact_kap_detail(soup)
    if detail:
        item["detail"] = detail
    return item


def _split_kap_detail(detail):
    fields, explanation = [], ""
    for raw in str(detail or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            if not explanation:
                explanation = clean(line)
            continue
        label, value = line.split(":", 1)
        label, value = clean(label), clean(value)
        if not value:
            continue
        if label.lower() == "açıklama":
            explanation = value
        else:
            fields.append((label, value))
    return fields, explanation


def classify_kap(item):
    text = clean(f"{item.get('title', '')} {item.get('summary', '')} {item.get('detail', '')}").lower()
    for icon, label, keywords in KAP_KIND_RULES:
        if any(keyword in text for keyword in keywords):
            return icon, label
    return "📣", "KAP BİLDİRİMİ"


def _fit_message(parts, limit=3900):
    message = "\n".join(parts)
    if len(message) <= limit:
        return message
    link = parts[-1] if parts else ""
    kept, reserve = [], len(link) + 2
    for line in parts[:-1]:
        candidate = "\n".join(kept + [line])
        if len(candidate) + reserve <= limit:
            kept.append(line)
    while kept and not kept[-1]:
        kept.pop()
    return "\n".join(kept + ["", link])


def _build_kap_message(item):
    title = clean(item.get("title")) or "ASELS — KAP Bildirimi"
    ticker, subject = "ASELS", title
    if " — " in title:
        ticker, subject = [part.strip() for part in title.split(" — ", 1)]
    published = base.format_date(item.get("published"))
    summary = clean(item.get("summary"))
    fields, explanation = _split_kap_detail(item.get("detail"))
    kind_icon, kind_label = classify_kap(item)

    parts = [
        f"🏛 <b>RESMÎ | KAP | {html.escape(ticker)}</b>",
        f"{kind_icon} <b>{html.escape(kind_label)}</b>",
        f"<b>{html.escape(subject)}</b>",
    ]
    if item.get("critical"):
        parts.append("🚨 <b>Önemli bildirim</b>")
    if published:
        parts.extend(["", f"🕒 {html.escape(published)}"])
    if summary and _plain_compare(summary) not in {_plain_compare(subject), _plain_compare(title)}:
        parts.extend(["", "📝 <b>Özet</b>", html.escape(_excerpt(summary, 520))])
    if fields:
        parts.extend(["", "📌 <b>İşlem bilgileri</b>"])
        for label, value in fields[:6]:
            parts.append(f"• <b>{html.escape(label)}:</b> {html.escape(_excerpt(value, 260))}")
    if explanation:
        parts.extend(["", "ℹ️ <b>Açıklama</b>", html.escape(_excerpt(explanation, 900))])
    elif item.get("detail") and not fields:
        detail = clean(item.get("detail"))
        if detail and _plain_compare(detail) != _plain_compare(summary):
            parts.extend(["", "ℹ️ <b>Detay</b>", html.escape(_excerpt(detail, 900))])
    if item.get("attachment_count"):
        parts.extend(["", f"📎 {int(item['attachment_count'])} ek"])
    parts.extend([
        "",
        f'<a href="{html.escape(item["link"], quote=True)}">KAP bildiriminin tamamını aç</a>',
    ])
    return _fit_message(parts)


def _build_news_message(item):
    source = item.get("source", "")
    icon, layer, label = SOURCE_STYLE.get(
        source,
        ("📰", "HABER", base.SOURCE_LABELS.get(source, source or "Haber")),
    )
    title = clean(item.get("title")) or "ASELSAN Haberi"
    provider = clean(item.get("provider"))
    published = base.format_date(item.get("published"))
    summary, detail = _prepare_news_texts(item)

    parts = [
        f"{icon} <b>{html.escape(layer)} | {html.escape(label)}</b>",
        f"<b>{html.escape(title)}</b>",
    ]
    if published:
        parts.append(f"🕒 {html.escape(published)}")
    if provider and not _provider_is_redundant(provider, label):
        parts.append(f"🏢 {html.escape(provider)}")
    if summary:
        parts.extend(["", "📝 <b>Özet</b>", html.escape(summary)])
    if detail:
        parts.extend(["", "ℹ️ <b>Detay</b>", html.escape(detail)])
    parts.extend([
        "",
        f'<a href="{html.escape(item["link"], quote=True)}">Haberi kaynağında aç</a>',
    ])
    return _fit_message(parts)


def build_message(item):
    return _build_kap_message(item) if item.get("source") == "kap" else _build_news_message(item)


def build_activation_message():
    return (
        "<b>✅ ASELSAN çok kaynaklı haber botu aktif</b>\n\n"
        "Kaynak önceliği: KAP → Bloomberg HT → Investing → NTV Para → TRT Haber → TradingView\n\n"
        "Bildirimler artık ortak, sade ve okunabilir Telegram kart düzeninde gönderilecek."
    )


def install():
    base.SOURCE_VERSION = SOURCE_VERSION
    base.enrich = enrich
    base.build_message = build_message
    base.build_activation_message = build_activation_message


def main():
    install()
    base.main()


if __name__ == "__main__":
    main()
