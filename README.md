# 🎛️ Tuğrul Deck

**Tuğrul Deck**, herhangi bir akıllı telefonu yerel ağ (Wi-Fi) üzerinden Windows bilgisayarlar için gerçek zamanlı, çift yönlü bir **Stream Deck ve sistem kontrol merkezine** dönüştüren açık kaynaklı bir Progressive Web App (PWA) ve Python WebSocket sunucusudur.

---

## ✨ Öne Çıkan Özellikler

* **🎛️ Çift Arayüz Modu (Genel & Yayın Modu):**
  * **Genel Mod:** Sistem sesi, ekran parlaklığı, medya oynatıcı senkronizasyonu ve özelleştirilebilir 9'lu makro ızgarası.
  * **Yayın Modu (Stream Mode):** Yüksek kontrastlı tema ile üstte anlık OBS sahne/yayın kontrollerini, altta ise canlı Kick sohbet akışını tek ekranda birleştirir.
* **🔊 Gerçek Zamanlı Ses, Parlaklık & Medya Kontrolü:** `pycaw` ve donanım medya tuşları aracılığıyla Windows ana ses seviyesini, sessize almayı, ekran parlaklığını ve YouTube Music / tarayıcı oynatıcısını gecikmesiz yönetir.
* **🎥 OBS Studio WebSocket Entegrasyonu (`obsws-python`):** Tek dokunuşla sahne geçişi yapar, canlı yayın ve kayıt durumunu anlık olarak telefon ekranına yansıtır.
* **💬 Canlı Kick Sohbet Akışı:** Kick kanalının sohbet odasına bağlanarak yayıncı, moderatör ve abone rozetleriyle birlikte mesajları gerçek zamanlı gösterir.
* **👁️ Live Peek & Canlı Sistem Monitörü:** Bilgisayar ekranının düşük gecikmeli önizlemesini telefondan izleme ve anlık **CPU / RAM** kullanımını takip etme imkânı sunar.
* **⏱️ Güç & Zamanlayıcı Yönetimi:** Bilgisayarı 30/60/120 dakika sonra otomatik kapatma sayacı kurar, iptal eder veya anında uyku moduna alır.
* **👻 Sessiz Arka Plan Servisi:** `pythonw.exe` ve otomatik log yönlendirmesi (`deck.log`) sayesinde görev çubuğunda konsol penceresi bırakmadan arka planda çalışır.

---

## 🛠️ Teknoloji Yığını

| Katman | Kullanılan Teknolojiler |
| :--- | :--- |
| **Backend** | Python 3.10+, `websockets`, `pycaw`, `obsws-python`, `psutil`, `pyautogui`, `Pillow`, `screen-brightness-control` |
| **Frontend (PWA)** | HTML5, CSS3 (Glassmorphism & Responsive Grid `100dvh`), Vanilla JavaScript, Service Worker |
| **İletişim** | Çift yönlü WebSocket (`ws://<PC-IP>:8765`) & No-Cache HTTP Sunucusu (`:8000`) |

---

## 📁 Proje Yapısı

```text
tugrul-deck/
├── deck_server.py       # Ana WebSocket ve HTTP arka plan sunucusu
├── media_helper.py      # Windows medya oturumu okuyucu yardımcı betik
├── index.html           # PWA kullanıcı arayüzü (Genel & Yayın Modu)
├── manifest.json        # Ana ekrana ekleme (PWA) yapılandırması
├── sw.js                # Service Worker önbellek yönetimi
├── deck_baslat.bat      # Arka planda penceresiz (pythonw) başlatıcı
├── deck_durdur.bat      # Arka plan servisini sonlandırıcı
├── requirements.txt     # Gerekli Python kütüphaneleri
└── README.md            # Proje dokümantasyonu
```
## 🚀 Kurulum ve Kullanım
```text
1. Depoyu Klonlayın
Bash
git clone [https://github.com/Tugruleyolll/tugrul-deck.git](https://github.com/Tugruleyolll/tugrul-deck.git)
cd tugrul-deck
2. Gerekli Kütüphaneleri Kurun
Bash
pip install -r requirements.txt
3. Yapılandırma
deck_server.py dosyasındaki KICK_CHANNEL değişkenini kendi Kick kullanıcı adınızla güncelleyin.

OBS kontrolü için OBS Studio içinden Araçlar 
→
→ WebSocket Sunucu Ayarları bölümünden WebSocket sunucusunu (4455 portu, şifresiz yerel bağlantı) etkinleştirin.

Windows Güvenlik Duvarı'nda 8000 ve 8765 TCP portlarına yerel ağ izni verin.

4. Sunucuyu Başlatın ve Telefondan Bağlanın
Arka planda sessiz çalıştırmak için deck_baslat.bat dosyasına çift tıklayın (konsol çıktılarıyla görmek için python deck_server.py çalıştırabilirsiniz).

Bilgisayarınızla aynı Wi-Fi ağına bağlı telefonunuzun tarayıcısından şu adrese gidin:

Plaintext
http://<BILGISAYAR_YEREL_IP_ADRESI>:8000
Tarayıcı menüsünden "Ana ekrana ekle" seçeneğini kullanarak tam ekran uygulama deneyimi elde edebilirsiniz.
```