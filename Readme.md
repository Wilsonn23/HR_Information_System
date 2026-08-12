# HR Information System (HRIS) & Asset Management App

Aplikasi berbasis web untuk mengelola data sumber daya manusia (SDM) dan manajemen aset unit secara terintegrasi menggunakan framework Flask (Python) dan database PostgreSQL.

---

## Persyaratan Sistem

Pastikan sistem Anda sudah terinstal:
- **Python 3.10 / 3.11** (untuk instalasi lokal)
- **Docker & Docker Compose** (jika ingin menjalankan dengan kontainer)
- **PostgreSQL** (jika menjalankan lokal tanpa Docker)

---

## 🐋 Cara Menjalankan Menggunakan Docker Compose (Direkomendasikan)

Ini adalah cara termudah dan tercepat karena database dan server web sudah diorkestrasi secara otomatis.

1. **Aktifkan Docker Desktop** di komputer Anda.
2. Jalankan perintah berikut di folder root project untuk mem-build image dan menyalakan kontainer:
   ```bash
   docker compose up --build
   ```
3. Buka browser Anda dan akses aplikasi di:
   **[http://localhost:5000](http://localhost:5000)**

*Catatan: Data database akan tersimpan secara persisten pada volume Docker bernama `pgdata` sehingga aman meskipun kontainer dimatikan.*

---

## 🛠️ CLI / Perintah Script Utility

Beberapa script utility yang dapat dijalankan secara lokal (setelah mengaktifkan venv):

- **Impor Karyawan Baru dari Excel**:
  ```bash
  python import_karyawan.py path/to/karyawan.xlsx
  ```
- **Impor Data Kehadiran / Absensi dari Excel**:
  ```bash
  python import_kehadiran.py path/to/absensi.xlsx
  ```