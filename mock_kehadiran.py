# ============================================================
# MOCK DATA SEEDER -- Data Kehadiran SDM
# Jalankan: python mock_kehadiran.py
# ============================================================

import sys
import os
import random
import pandas as pd
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules['app'] = __import__('app', fromlist=['*'])

from app import app, db
from app import KaryawanEntry, Kehadiran, HariLibur

MONTHS_2026 = [
    ('Januari', 1, 31),
    ('Februari', 2, 28),
    ('Maret', 3, 31),
    ('April', 4, 30),
    ('Mei', 5, 31),
    ('Juni', 6, 30),
    ('Juli', 7, 31),
    ('Agustus', 8, 31),
]

HOLIDAYS_2026 = {
    date(2026, 1, 1): "Tahun Baru Masehi",
    date(2026, 2, 17): "Tahun Baru Imlek",
    date(2026, 3, 20): "Hari Raya Idul Fitri",
    date(2026, 3, 21): "Hari Raya Idul Fitri",
    date(2026, 5, 1): "Hari Buruh Internasional",
    date(2026, 5, 14): "Kenaikan Isa Almasih",
    date(2026, 6, 1): "Hari Lahir Pancasila",
    date(2026, 8, 17): "Hari Kemerdekaan RI",
    date(2026, 12, 25): "Hari Raya Natal",
}

