# OrderBlock - AI Destekli Forex Araştırma ve Backtest Sistemi

Bu proje, **EURUSD** üzerinde **OrderBlock + Wick Rejection / Momentum Confirmation** yaklaşımıyla çalışan, tamamen bağımsız bir Python araştırma ve backtest altyapısıdır.

## Özellikler

- Sembol: **EURUSD**
- Timeframe: **M15, H1, H4**
- Çoklu zaman dilimi mantığı:
  - H4 trend bias
  - H1 yapı doğrulaması
  - M15 execution
- Sadece seans filtresi:
  - London
  - New York
- Sabit lot: **0.05** (`config.py` üzerinden ayarlanabilir)
- Backtest dönem uzunluğu: **geriye dönük 6 ay**
- MT5 + XMGlobal veri çekimi
- Opsiyonel AI sınıflandırma:
  - PyTorch CNN
  - CUDA varsa GPU, yoksa CPU fallback
- Optimizasyon:
  - Grid Search
  - Optuna

---

## Klasör Yapısı

```text
OrderBlock/
  data/
  dataset/
  ai_models/
  charts/
  logs/
  backtests/
  optimization/
  strategy/
  mt5/
  core/
  main.py
  train_ai.py
  config.py
  requirements.txt
  README.md
```

---

## Kurulum

### 1) Python ve bağımlılıklar

```bash
pip install -r OrderBlock/requirements.txt
```

### 2) MT5 / XMGlobal ayarları

Ortam değişkenleri (Windows PowerShell örneği):

```powershell
$env:MT5_LOGIN="12345678"
$env:MT5_PASSWORD="sifreniz"
$env:MT5_SERVER="XMGlobal-MT5 7"
$env:MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
```

Not:
- `MT5_PATH` opsiyoneldir, terminal zaten açıksa çoğu zaman otomatik initialize olur.
- Bu sistem yalnızca veri çeker, aktif çalışan diğer EA/stratejilere müdahale etmez.

---

## GPU / CUDA Kullanımı

- `train_ai.py` ve inference aşaması otomatik cihaz seçimi yapar:
  - CUDA mevcutsa: `cuda`
  - CUDA yoksa: `cpu`
- CUDA doğrulama için:

```python
import torch
print(torch.cuda.is_available())
```

---

## Çalıştırma

### 1) Backtest (varsayılan)

```bash
python OrderBlock/main.py --mode backtest
```

### 2) Cached veri ile backtest

```bash
python OrderBlock/main.py --mode backtest --use-cached-data
```

### 3) Dataset üretimi

```bash
python OrderBlock/main.py --mode dataset
```

### 4) AI model eğitimi

```bash
python OrderBlock/train_ai.py
```

### 5) Optimizasyon (Optuna)

```bash
python OrderBlock/main.py --mode optimize --optimizer optuna
```

### 6) Optimizasyon (Grid Search)

```bash
python OrderBlock/main.py --mode optimize --optimizer grid
```

---

## Strateji Mantığı (Özet)

### BUY
1. Bullish orderblock tespiti
2. Fiyatın OB bölgesine geri gelmesi
3. Onay:
   - wick rejection **veya**
   - güçlü bullish momentum mum
4. MTF filtre:
   - H4 bullish trend
   - H1 bullish structure
5. SL: wick/OB altı + buffer
6. TP: RR bazlı (örn 1:2, config ile değişebilir)

### SELL
1. Bearish orderblock tespiti
2. Fiyatın OB bölgesine geri gelmesi
3. Onay:
   - wick rejection **veya**
   - güçlü bearish momentum mum
4. MTF filtre:
   - H4 bearish trend
   - H1 bearish structure
5. SL: wick/OB üstü + buffer
6. TP: RR bazlı

---

## Çıktılar

- `OrderBlock/data/`: indirilen OHLCV verileri
- `OrderBlock/backtests/`:
  - `*_trades.csv`
  - `*_metrics.csv`
  - `*_equity.csv`
  - `summary.csv`
- `OrderBlock/charts/`:
  - equity png/html
  - price structure html
- `OrderBlock/optimization/`:
  - grid/optuna sonuçları
- `OrderBlock/logs/system.log`

---

## Sonuç Metrikleri

Backtest sonunda timeframe bazında ve toplamda:
- Net PnL (USD)
- Getiri (%)
- Win rate
- Profit factor
- Max drawdown
- Sharpe ratio
- BUY vs SELL dağılımı
- Ardışık kazanç/kayıp

---

## Sorun Giderme

1) `MT5 bağlantısı kurulamadı`
- Login/password/server bilgilerini kontrol edin
- MT5 terminalinin açık olduğundan emin olun
- Broker sunucu adını birebir doğrulayın

2) `Dataset boş`
- Önce `--mode dataset` çalıştırın
- Veri dosyalarının `OrderBlock/data` altında olduğunu kontrol edin

3) `CUDA görünmüyor`
- NVIDIA sürücüsü + CUDA toolkit + uyumlu torch sürümü kontrol edin
- CPU fallback otomatik devrededir

4) `Eksik mum oranı yüksek`
- Broker veri kesintisi olabilir
- Tarih aralığını daraltıp tekrar deneyin

---

## Uyarı

Bu yazılım araştırma/backtest amaçlıdır. Canlı işlemde kullanmadan önce forward test ve risk yönetimi doğrulaması zorunludur.
