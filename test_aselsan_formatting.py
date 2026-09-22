import unittest

from bs4 import BeautifulSoup

import aselsan_news_bot as base
import aselsan_news_bot_v2 as v2


class AselsanFormattingTests(unittest.TestCase):
    def test_kap_detail_removes_form_tokens_and_english_duplicate(self):
        soup = BeautifulSoup(
            """
            <div class="disclosureScrollableArea">
              <span>[CONSOLIDATION METHOD TITLE]</span>
              <span>oda_DefaultTransactionTransactionType1</span>
              <span>Temerrüt İşleminin Tamamlanması (Completion of Default Transaction)</span>
              <span>oda_RelatedMarket1</span><span>PAY PİYASASI</span>
              <span>oda_SettlementDate1</span><span>2026-09-22</span>
              <span>oda_DateOfThePreviousNotificationAboutTheSameSubject1</span><span>22/09/2026</span>
              <span>oda_ExplanationTextBlock1</span>
              <span>ASELS.TE sırasındaki temerrüt işlemi 22/09/2026 tarihinde tamamlanmıştır.</span>
            </div>
            """,
            "html.parser",
        )
        detail = v2.compact_kap_detail(soup)
        self.assertIn("İşlem Türü: Temerrüt İşleminin Tamamlanması", detail)
        self.assertIn("İlgili Pazar: PAY PİYASASI", detail)
        self.assertIn("Takas Tarihi: 22.09.2026", detail)
        self.assertIn("Açıklama: ASELS.TE", detail)
        self.assertNotIn("oda_", detail)
        self.assertNotIn("Completion of Default Transaction", detail)
        self.assertNotIn("CONSOLIDATION", detail)

    def test_kap_message_is_grouped(self):
        item = base.blank_item(
            "kap",
            "ASELS — Temerrüt İşlemi",
            "https://www.kap.org.tr/tr/Bildirim/1",
            provider="ASELSAN",
            published="2026-09-22T15:50:57+03:00",
            summary="İşleme Açılan Temerrüt Sırası",
            detail=(
                "İşlem Türü: Temerrüt İşleminin Tamamlanması\n"
                "İlgili Pazar: PAY PİYASASI\n"
                "Takas Tarihi: 22.09.2026\n"
                "Açıklama: ASELS.TE sırasındaki temerrüt işlemi tamamlanmıştır."
            ),
        )
        message = v2.build_message(item)
        self.assertIn("RESMÎ | KAP | ASELS", message)
        self.assertIn("TEMERRÜT İŞLEMİ", message)
        self.assertIn("📌 <b>İşlem bilgileri</b>", message)
        self.assertIn("ℹ️ <b>Açıklama</b>", message)
        self.assertIn("KAP bildiriminin tamamını aç", message)
        self.assertNotIn("oda_", message)

    def test_regular_news_uses_clean_card_without_source_repeat(self):
        item = base.blank_item(
            "bloomberght",
            "ASELSAN yeni sözleşme açıkladı",
            "https://example.com/haber",
            provider="Bloomberg HT",
            published="2026-09-22T10:05:00+03:00",
            summary="ASELSAN yeni bir ihracat sözleşmesi açıkladı.",
            detail="ASELSAN yeni bir ihracat sözleşmesi açıkladı. Sözleşmenin teslimatları 2027 yılında yapılacak.",
        )
        message = v2.build_message(item)
        self.assertIn("PİYASA HABERİ | Bloomberg HT", message)
        self.assertIn("📝 <b>Özet</b>", message)
        self.assertIn("ℹ️ <b>Detay</b>", message)
        self.assertEqual(message.count("Bloomberg HT"), 1)
        self.assertIn("Haberi kaynağında aç", message)

    def test_tradingview_keeps_distinct_provider(self):
        item = base.blank_item(
            "tradingview",
            "ASELSAN sipariş aldı",
            "https://tr.tradingview.com/news/example",
            provider="Matriks",
            summary="ASELSAN yeni sipariş açıkladı.",
        )
        message = v2.build_message(item)
        self.assertIn("PİYASA AKIŞI | TradingView", message)
        self.assertIn("🏢 Matriks", message)

    def test_long_message_stays_within_telegram_limit_and_escapes_html(self):
        item = base.blank_item(
            "kap",
            "ASELS <kritik>",
            "https://kap/1?a=1&b=2",
            summary="A&B " + "uzun " * 1200,
            critical=True,
        )
        message = v2.build_message(item)
        self.assertIn("&lt;kritik&gt;", message)
        self.assertIn("🚨", message)
        self.assertLessEqual(len(message), 3900)

    def test_install_switches_runtime_to_new_formatter(self):
        v2.install()
        self.assertIs(base.build_message, v2.build_message)
        self.assertIs(base.enrich, v2.enrich)
        self.assertEqual(base.SOURCE_VERSION, v2.SOURCE_VERSION)


if __name__ == "__main__":
    unittest.main()
