# BIST Hisse Tarayici (FastAPI + HTML + Bootstrap + JavaScript)

Bu uygulama, TradingView Scanner servisine istek atip BIST hisselerini filtreleyerek web ekraninda listeler.

Uygulama su filtrelerle gelir:
- F/K < 8
- Temettu > %8
- Piyasa Degeri > 5.000.000.000 TL
- Sadece common stock

Sonuclarda her hissenin yaninda TradingView acma linki de vardir.

---

## 1) Bu proje kimler icin?

Bu rehber, yazilima yeni baslayanlar icin hazirlandi.
Eger daha once Python veya VS Code kurmadiysan, adim adim takip ederek calistirabilirsin.

---

## 2) Gerekenler

Windows uzerinde su iki seyin kurulu olmasi yeterli:

1. Python 3.11+ (onerilen: 3.12 veya 3.13)
2. Visual Studio Code

Istege bagli ama faydali:

1. VS Code Python eklentisi (Microsoft)

---

## 3) Python kurulumu (Windows)

1. Python resmi sitesine gir: https://www.python.org/downloads/
2. Windows icin Python indir ve kur.
3. Kurulum ekraninda Add Python to PATH secenegini isaretle.
4. Kurulum bitince PowerShell ac ve surum kontrol et:

	python --version

Surum goruyorsan tamam.

Eger python komutu calismazsa:
- py --version komutunu dene
- Gerekirse bilgisayari yeniden baslat

---

## 4) VS Code kurulumu

1. VS Code indir: https://code.visualstudio.com/
2. Kurulumu tamamla.
3. VS Code ac.
4. Extensions bolumunden Python eklentisini kur (yayinci: Microsoft).

---

## 5) Projeyi acma

1. VS Code icinde proje kok klasorunu ac: nyse
2. Terminal ac (Terminal > New Terminal)
3. Terminalde bist klasorune gec:

	cd bist

---

## 6) Sanal ortam olusturma (venv)

Bu adim, paketlerin sistem Python'una degil proje icine kurulmasini saglar.

1. Sanal ortam olustur:

	python -m venv .venv

2. Sanal ortami aktif et (PowerShell):

	.\.venv\Scripts\Activate.ps1

3. Prompt basinda (.venv) gorduysen aktif olmustur.

Eger script calistirma hatasi alirsan, gecici olarak su komutu calistir:

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

Sonra tekrar:

.\.venv\Scripts\Activate.ps1

---

## 7) Bagimliliklari kurma

Sanal ortam aktifken:

pip install -r requirements.txt

---

## 8) Uygulamayi calistirma

Sanal ortam aktifken:

python -m uvicorn main:app --reload

Basarili olursa terminalde su tipte bir satir gorursun:

Uvicorn running on http://127.0.0.1:8000

Tarayicida ac:

http://127.0.0.1:8000

---

## 9) Ekrani kullanma

1. Filtre alanlarini kontrol et.
2. Tara butonuna bas.
3. Sonuclar tabloda listelenir.
4. Her satirdaki TradingView linki ile sembolu TradingView uzerinde acabilirsin.

---

## 10) Sik karsilasilan sorunlar

### Sorun: python komutu bulunamadi

Neden:
- Python PATH'e eklenmemis olabilir.

Cozum:
- Python'u yeniden kurup Add Python to PATH secenegini isaretle.
- Ya da py komutunu dene:

  py -m venv .venv

### Sorun: Port zaten kullanimda

Neden:
- 8000 portunda baska bir uygulama calisiyor olabilir.

Cozum:
- Farkli portla calistir:

  python -m uvicorn main:app --reload --port 8010

- Sonra su adresten ac:

  http://127.0.0.1:8010

### Sorun: TradingView istegi hata veriyor

Neden:
- Gecici ag sorunu, engelleme veya API davranis degisikligi olabilir.

Cozum:
- Birkac dakika sonra tekrar dene.
- Internet/proxy ayarlarini kontrol et.

---

## 11) Uygulamayi durdurma

Terminale gecip su kisayolu kullan:

Ctrl + C

---

## 12) Gelistirme notu

Bu klasordeki ana dosyalar:
- main.py: FastAPI backend
- templates/index.html: Arayuz
- static/app.js: Tarayici tarafi JavaScript
- static/styles.css: Stil dosyasi
- requirements.txt: Python paketleri

Istersen bir sonraki adimda bu README'ye ekran goruntusu bolumu ve GIF adimi da ekleyebilirim.
