# OrderBlock Proje TODO

## Plan Özeti (Onaylandı)
- [x] Yeni proje tamamen bağımsız olacak ve sadece `OrderBlock/` altında geliştirilecek.
- [x] `LiquiditySweep_BOS_FVG_System` klasörüne müdahale edilmeyecek.
- [x] Backtest geriye dönük **6 ay** veri üzerinde çalışacak.
- [x] Sonuçlarda kazanç/kayıp hem **USD** hem **%** olarak raporlanacak.

## 1) Proje İskeleti ve Konfigürasyon
- [x] `OrderBlock/` klasör yapısını oluştur
- [x] `config.py` oluştur (sabit lot 0.05, EURUSD, M15/H1/H4, 6 ay, session, RR, AI ayarları)
- [x] `requirements.txt` oluştur

## 2) MT5 Veri Katmanı (Güvenli ve Bağımsız)
- [x] `mt5/connector.py` oluştur (read-only veri çekme, reconnect, eksik mum kontrolü)
- [x] XMGlobal bağlantı parametrelerini çevresel değişkenlerden okuma
- [x] Mevcut çalışan EA/stratejilere dokunmayan güvenli yaklaşım

## 3) Strateji Motoru (OrderBlock + Onay)
- [ ] `strategy/orderblock_strategy.py` oluştur
- [ ] Bullish/Bearish OrderBlock tespiti
- [ ] BOS/CHoCH doğrulaması
- [ ] Wick rejection veya momentum candle onayı
- [ ] MTF mantık (H4 bias, H1 structure, M15 execution)

## 4) Backtest Motoru ve Metrikler
- [ ] `core/backtester.py` oluştur
- [ ] M15, H1, H4 ayrı backtest
- [ ] İşlem logları (entry/exit, SL/TP, RR)
- [ ] Winrate, Profit Factor, Max Drawdown, Sharpe
- [ ] Equity curve
- [ ] Session istatistikleri
- [ ] Aylık istatistikler
- [ ] BUY vs SELL performansı
- [ ] Ardışık kazanç/kayıp
- [ ] Toplam PnL (USD) ve Getiri (%)

## 5) AI Dataset ve Model
- [ ] `ai/dataset_builder.py` oluştur (görsel + etiket + metadata)
- [ ] `ai/cnn_model.py` oluştur (PyTorch CNN)
- [ ] `ai/inference.py` oluştur
- [ ] `train_ai.py` oluştur (CUDA varsa GPU, yoksa CPU)

## 6) Görselleştirme
- [ ] `core/visualization.py` oluştur
- [ ] Orderblock, BOS, CHoCH, liquidity sweep, entry/SL/TP/RR çizimleri
- [ ] Equity curve (matplotlib + plotly)

## 7) Optimizasyon
- [ ] `optimization/grid_search.py` oluştur
- [ ] `optimization/optuna_search.py` oluştur
- [ ] Wick ratio, candle strength, RR, session, OB sensitivity, BOS, AI confidence optimizasyonu

## 8) Çalıştırma Girişleri ve Dokümantasyon
- [ ] `main.py` oluştur (modlar: backtest/train/optimize)
- [ ] `README.md` tamamen Türkçe yaz
- [ ] Kurulum, MT5/XMGlobal, GPU/CUDA, kullanım ve troubleshooting bölümlerini ekle

## 9) Doğrulama
- [ ] Kurulum testi: `pip install -r OrderBlock/requirements.txt`
- [ ] Backtest smoke testi: `python OrderBlock/main.py --mode backtest`
- [ ] AI eğitim testi: `python OrderBlock/train_ai.py`
- [ ] Optimizasyon testi: `python OrderBlock/main.py --mode optimize --optimizer optuna`
