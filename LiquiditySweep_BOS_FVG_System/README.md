# LiquiditySweep_BOS_FVG_System

Bu proje, **EURUSD (XM Global MT5)** verisi üzerinde çalışan profesyonel ve modüler bir araştırma/backtest altyapısıdır.

Sistem hem **bullish** hem **bearish** SMC kurulumlarını uygular:

1. Liquidity Sweep (wick ile süpürme + seviye reclaim/reject kapanışı)
2. BOS (yalnızca close kırılımı)
3. Displacement filtresi
4. FVG (ICT 3 mum)
5. FVG retest + yönlü reaksiyon
6. BUY/SELL işlem simülasyonu

## 1) Klasör Yapısı

Tüm kod/çıktılar tek proje dizinindedir:

- `LiquiditySweep_BOS_FVG_System/data`
- `LiquiditySweep_BOS_FVG_System/reports`
- `LiquiditySweep_BOS_FVG_System/charts`
- `LiquiditySweep_BOS_FVG_System/logs`
- `LiquiditySweep_BOS_FVG_System/core`
- `LiquiditySweep_BOS_FVG_System/strategies`
- `LiquiditySweep_BOS_FVG_System/results`
- `LiquiditySweep_BOS_FVG_System/config`

## 2) Kurulum

### Python sürümü

- Python **3.12+** önerilir.

### Bağımlılık kurulumu

```bash
pip install -r requirements.txt
```

### MT5 ortam değişkenleri (önerilen)

Windows PowerShell örneği:

```powershell
$env:MT5_LOGIN="12345678"
$env:MT5_PASSWORD="sifre"
$env:MT5_SERVER="XMGlobal-MT5 7"
$env:MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
```

> Not: `MT5_PATH` opsiyoneldir. Terminal zaten açıksa çoğu durumda otomatik bağlanır.

## 3) Çalıştırma

### Tam akış (indir + backtest + rapor + grafik)

```bash
python run_backtest.py
```

### Sadece veri indir

```bash
python run_backtest.py --download-only
```

### İndirme yapmadan mevcut CSV ile backtest

```bash
python run_backtest.py --skip-download
```

### HTF filtresiz parametre tarama (grid search)

RR, pivot sensitivity ve minimum FVG boyutu için optimize arama:

```bash
python run_grid_search.py
```

Ardından optimize konfig ile tekrar backtest:

```bash
python run_backtest.py --skip-download --strategy-config config/strategy_config_optimized_no_htf.json
```

## 4) Mimari Özeti

### `core/mt5_connector.py`

- MT5 bağlantı yönetimi
- EURUSD için OHLCV + spread indirme

### `core/data_manager.py`

- JSON konfigürasyon okuma
- Tarih aralığı çözümleme (M5 için kısa tarih fallback)
- CSV/Excel veri kaydetme

### `strategies/liquidity_sweep_bos_fvg.py`

- Pivot/fraktal swing tespiti
- Bullish/Bearish liquidity sweep tespiti
- Bullish/Bearish BOS + displacement doğrulaması
- Bullish/Bearish FVG üretimi ve mitigation takibi
- FVG retest + yönlü reaksiyon ile BUY/SELL giriş üretimi
- Seans filtresi (London/NY) + HTF filtresi (H1 structure veya EMA50)

### `core/trade_manager.py`

- İşlem aç/kapat
- Spread maliyeti simülasyonu
- TP/SL kontrolü
- PnL ve gerçekleşen RR hesapları

### `core/backtester.py`

- Mumları sıralı işleyerek look-ahead bias engelleme
- Çoklu açık pozisyon desteği
- Equity curve ve performans metrikleri

### `core/report_generator.py`

- CSV çıktıları
- Excel çoklu sayfa raporu
- HTML özet raporu

### `core/chart_renderer.py`

- Mum grafiği üzerinde swing/FVG/BOS/entry görselleştirme
- Equity curve PNG + interaktif HTML

## 5) Konfigürasyon

### `config/system_config.json`

- Enstrüman, zaman dilimleri, hesap parametreleri
- Spread/slippage/pozisyon limiti
- 6 ay geçmiş + M5 için minimum 1 ay fallback

### `config/strategy_config.json`

- `pivot_sensitivity`
- `min_sweep_distance_points`
- `min_fvg_size_points`
- displacement eşikleri
- entry confirmation modu
- session filter saatleri
- htf filter seçenekleri
- global RR ve SL/TP modları

## 6) Çıktılar

### Veri

- `data/EURUSD_M5.csv`
- `data/EURUSD_M15.csv`
- `data/EURUSD_H1.csv`
- `data/EURUSD_H4.csv`

### Sonuçlar

- `results/*_trades.csv`
- `results/*_swings.csv`
- `results/*_fvg.csv`
- `results/*_events.csv`
- `results/summary_*.csv`
- `results/equity_*.csv`

### Raporlar

- `reports/rapor_*.xlsx`
- `reports/ozet_*.html`

### Grafikler

- `charts/*_price_structure.png`
- `charts/*_equity_curve.png`
- `charts/*_equity_curve.html`

### Log

- `logs/system.log`

## 7) Geliştirme Fazları Karşılığı

- Faz 1: MT5 bağlantı + veri indirme
- Faz 2: Swing detector
- Faz 3: Liquidity sweep detector
- Faz 4: BOS detector
- Faz 5: Displacement filtresi
- Faz 6: FVG detector
- Faz 7: Entry engine
- Faz 8: Raporlama
- Faz 9: Görselleştirme

## 8) Gelecek Adım (Paper/Live)

Mevcut mimari, `core/` içine eklenecek bir `execution_gateway.py` ile paper/live katmanına genişletilebilir. Bu sayede aynı strateji sinyal motoru korunarak emir iletim altyapısı değiştirilebilir.