with app.app_context():
    print("=== MEMBUAT DATA MOCK KEHADIRAN (2026) ===")

    # 1. Ambil semua karyawan aktif
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()

    if not karyawan_list:
        print("❌ Error: Tidak ada data karyawan! Jalankan 'python mock_sdm.py' terlebih dahulu.")
        sys.exit(1)

    print(f"Ditemukan {len(karyawan_list)} karyawan terdaftar.")

    # 2. Ambil hari libur dari DB jika ada
    db_holidays = {h.tanggal: h.keterangan for h in db.session.execute(db.select(HariLibur)).scalars().all()}
    all_holidays = {**HOLIDAYS_2026, **db_holidays}

    total_inserted = 0
    total_updated = 0
    excel_rows = []

    for k in karyawan_list:
        for bln_nama, bln_num, bln_days in MONTHS_2026:
            # Check existing Kehadiran record
            kh = db.session.execute(
                db.select(Kehadiran).where(
                    Kehadiran.nik == k.nik,
                    Kehadiran.bulan == bln_nama,
                    Kehadiran.tahun == 2026
                )
            ).scalar_one_or_none()

            status_dict = {}
            masuk_dict = {}
            pulang_dict = {}
            keterangan_dict = {}
            izin_dict = {}

            for day in range(1, bln_days + 1):
                day_str = str(day)
                dt = date(2026, bln_num, day)

                # Cek jika sebelum TMK (belum masuk kerja)
                try:
                    tmk_dt = datetime.strptime(k.tmk, "%Y-%m-%d").date() if k.tmk else date(2020, 1, 1)
                except ValueError:
                    tmk_dt = date(2020, 1, 1)

                if dt < tmk_dt:
                    continue

                # Cek jika sudah resign
                if k.tanggal_resign:
                    try:
                        resign_dt = datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                        if dt > resign_dt:
                            continue
                    except ValueError:
                        pass

                # Weekend: Sabtu (5) / Minggu (6)
                if dt.weekday() in (5, 6):
                    status_dict[day_str] = 'OFF'
                # Hari Libur Nasional
                elif dt in all_holidays:
                    status_dict[day_str] = 'L'
                    keterangan_dict[day_str] = all_holidays[dt]
                else:
                    # Hari Kerja
                    r = random.random()
                    
                    # Berikan beberapa sampel Pending (P) khusus bulan Agustus 2026 pada tanggal 18 & 19 untuk beberapa karyawan
                    if bln_num == 8 and day in (18, 19) and (k.absen % 12 == 0):
                        status_dict[day_str] = 'P'
                        # Contoh: Ada yang hanya scan masuk tanpa scan pulang
                        if k.absen % 24 == 0:
                            masuk_dict[day_str] = "08:15"
                            pulang_dict[day_str] = ""
                            keterangan_dict[day_str] = "Lupa scan pulang (Pending)"
                        else:
                            masuk_dict[day_str] = ""
                            pulang_dict[day_str] = ""
                            keterangan_dict[day_str] = "Belum ada data scan (Pending)"
                    elif r < 0.88:
                        # MASUK (M)
                        status_dict[day_str] = 'M'
                        
                        # Variasi scan masuk:
                        # 70% Tepat waktu (07:35 - 08:00)
                        # 30% Terlambat (08:05 - 09:15)
                        if random.random() < 0.70:
                            m_minute = random.randint(35, 59)
                            m_time = f"07:{m_minute:02d}"
                        else:
                            # Masuk Terlambat
                            terlambat_minutes = random.choice([5, 8, 12, 18, 25, 35, 45, 60, 75])
                            m_hour = 8 + (terlambat_minutes // 60)
                            m_min = terlambat_minutes % 60
                            m_time = f"{m_hour:02d}:{m_min:02d}"
                            
                        # Scan pulang (17:00 - 18:30)
                        p_minute = random.randint(0, 45)
                        p_time = f"17:{p_minute:02d}"

                        masuk_dict[day_str] = m_time
                        pulang_dict[day_str] = p_time

                        # Tambahkan ke data export excel contoh untuk bulan Agustus 2026
                        if bln_num == 8:
                            excel_rows.append({
                                "nik": k.nik,
                                "absen": k.absen,
                                "nama": k.nama,
                                "tanggal": dt.strftime("%m/%d/%Y"),
                                "scan masuk": m_time,
                                "scan pulang": p_time
                            })

                    elif r < 0.91:
                        # DINAS LUAR (DL)
                        status_dict[day_str] = 'DL'
                        keterangan_dict[day_str] = "Tugas Dinas Luar Kota"
                    elif r < 0.94:
                        # SAKIT (S)
                        status_dict[day_str] = 'S'
                        keterangan_dict[day_str] = "Surat Dokter Terlampir"
                    elif r < 0.97:
                        # CUTI TAHUNAN (CT)
                        status_dict[day_str] = 'CT'
                        keterangan_dict[day_str] = "Cuti Tahunan"
                    elif r < 0.99:
                        # CUTI DINAS (CD)
                        status_dict[day_str] = 'CD'
                        keterangan_dict[day_str] = "Cuti Dinas"
                    else:
                        # CUTI NORMATIF (CN)
                        status_dict[day_str] = 'CN'
                        keterangan_dict[day_str] = "Cuti Khusus/Normatif"

            if not kh:
                kh = Kehadiran(
                    nik=k.nik,
                    bulan=bln_nama,
                    tahun=2026,
                    status_hari=status_dict,
                    scan_masuk_hari=masuk_dict,
                    scan_pulang_hari=pulang_dict,
                    keterangan_hari=keterangan_dict,
                    izin_hari=izin_dict
                )
                db.session.add(kh)
                total_inserted += 1
            else:
                kh.status_hari = status_dict
                kh.scan_masuk_hari = masuk_dict
                kh.scan_pulang_hari = pulang_dict
                kh.keterangan_hari = keterangan_dict
                kh.izin_hari = izin_dict
                total_updated += 1

        if (total_inserted + total_updated) % 400 == 0:
            db.session.commit()
            print(f"  ... Diproses {total_inserted + total_updated} record kehadiran")

    db.session.commit()
    print("\n[OK] Selesai mengisi database Kehadiran:")
    print(f"   - Record baru dibuat : {total_inserted}")
    print(f"   - Record diperbarui  : {total_updated}")
    print(f"   - Total record       : {total_inserted + total_updated} (200 karyawan x 8 bulan)")

    # 3. Export contoh file Excel untuk fitur upload kehadiran
    if excel_rows:
        df = pd.DataFrame(excel_rows)
        excel_path = "dummy_kehadiran_sample.xlsx"
        df.to_excel(excel_path, index=False)
        print(f"\n[OK] File Excel contoh kehadiran berhasil dibuat: '{excel_path}' ({len(excel_rows)} baris scan absensi)")
