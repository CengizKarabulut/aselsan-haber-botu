# ASELSAN Çok Kaynaklı Haber Botu

ASELSAN (`BIST:ASELS`) için resmî KAP bildirimlerini ve Türkçe ekonomi haberlerini Telegram'a gönderir.

## Kaynak önceliği

1. KAP — ASELSAN şirket kimliğiyle doğrudan resmî sorgu
2. Bloomberg HT
3. Investing.com Türkiye
4. NTV Para
5. TRT Haber Ekonomi
6. TradingView — `BIST:ASELS` sembol filtresi

KAP dışındaki kaynaklarda yalnızca `ASELS`, `ASELS.E`, `BIST:ASELS` veya `ASELSAN` ifadesi açıkça
bulunan içerikler kabul edilir. Genel savunma sanayii haberleri ASELSAN adı geçmiyorsa gönderilmez.

## Bildirim davranışı

- Yeni iş ilişkisi, sözleşme, sipariş, ihale, yatırım, finansal rapor, temettü ve sermaye
  açıklamaları kritik olarak işaretlenir.
- Pay bazında devre kesici bildirimleri varsayılan olarak susturulur.
- Aynı olay daha düşük öncelikli başka bir kaynakta yayımlanırsa tekrar gönderilmez.
- Mesajlarda kaynak, tarih, özet, sınırlı ayrıntı ve resmî bağlantı bulunur.
- İlk çalışmada eski içerikler gönderilmez; mevcut TradingView cache'i yeni yapıya taşınır.
- Yeni bot sürümü devreye girdiğinde Telegram'a yalnızca bir kez aktivasyon bildirimi gönderilir.

## GitHub Secrets

```text
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
TELEGRAM_MESSAGE_THREAD_ID
```

`TELEGRAM_MESSAGE_THREAD_ID` yalnızca Telegram forum konusu kullanılıyorsa gereklidir.

## İsteğe bağlı ortam değişkenleri

```text
NEWS_SOURCES=kap,bloomberght,investing,ntvpara,trthaber,tradingview
NEWS_LIMIT=100
PER_RUN_SEND_LIMIT=20
DETAIL_MAX_CHARS=2200
TELEGRAM_SEND_DELAY=4
INCLUDE_CIRCUIT_BREAKER=false
KAP_MEMBER_OID=4028e4a1413b7ef401413bc2251e0047
```

## Yerel test

```bash
pip install -r requirements.txt
python -m unittest -v test_aselsan_news_bot.py
DRY_RUN=1 python aselsan_news_bot.py
```
