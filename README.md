# Better-Tesla 🚗⚡

**Better-Tesla**, Tesla araçların CAN Bus (Kontrol Alan Ağı) trafiğini dinlemek, analiz etmek ve araca özel komutlar (geri viteste otomatik dörtlü yakma vb.) göndermek için geliştirilmiş açık kaynaklı bir donanım/yazılım projesidir.

Yapay zeka asistanları (Claude, Cursor, vb.) ile tam entegre çalışacak şekilde bir **MCP (Model Context Protocol)** sunucusu da barındırır. Bu sayede yapay zeka asistanınız, aracınızın CAN ağını canlı olarak izleyebilir ve size tersine mühendislik yaparken yardımcı olabilir.

---

## 🛠️ Donanım Gereksinimleri

* **NodeMCU ESP8266 (v2)**
* **MCP2515 CAN Controller Modülü** (ÖNEMLİ: Mutlaka **8MHz** kristalli model kullanılmalıdır)
  * *(Opsiyonel)* Aynı anda ikinci bir CAN hattını dinlemek isterseniz, ikinci bir MCP2515 modülü ekleyebilirsiniz.
* **Bağlantı Şeması (SPI):**
  * `CS` ➔ `D8 (GPIO15)` *(Ana MCP)*
  * `CS` ➔ `D3 (GPIO0)` *(İkinci MCP - Opsiyonel)*
  * `INT` ➔ `D2 (GPIO4)` *(İkinci MCP'de kullanılmıyor)*
  * `SCK` ➔ `D5 (GPIO14)` *(İki modül için paylaşımlı)*
  * `MOSI` ➔ `D7 (GPIO13)` *(İki modül için paylaşımlı)*
  * `MISO` ➔ `D6 (GPIO12)` *(İki modül için paylaşımlı)*
* Tesla CAN Bus adaptör kablosu (Aracınızın modeline ve üretim yılına göre OBD2 veya özel soket)

---

## 📂 Proje Yapısı

Proje 4 ana bileşenden oluşur:

1. **`firmware/` (C++):** ESP8266 içerisine yüklenen yazılım. CAN Bus'taki verileri okur ve seri port üzerinden bilgisayara JSON formatında aktarır. Ayrıca geri vitese takıldığında dörtlüleri açmak gibi aktif enjeksiyon görevlerini yürütür.
2. **`bridge/` (Python):** ESP8266'dan gelen seri port verilerini anlık olarak okuyup `can.db` adlı yerel SQLite veritabanına kaydeden köprü yazılımı. 
3. **`mcp_server/` (Python):** Yapay zeka asistanlarının (Cursor, Claude) aracın canlı CAN verilerine ulaşmasını, DBC veritabanında arama yapmasını ve sinyalleri anlamlandırmasını sağlayan MCP sunucusu.
4. **`data/hacks/` (Markdown):** Tesla'nın güvenlik sistemlerini aşmak ve araç fonksiyonlarını (dörtlüleri yakmak gibi) tetiklemek için kullandığımız yöntemlerin ve keşiflerin ("Tersine Mühendislik") dökümante edildiği bölüm.

---

## 🚀 Kurulum ve Kullanım

### 1. Firmware Yüklemesi (ESP8266)
Yazılımı derlemek ve yüklemek için [PlatformIO](https://platformio.org/) kullanıyoruz.
1. `firmware/` klasörünü VS Code veya PlatformIO IDE ile açın.
2. *(Opsiyonel)* İkinci bir MCP2515 bağladıysanız, `firmware/include/config.h` dosyasındaki `ENABLE_SECOND_MCP2515` ayarını `true` yapın.
3. ESP8266'nızı USB ile bilgisayara bağlayın.
4. PlatformIO üzerinden `Upload` diyerek kodu yükleyin.

### 2. Python Bridge Çalıştırma
Verileri kaydetmek ve ESP8266'ya komut göndermek için köprü scriptini çalıştırmalısınız.
```bash
# Python bağımlılıklarını yükleyin (sanal ortam önerilir)
python -m venv .venv
source .venv/bin/activate
pip install pyserial

# Bridge'i başlatın (Seri portu otomatik bulur)
python bridge/bridge.py
```
*Not: Veriler `can.db` adlı SQLite veritabanında toplanacaktır.*

### 3. MCP Sunucusunu Kullanma
Bu projeyi destekleyen bir yapay zeka asistanı kullanıyorsanız (örn. Cursor), MCP sunucusunu konfigürasyonunuza ekleyebilirsiniz. Böylece yapay zekaya *"Şu an hangi CAN ID'leri değişiyor?"* veya *"Dörtlülerin CAN ID'si nedir?"* gibi sorular sorabilirsiniz.

```json
{
  "mcpServers": {
    "better-tesla": {
      "command": "python",
      "args": ["/projenizin/tam/yolu/mcp_server/server.py"]
    }
  }
}
```

---

## 🎯 Projenin Amacı

Better-Tesla projesi, modern otomobillerdeki (özellikle Tesla) kapalı araç ağlarının (CAN Bus) şifrelerini çözmeyi, sinyalleri anlamlandırmayı ve açık kaynaklı donanımlar aracılığıyla araçla etkileşime geçmeyi amaçlar. Temel hedeflerimiz şunlardır:

* **Tersine Mühendislik ve Analiz:** Araç donanımlarının nasıl haberleştiğini keşfetmek ve bu bilgileri dökümante etmek (DBC dosyaları ve notlar aracılığıyla).
* **Yapay Zeka Destekli Geliştirme:** Bir MCP (Model Context Protocol) sunucusu sunarak LLM'lerin ve yapay zeka asistanlarının (Cursor, Claude vb.) canlı araç verisi üzerinde doğrudan analiz yapabilmesine olanak tanımak.
* **Özelleştirilebilir Araç Deneyimi:** Elde edilen veriler doğrultusunda, üçüncü parti yazılımlar ve açık kaynak donanımlarla (ESP8266) araca yeni otomasyonlar ve özellikler kazandırabilmek için bir altyapı sunmak.
* **Akıllı Filtreleme ve Kontrol:** Sadece belirli CAN ID'lerini izlemek veya araca doğrudan donanımsal komut göndermek için seri port üzerinden haberleşme (`filter`, `send` vb.) sağlamak.

---

## 🙏 Teşekkürler & Atıflar

Bu projenin geliştirilmesi ve Tesla CAN Bus verilerinin çözümlenmesi sürecinde aşağıdaki harika açık kaynaklı projelerden ilham alınmış ve büyük ölçüde faydalanılmıştır:
* [mikegapinski/tesla-can-explorer](https://github.com/mikegapinski/tesla-can-explorer) - CAN mesajlarının çözümlenmesi ve donanım iletişim prensipleri
* [commaai/opendbc](https://github.com/commaai/opendbc) - Kapsamlı ve açık kaynaklı DBC (veritabanı) dosyası arşivi

---

## ⚠️ Sorumluluk Reddi (Disclaimer)

Bu proje tamamen eğitim ve araştırma amaçlıdır. Aracın CAN Bus hattına veri enjekte etmek (yazmak) **tehlikeli olabilir** ve aracın beklenmedik tepkiler vermesine veya sürüş güvenliğinin tehlikeye girmesine yol açabilir. 

Bu yazılımı kullanırken oluşabilecek her türlü donanımsal arıza, kaza veya garanti dışı kalma durumu tamamen **sizin sorumluluğunuzdadır.** Hareket halindeki bir araçta CAN Bus enjeksiyon testleri yapmayın.
