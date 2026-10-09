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
        self.assertEqual(message.count("PİYASA HABERİ | Bloomberg HT"), 1)
        self.assertIn("Kaynak: Bloomberg HT", message)
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


    def test_kap_message_contains_x_ready_share_with_source_time_and_link(self):
        item = base.blank_item(
            "kap",
            "ASELS — Yeni İş İlişkisi",
            "https://www.kap.org.tr/tr/Bildirim/999",
            provider="ASELSAN",
            published="2026-10-09T10:15:00+03:00",
            summary="Şirket yeni bir sözleşme imzaladığını açıkladı.",
            detail="Açıklama: Toplam 125 milyon USD tutarındaki sözleşme kapsamında teslimatlar 2027-2028 döneminde yapılacaktır.",
        )
        message = v2.build_message(item)
        self.assertIn("X İÇİN HAZIR PAYLAŞIM", message)
        self.assertIn("#ASELS", message)
        self.assertIn("Kaynak: KAP | 09.10.2026 10:15", message)
        self.assertIn("https://www.kap.org.tr/tr/Bildirim/999", message)

    def test_regular_news_message_contains_x_ready_share(self):
        item = base.blank_item(
            "investing",
            "ASELSAN ihracat görünümünü değerlendirdi",
            "https://tr.investing.com/news/example",
            provider="Investing.com Türkiye",
            published="2026-10-09T11:00:00+03:00",
            summary="Şirket ihracat siparişlerinin güçlü seyrini koruduğunu belirtti.",
            detail="Yönetim teslimat takviminin yılın son çeyreğinde yoğunlaşacağını ifade etti.",
        )
        message = v2.build_message(item)
        self.assertIn("X İÇİN HAZIR PAYLAŞIM", message)
        self.assertIn("Kaynak: Investing.com Türkiye | 09.10.2026 11:00", message)
        self.assertIn("https://tr.investing.com/news/example", message)
        self.assertLessEqual(len(message), 3900)


    def test_financial_asset_kap_is_turkish_and_correctly_classified(self):
        soup = BeautifulSoup(
            """
            <div class="disclosureScrollableArea">
              <span>oda_ExplanationTextBlock1</span>
              <span>Şirketimizin bağlı ortaklığı Cetwell'in sermayesi 100.000.000 TL'ye yükseltilmiş, 87.000.000 TL FORTE tarafından karşılanmıştır. FORTE'nin payı %93,63'e ulaşmıştır. İşbu açıklamamızın İngilizce çevirisi ekte yer almaktadır. | The share capital of Cetwell was increased and funded by FORTE.</span>
            </div>
            """,
            "html.parser",
        )
        detail = v2.compact_kap_detail(soup)
        self.assertIn("87.000.000 TL", detail)
        self.assertIn("%93,63", detail)
        self.assertNotIn("The share capital", detail)
        item = base.blank_item(
            "kap",
            "FORTE — Finansal Duran Varlık Edinimi",
            "https://www.kap.org.tr/tr/Bildirim/1678460",
            provider="FORTE",
            summary="Cetwell sermaye artırımına katılım",
            detail=detail,
        )
        icon, label = v2.classify_kap(item)
        self.assertEqual(label, "İŞTİRAK / FİNANSAL DURAN VARLIK")
        self.assertNotIn("SERMAYE İŞLEMİ", v2.build_message(item))


    def test_english_only_regular_news_is_not_rendered(self):
        item = base.blank_item(
            "tradingview",
            "ASELSAN signs new defense export contract",
            "https://tr.tradingview.com/news/example/",
            provider="Reuters",
            published="2026-10-09T12:00:00+03:00",
            summary="The company signed a new export contract for defense systems worth 125 million dollars.",
            detail="The order will be delivered over the next two years.",
        )
        self.assertTrue(v2.is_mostly_english(item["summary"]))
        self.assertEqual(v2.build_message(item), "")

    def test_turkish_regular_news_keeps_humanized_card(self):
        item = base.blank_item(
            "investing",
            "ASELSAN yeni ihracat sözleşmesini açıkladı",
            "https://tr.investing.com/news/example",
            provider="Investing.com Türkiye",
            published="2026-10-09T12:00:00+03:00",
            summary="Şirket 125 milyon dolarlık yeni ihracat sözleşmesi imzaladığını açıkladı.",
            detail="Teslimatların iki yıl içinde yapılması planlanıyor.",
        )
        message = v2.build_message(item)
        self.assertIn("ASELSAN yeni ihracat sözleşmesini açıkladı", message)
        self.assertIn("X İÇİN HAZIR PAYLAŞIM", message)
        self.assertNotIn("Related Companies", message)


if __name__ == "__main__":
    unittest.main()
