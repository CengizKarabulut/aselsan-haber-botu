import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["DRY_RUN"] = "1"

import aselsan_news_bot as bot


class AselsanNewsBotTests(unittest.TestCase):
    def test_source_priority(self):
        self.assertEqual(
            bot.ENABLED_SOURCES,
            ["kap", "bloomberght", "investing", "ntvpara", "trthaber", "tradingview"],
        )

    def test_company_match_is_strict(self):
        self.assertTrue(bot.has_aselsan("ASELSAN yeni sözleşme imzaladı"))
        self.assertTrue(bot.has_aselsan("BIST:ASELS için hedef fiyat"))
        self.assertFalse(bot.has_aselsan("Savunma sanayii ihracatı arttı"))
        self.assertFalse(bot.has_aselsan("Parasal genişleme başladı"))

    def test_kap_filters_circuit_breaker_and_marks_contract_critical(self):
        rows = [
            {
                "disclosureIndex": 2,
                "subject": "Özel Durum Açıklaması (Genel)",
                "summary": "Yeni iş ilişkisi kapsamında sözleşme imzalandı",
                "publishDate": "15.08.2026 12:00:00",
                "attachmentCount": 1,
            },
            {
                "disclosureIndex": 1,
                "subject": "Pay Bazında Devre Kesici Bildirimi",
                "summary": "ASELS.E işlem sırasında devre kesici uygulandı",
            },
        ]
        items = bot.fetch_kap(_Session(post_response=_Response(data=rows)))
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["critical"])
        self.assertEqual(items[0]["id"], "2")

    def test_rss_keeps_only_aselsan_news(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item><title>ASELSAN yeni ihracat sözleşmesi imzaladı</title>
          <link>https://example.com/aselsan</link><guid>a1</guid>
          <description>ASELS için yeni anlaşma açıklandı.</description></item>
          <item><title>Piyasalarda gün ortası</title>
          <link>https://example.com/piyasa</link><guid>b1</guid>
          <description>Genel piyasa haberi.</description></item>
        </channel></rss>""".encode("utf-8")
        items = bot.fetch_rss_source("ntvpara", _Session(get_response=_Response(content=xml)))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "a1")

    def test_tradingview_link_is_primary_cache_identity(self):
        item = bot.blank_item(
            "tradingview", "ASELSAN haberi", "https://tr.tradingview.com/news/example:1:0",
            id="provider-internal-id",
        )
        self.assertEqual(
            bot.item_key(item),
            "tradingview:https://tr.tradingview.com/news/example:1:0",
        )

    def test_cross_source_duplicate(self):
        kap = bot.blank_item(
            "kap", "ASELS — Yeni iş ilişkisi", "https://kap/1",
            summary="ASELSAN 100 milyon dolarlık sözleşme imzaladı",
        )
        bloomberg = bot.blank_item(
            "bloomberght", "ASELSAN'dan 100 milyon dolarlık sözleşme", "https://bht/1",
            summary="Şirket yeni iş ilişkisini duyurdu",
        )
        history = []
        bot.remember_story(kap, history)
        self.assertTrue(bot.is_cross_source_duplicate(bloomberg, history))

    def test_first_run_bootstraps_without_old_messages(self):
        items = [
            bot.blank_item("kap", "ASELS — Yeni", "https://kap/2", id="2"),
            bot.blank_item("kap", "ASELS — Eski", "https://kap/1", id="1"),
        ]
        candidates, keys = bot.select_new(items, {"last_seen_key": "", "seen_keys": []})
        self.assertEqual(candidates, [])
        self.assertEqual(len(keys), 2)

    def test_legacy_cache_migrates_to_tradingview_source(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            cache.write_text(json.dumps({
                "source_version": "aselsan-tradingview-v2",
                "last_seen_key": "https://tv/new",
                "seen_keys": ["https://tv/new", "https://tv/old"],
            }), encoding="utf-8")
            previous = bot.CACHE_FILE
            try:
                bot.CACHE_FILE = str(cache)
                state = bot.load_state()
            finally:
                bot.CACHE_FILE = previous
        self.assertEqual(state["sources"]["tradingview"]["last_seen_key"], "tradingview:https://tv/new")
        self.assertEqual(len(state["sources"]["tradingview"]["seen_keys"]), 2)

    def test_activation_message_explains_sources(self):
        message = bot.build_activation_message()
        self.assertIn("ASELSAN çok kaynaklı haber botu aktif", message)
        self.assertIn("KAP → Bloomberg HT", message)
        self.assertLessEqual(len(message), 3900)

    def test_message_is_escaped_and_limited(self):
        item = bot.blank_item(
            "kap", "ASELS <kritik>", "https://kap/1?a=1&b=2",
            summary="A&B " + "uzun " * 1200, critical=True,
        )
        message = bot.build_message(item)
        self.assertIn("&lt;kritik&gt;", message)
        self.assertIn("🚨", message)
        self.assertLessEqual(len(message), 3900)


class _Response:
    def __init__(self, content=b"", data=None, text=""):
        self.content = content
        self.data = data
        self.text = text
        self.encoding = None

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class _Session:
    def __init__(self, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response

    def get(self, *args, **kwargs):
        return self.get_response

    def post(self, *args, **kwargs):
        return self.post_response


if __name__ == "__main__":
    unittest.main()
