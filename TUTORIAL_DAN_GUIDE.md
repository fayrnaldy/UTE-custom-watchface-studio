# ⌚ Panduan Lengkap: Cara Bikin Custom Watchface Smartwatch Budget dari Nol & Oprek Ekosistemnya

> **Panduan edukatif & tutorial step-by-step untuk komunitas penggiat tech, opreker gadget, dan follower media sosial.**  
> Dokumen ini menjelaskan rahasia di balik sistem smartwatch budget, cara kerja tool yang kita buat, hingga kompatibilitas dengan smartwatch merek lain.

---

## 📑 Daftar Isi
1. [Rahasia Dapur: Kenapa Smartwatch Murah Bisa Dioprek?](#1-rahasia-dapur-kenapa-smartwatch-murah-bisa-dioprek)
2. [Cara Kerja Tool (Visual Studio + MITM Injector)](#2-cara-kerja-tool-visual-studio--mitm-injector)
3. [Tutorial Step-by-Step untuk Pemula](#3-tutorial-step-by-step-untuk-pemula)
   - [Langkah 1: Jalankan Tool di Laptop](#langkah-1-jalankan-tool-di-laptop)
   - [Langkah 2: Desain Watchface di Browser](#langkah-2-desain-watchface-di-browser)
   - [Langkah 3: Pasang Sertifikat di HP (Cukup Sekali Seumur Hidup)](#langkah-3-pasang-sertifikat-di-hp-cukup-sekali-seumur-hidup)
   - [Langkah 4: Suntikkan ke Jam Tangan dalam 30 Detik](#langkah-4-suntikkan-ke-jam-tangan-dalam-30-detik)
4. [Tanya Jawab Kompatibilitas: Smartwatch Tipe Lain Bisa Nggak?](#4-tanya-jawab-kompatibilitas-smartwatch-tipe-lain-bisa-nggak)
5. [Troubleshooting & Tips Keamanan (Anti-Brick)](#5-troubleshooting--tips-keamanan-anti-brick)

---

## 1. Rahasia Dapur: Kenapa Smartwatch Murah Bisa Dioprek?

Banyak orang mengira bikin watchface kustom hanya bisa dilakukan di Apple Watch atau Galaxy Watch yang harganya jutaan rupiah. Nyatanya, smartwatch budget (rentang harga 200rb - 500rb seperti Aolon, Kospet, Colmi, dsb) justru memiliki arsitektur yang sangat menarik untuk dioprek!

### Bedanya dengan Apple Watch / Galaxy Watch
* **Smartwatch Mahal (Wear OS / watchOS):** Menjalankan sistem operasi penuh (seperti Android/iOS mini). Watchface berupa aplikasi kecil yang dikompilasi menggunakan SDK resmi dan didistribusikan lewat Google Play Store / App Store.
* **Smartwatch Budget (RTOS / Real-Time Operating System):** Menggunakan mikrokontroler hemat daya dengan RAM sangat kecil (seringkali di bawah 1 MB). Jam tangan ini tidak menjalankan kode program berat di layar, melainkan **merender gambar binary statis (`.bin`)** yang sudah disiapkan sebelumnya.

### Trik "Man-in-the-Middle" (MITM)
Biasanya aplikasi bawaan jam (seperti Aolon atau GloryFit) membatasi kita: hanya boleh memilih gambar wallpaper sendiri dengan format jam digital bawaan yang kaku. 

Namun di aplikasi tersebut, ada menu **"Dial Market" / "Pusat Dial"** di mana kita bisa men-download ratusan watchface gratis dari internet. 

Di sinilah trik kita bekerja:
1. Kita membuat server perantara (**Proxy**) di laptop.
2. HP kita diarahkan untuk lewat jalur proxy ini saat browsing.
3. Saat kita menekan tombol **"Download"** pada salah satu watchface gratis di aplikasi HP, aplikasi akan meminta file `.bin` ke server resmi di cloud.
4. Proxy kita mencegat request tersebut, lalu **menukar file `.bin` resmi dengan file `.bin` hasil desain kita sendiri di Web Studio**!
5. Aplikasi HP mengira file tersebut asli dari server, lalu mentransfernya via Bluetooth ke jam tangan.
6. Hasilnya: **Watchface kustom impianmu langsung tampil di layar jam tanpa perlu membongkar hardware ataupun nge-root HP!**

---

## 2. Cara Kerja Tool (Visual Studio + MITM Injector)

Tool ini dirancang seringkas dan semodular mungkin:
1. **Visual Web Studio (`studio.html` & `studio.mjs`):**
   - Berjalan di browser lokal (`http://localhost:3333`).
   - Menyediakan kanvas visual sesuai resolusi layar asli (**390 × 450 AMOLED** dengan bezel melengkung).
   - Mendukung drag-and-drop elemen: waktu digital 7-segmen, tanggal, detak jantung, baterai, efek CRT retro, hingga stiker karakter (seperti Miss Minutes atau logo anime).
2. **Reverse Engineered Compiler (`ute_wf.py`):**
   - Merakit susunan grafis menjadi format biner resmi mikrokontroler UTE:
     - Header kontainer 24-byte (mencakup ID watchface dan checksum CRC32).
     - Format kompresi citra **PA (fmt 0x0200)** yang mengemas warna 16-bit RGB565 dan 8-bit Alpha mask per baris piksel.
   - Dibuat dengan **Pure Python Standar (0 Dependencies)**, tanpa perlu install modul berat seperti OpenCV atau Pillow.
3. **Auto-ID MITM Interceptor (`proxy.mjs`):**
   - Berjalan di port `8888`.
   - Secara dinamis mendeteksi ID watchface yang sedang diminta oleh aplikasi HP, lalu menyematkan ID tersebut dan menghitung ulang CRC32 pada file kustom kita secara otomatis dalam hitungan milidetik.

---

## 3. Tutorial Step-by-Step untuk Pemula

### Persiapan
- Laptop / PC (**Mac, Windows, atau Linux**) yang sudah terinstall:
  - **Node.js** (versi 18 ke atas)
  - **Python 3** (versi 3.8 ke atas)
- Smartwatch (misal: **Aolon GTS 3**) yang sudah tersambung ke aplikasi **Aolon** atau **GloryFit** di HP.
- Laptop dan HP terhubung ke **jaringan Wi-Fi yang sama** (atau HP tethering/hotspot ke laptop).

---

### Langkah 1: Jalankan Tool di Laptop
Buka Terminal (Mac/Linux) atau Command Prompt / PowerShell (Windows), lalu jalankan:

```bash
git clone https://github.com/USERNAME_KAMU/aolon-gts3-watchface.git
cd aolon-gts3-watchface
npm start
```

Terminal akan otomatis mendeteksi IP Wi-Fi laptop kamu dan menampilkan pesan seperti ini:
```text
============================================================
  ⌚ Aolon GTS3 Watchface Studio & Injector is RUNNING!
============================================================
  🎨 Web Studio : http://localhost:3333
  🛡️ Proxy Port : 8888
  🌐 Your IP    : 192.168.1.15  (Catat IP ini untuk disetel di HP)
============================================================
```

---

### Langkah 2: Desain Watchface di Browser
1. Buka browser di laptop, kunjungi: `http://localhost:3333`
2. Kamu bisa langsung memilih preset keren yang sudah disediakan:
   - **`Casio Retro Digital`**: Nuansa jam digital klasik Casio F-91W / A168W lengkap dengan frame water-resist dan font LCD.
   - **`Loki TVA Sacred Timeline`**: Tema retro-futuristik TVA dari serial Loki dengan gelombang garis timeline dan font terminal vintage.
   - **`TVA Miss Minutes`**: Dilengkapi stiker resmi Miss Minutes maskot TVA.
3. Kamu juga bisa menggeser elemen, mengubah warna, mengatur ukuran, atau mengupload stiker PNG transparan buatanmu sendiri.
4. Jika sudah puas dengan desainnya:
   - Klik **`💾 Simpan Proyek`**
   - Klik **`⚡ Compile & Pasang ke Proxy`**
   *(Selesai! File binary kustom kamu sudah siap disuntikkan oleh server proxy).*

---

### Langkah 3: Pasang Sertifikat di HP (Cukup Sekali Seumur Hidup)
Karena aplikasi HP berkomunikasi lewat protokol aman HTTPS, HP perlu memercayai proxy lokal kita:

1. Di HP, buka browser (Safari di iPhone atau Chrome di Android), lalu buka alamat:  
   `http://<IP_LAPTOP_KAMU>:8888/ca.crt`  
   *(Contoh: `http://192.168.1.15:8888/ca.crt`)*
2. File sertifikat akan otomatis terunduh.
3. **Khusus Pengguna iPhone (iOS):**
   - Buka **Settings** > tap banner **Profile Downloaded** > tap **Install**.
   - Buka **Settings > General > About > Certificate Trust Settings** (paling bawah) > aktifkan saklar hijau pada **Aolon GTS3 Watchface Proxy CA**.
4. **Khusus Pengguna Android:**
   - Buka **Settings > Security > Install a Certificate > CA Certificate** > pilih file `ca.crt` yang baru di-download > konfirmasi.

> 💡 *Langkah ini hanya perlu dilakukan sekali saja. Untuk pembuatan watchface berikutnya di masa depan, langkah ini bisa langsung dilewati!*

---

### Langkah 4: Suntikkan ke Jam Tangan dalam 30 Detik
1. **Setel Proxy di HP:**
   - **iPhone:** Masuk ke **Settings > Wi-Fi** > tap tanda `(i)` di sebelah nama Wi-Fi yang tersambung > scroll ke bawah: **Configure Proxy** pilih **Manual** > masukkan **Server** (IP laptop kamu) dan **Port** `8888` > tap **Save**.
   - **Android:** Masuk ke **Settings > Wi-Fi** > tap icon gear/pengaturan Wi-Fi > pilih **Proxy: Manual** > masukkan Hostname IP laptop dan Port `8888` > simpan.
2. **Kirim ke Jam:**
   - Buka aplikasi **Aolon** di HP.
   - Buka menu **Dial Center / Pasar Watchface**.
   - Pilih salah satu watchface gratis yang **belum pernah kamu download sebelumnya**, lalu klik **Download / Sinkronkan**.
3. **Selesai!**
   - Proxy di laptop akan otomatis mencegat request tersebut dan menggantinya dengan desain kustom kamu.
   - Progress bar download di HP akan berjalan hingga 100%, dan watchface baru langsung menyala di pergelangan tanganmu!
4. **Kembalikan Pengaturan Proxy:**
   - Setelah sukses, matikan pengaturan proxy di HP (kembalikan ke **Off / None**).
   - Tekan `Ctrl + C` di terminal laptop untuk mematikan server.

---

## 4. Tanya Jawab Kompatibilitas: Smartwatch Tipe Lain Bisa Nggak?

Banyak follower yang bertanya:  
*"Min, kalau smartwatch saya merk Colmi / Olike / Kospet / Haylou / Xiaomi / Huawei bisa pakai cara ini juga nggak?"*

Berikut adalah penjelasan teknis arsitekturnya:

| Ekosistem Chipset | Contoh Aplikasi di PlayStore / AppStore | Merek / Tipe Jam Populer | Apakah Bisa Pakai Tool Ini? |
| :--- | :--- | :--- | :--- |
| **UTE / YouCheng** | **Aolon**, **GloryFit**, Kospet Fit | Aolon GTS 3, Kospet Tank, Zeblaze Ares, bbrp tipe Mibro | ✅ **BISA LANGSUNG!** Format filenya sama persis (`WF` v2). Jika ukuran layarnya bukan 390x450 (misal 240x280), cukup ubah parameter resolusi di kode compiler. |
| **MoYoung / Da Fit** | **Da Fit**, Pubu | Colmi (P8, C60, dsb), Olike, Fire-Boltt | ⚠️ **Bisa Oprek, tapi Format Beda.** Da Fit menggunakan format Type-C `.bin` yang di-pack dengan tool komunitas bernama `extrathundertool` atau aplikasi Android `DaFup`. Trik proxy MITM-nya tetap bisa dipakai! |
| **FitCloudPro / TopStep** | **FitCloudPro** | Jam tangan clone Apple Watch murah (seri T800, Ultra clone), Kinyo | ⚠️ **Format TBUI.** Menggunakan struktur biner TBUI khusus. Memerlukan TBUI Unpacker/Packer. |
| **JieLi / JL AC701x** | **RDFit**, Wearfit Pro, HryFine | HW series, HK8 Pro Max, jam replika chip JieLi | ⚠️ **Format JL AC701x UI.** Harus di-compile menggunakan JL Watchface SDK/Tool khusus. |
| **Zepp OS (Amazfit)** | **Zepp** | Amazfit GTR, GTS, Bip, Cheetah, T-Rex | ℹ️ **Ekosistem Terbuka Resmi.** Amazfit sudah menyediakan JavaScript SDK resmi (Zepp OS SDK), jadi tidak perlu teknik MITM ilegal. Bisa langsung bikin pakai web studio resmi Amazfit. |
| **Wear OS** | Galaxy Wearable, Wear OS | Samsung Galaxy Watch 4/5/6, Pixel Watch | ℹ️ **Ekosistem Android Penuh.** Sudah tersedia tool resmi gratis dari Samsung yaitu **Watch Face Studio (WFS)** dengan ekspor format WFF (Watch Face Format). |

### Bagaimana Cara Cek Jam Milik Follower Masuk Kategori Mana?
Cara termudah adalah: **Lihat buku petunjuk atau kotak jamnya, aplikasi apa yang disuruh install di HP?**
- Jika aplikasinya **Aolon** atau **GloryFit** 👉 **100% menggunakan arsitektur UTE**, sama persis seperti project ini!
- Jika aplikasinya **Da Fit** 👉 Menggunakan arsitektur MoYoung.

---

## 5. Troubleshooting & Tips Keamanan (Anti-Brick)

### 1. Apakah Trik Ini Bisa Bikin Jam Rusak / "Mati Total" (Brick)?
**Tidak.**  
Pada smartwatch RTOS, firmware utama mikrokontroler (bootloader & Bluetooth stack) disimpan di partisi memori ROM yang terisolasi dan dilindungi hak akses write.  
File `.bin` watchface yang kita suntikkan hanya disimpan di partisi memori penyimpanan grafis eksternal (SPI Flash). Kalaupun ada kesalahan file atau format tidak cocok, jam tangan biasanya hanya menampilkan layar hitam sejenak atau kembali ke watchface default bawaan pabrik. Kamu tinggal menekan tombol putar/samping jam untuk memilih watchface asli bawaannya.

### 2. HP Gagal Konek ke Proxy Laptop
- Pastikan laptop dan HP terhubung ke **nama Wi-Fi yang sama**.
- Jika menggunakan Wi-Fi kantor, kampus, atau café yang memiliki fitur *Client Isolation* (perangkat dalam satu Wi-Fi dilarang saling menyapa), gunakan fitur **Hotspot Seluler dari HP** ke laptop, atau sebaliknya.
- Pastikan firewall di laptop tidak memblokir port `8888` dan `3333`.

### 3. Muncul Notifikasi "Internet Not Available" Saat Proxy Dinyalakan di HP
- Ini normal terjadi jika kamu belum mengaktifkan "Full Trust" pada sertifikat root CA di iPhone (*Settings > General > About > Certificate Trust Settings*).
- Setelah selesai mentransfer watchface ke jam, **jangan lupa matikan pengaturan proxy di HP** agar koneksi internet HP kamu kembali lancar normal.

---

## 💬 Penutup & Hak Cipta
Tool dan tutorial ini dibuat untuk tujuan pembelajaran (*reverse engineering* & edukasi arsitektur embedded RTOS).  
Silakan bagikan tutorial ini, buat tema sekreatif mungkin, dan sertakan link credit ke repository jika bermanfaat! 🚀
