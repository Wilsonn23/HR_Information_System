# ============================================================
# MOCK DATA SEEDER -- Modul SDM
# Jalankan: python mock_sdm.py
# ============================================================

import sys
import os
import random
from datetime import datetime, date, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules['app'] = __import__('app', fromlist=['*'])

from app import app, db
from app import (
    SdmPT, SdmDivisi, SdmDepartemen, Jabatan,
    KaryawanEntry, Cuti, CutiManual, Bulan, HariLibur, Kehadiran, SdmActivityLog
)

ACTOR = 'Admin'

FIRST_NAMES = [
    "Ahmad", "Budi", "Candra", "Dedi", "Eko", "Feri", "Gita", "Hadi", "Indra", "Joko",
    "Kartika", "Lestari", "Mulyono", "Novi", "Oki", "Putra", "Rini", "Siti", "Tri", "Utami",
    "Wibowo", "Yanto", "Zainal", "Aditya", "Bayu", "Dewi", "Elisa", "Farhan", "Gilang", "Hani",
    "Irfan", "Julia", "Kevin", "Lia", "Maulana", "Nanda", "Oscar", "Pratiwi", "Rian", "Siska",
    "Taufik", "Umar", "Vina", "Wahyu", "Yuda", "Zahra", "Aldo", "Bagas", "Citra", "Dian",
    "Agus", "Bambang", "Doni", "Endang", "Fitri", "Gunawan", "Hendra", "Ika", "Jaka", "Kusuma"
]

LAST_NAMES = [
    "Pratama", "Wijaya", "Santoso", "Saputra", "Hidayat", "Kusuma", "Setiawan", "Lestari", 
    "Siregar", "Nasution", "Ginting", "Sitompul", "Simanjuntak", "Pane", "Harahap", "Lubis", 
    "Pohan", "Sitorus", "Tampubolon", "Pangaribuan", "Gunawan", "Suharto", "Susilo", "Yudhoyono", 
    "Widodo", "Prabowo", "Megawati", "Sukarno", "Habibie", "Gusdur", "Wahyuni", "Sari", "Rahayu",
    "Ningsih", "Astuti", "Fitriani", "Ramadhan", "Akbar", "Kurniawan", "Sholeh", "Hadi", "Putri",
    "Firmansyah", "Permana", "Wicaksono", "Anggraini", "Wulandari", "Mahendra", "Purnomo", "Utomo"
]

MONTH_NAMES = [
    ('Januari', 31), ('Februari', 28), ('Maret', 31), ('April', 30),
    ('Mei', 31), ('Juni', 30), ('Juli', 31), ('Agustus', 31),
    ('September', 30), ('Oktober', 31), ('November', 30), ('Desember', 31)
]

def generate_unique_names(count):
    names = set()
    attempts = 0
    while len(names) < count and attempts < 10000:
        attempts += 1
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        names.add(f"{fn} {ln}")
    while len(names) < count:
        names.add(f"Karyawan {len(names)+1}")
    return list(names)

with app.app_context():
    print("=== SEEDING MASTER SDM ===")

    # 1. BULAN
    for m_name, m_days in MONTH_NAMES:
        obj = db.session.get(Bulan, m_name)
        if not obj:
            db.session.add(Bulan(nama=m_name, jumlah_hari=m_days))
    db.session.commit()
    print("  + Master Bulan siap")

    # 2. HARI LIBUR
    holidays = [
        (date(2026, 1, 1), "Tahun Baru Masehi"),
        (date(2026, 2, 17), "Tahun Baru Imlek"),
        (date(2026, 3, 20), "Hari Raya Idul Fitri"),
        (date(2026, 3, 21), "Hari Raya Idul Fitri"),
        (date(2026, 5, 1), "Hari Buruh Internasional"),
        (date(2026, 5, 14), "Kenaikan Isa Almasih"),
        (date(2026, 6, 1), "Hari Lahir Pancasila"),
        (date(2026, 8, 17), "Hari Kemerdekaan RI"),
        (date(2026, 12, 25), "Hari Raya Natal"),
    ]
    for h_date, h_ket in holidays:
        existing = db.session.execute(db.select(HariLibur).where(HariLibur.tanggal == h_date)).scalar_one_or_none()
        if not existing:
            db.session.add(HariLibur(tanggal=h_date, keterangan=h_ket))
    db.session.commit()
    print("  + Master Hari Libur siap")

    # 3. ORGANIZATIONAL STRUCTURE
    org_structure = {
        "PT SINERGI MANDIRI": {
            "Finance": ["Accounting", "Treasury", "Tax"],
            "HR": ["Recruitment", "Training", "Compensation"],
            "General Affairs": ["Facility", "Procurement"]
        },
        "PT WAHANA KARYA": {
            "Operations": ["Logistics", "Warehouse", "Production"],
            "IT": ["Software Dev", "Tech Support", "Cyber Security"],
            "HSE": ["Safety", "Environment"]
        },
        "PT GLOBAL NIAGA": {
            "Marketing": ["Sales", "Branding", "Digital Marketing"],
            "Public Relations": ["Media Relations", "Internal Comms"],
            "Supply Chain": ["Planning", "Distribution"]
        }
    }

    # Seed Master PT, Divisi, Departemen, Jabatan
    for pt_name, divs in org_structure.items():
        if not db.session.execute(db.select(SdmPT).where(SdmPT.nama == pt_name)).scalar_one_or_none():
            db.session.add(SdmPT(nama=pt_name, dilakukan_oleh=ACTOR))
        
        for div_name, depts in divs.items():
            if not db.session.execute(db.select(SdmDivisi).where(SdmDivisi.nama == div_name)).scalar_one_or_none():
                db.session.add(SdmDivisi(nama=div_name, dilakukan_oleh=ACTOR))
            
            # Jabatan Kepala Divisi
            jab_kadiv = f"Kepala Divisi {div_name}"
            if not db.session.execute(db.select(Jabatan).where(Jabatan.nama == jab_kadiv)).scalar_one_or_none():
                db.session.add(Jabatan(nama=jab_kadiv, dilakukan_oleh=ACTOR))
                
            for dept_name in depts:
                if not db.session.execute(db.select(SdmDepartemen).where(SdmDepartemen.nama == dept_name)).scalar_one_or_none():
                    db.session.add(SdmDepartemen(nama=dept_name, dilakukan_oleh=ACTOR))
                
                # Jabatan Kepala Dept & Staff
                jab_kadept = f"Kepala Departemen {dept_name}"
                if not db.session.execute(db.select(Jabatan).where(Jabatan.nama == jab_kadept)).scalar_one_or_none():
                    db.session.add(Jabatan(nama=jab_kadept, dilakukan_oleh=ACTOR))
                
                jab_staff = f"Staff {dept_name}"
                if not db.session.execute(db.select(Jabatan).where(Jabatan.nama == jab_staff)).scalar_one_or_none():
                    db.session.add(Jabatan(nama=jab_staff, dilakukan_oleh=ACTOR))
    
    db.session.commit()
    print("  + Master SDM (PT, Divisi, Departemen, Jabatan) siap")

    # 4. KARYAWAN ENTRIES (200 KARYAWAN)
    print("\n=== SEEDING KARYAWAN & CUTI (200 DATA) ===")
    
    TOTAL_KARYAWAN = 200
    unique_names = generate_unique_names(TOTAL_KARYAWAN)
    name_idx = 0
    absen_counter = 1001

    karyawan_records = []

    # Priority 1: Kepala Divisi
    for pt, divs in org_structure.items():
        for div in divs.keys():
            karyawan_records.append({
                "absen": absen_counter,
                "nik": f"NIK{absen_counter}",
                "nama": unique_names[name_idx],
                "tmk": (datetime(2015, 1, 1) + timedelta(days=random.randint(0, 1800))).strftime("%Y-%m-%d"),
                "jam_masuk": time(8, 0),
                "jam_pulang": time(17, 0),
                "pt": pt,
                "staff": "Staff",
                "jabatan": f"Kepala Divisi {div}",
                "divisi": div,
                "departemen": None,
                "priority_level": 1
            })
            absen_counter += 1
            name_idx += 1

    # Priority 2: Kepala Departemen
    all_dept_tuples = []
    for pt, divs in org_structure.items():
        for div, depts in divs.items():
            for dept in depts:
                all_dept_tuples.append((pt, div, dept))
                karyawan_records.append({
                    "absen": absen_counter,
                    "nik": f"NIK{absen_counter}",
                    "nama": unique_names[name_idx],
                    "tmk": (datetime(2017, 1, 1) + timedelta(days=random.randint(0, 1500))).strftime("%Y-%m-%d"),
                    "jam_masuk": time(8, 0),
                    "jam_pulang": time(17, 0),
                    "pt": pt,
                    "staff": "Staff",
                    "jabatan": f"Kepala Departemen {dept}",
                    "divisi": div,
                    "departemen": dept,
                    "priority_level": 2
                })
                absen_counter += 1
                name_idx += 1

    # Priority 3: Staff Karyawan
    remaining = TOTAL_KARYAWAN - len(karyawan_records)
    for _ in range(remaining):
        pt, div, dept = random.choice(all_dept_tuples)
        karyawan_records.append({
            "absen": absen_counter,
            "nik": f"NIK{absen_counter}",
            "nama": unique_names[name_idx],
            "tmk": (datetime(2019, 1, 1) + timedelta(days=random.randint(0, 2000))).strftime("%Y-%m-%d"),
            "jam_masuk": time(8, 0),
            "jam_pulang": time(17, 0),
            "pt": pt,
            "staff": "Staff",
            "jabatan": f"Staff {dept}",
            "divisi": div,
            "departemen": dept,
            "priority_level": 3
        })
        absen_counter += 1
        name_idx += 1

    inserted_karyawan = 0
    all_niks = []
    for rec in karyawan_records:
        existing = db.session.get(KaryawanEntry, rec['nik'])
        if not existing:
            new_k = KaryawanEntry(
                nik=rec['nik'],
                absen=rec['absen'],
                nama=rec['nama'],
                jabatan=rec['jabatan'],
                tmk=rec['tmk'],
                jam_masuk=rec['jam_masuk'],
                jam_pulang=rec['jam_pulang'],
                pt=rec['pt'],
                staff=rec['staff'],
                divisi=rec['divisi'],
                departemen=rec['departemen'],
                priority_level=rec['priority_level'],
                dilakukan_oleh=ACTOR
            )
            db.session.add(new_k)
            
            # Cuti Record
            cuti_thn = random.choice([0, 3, 6, 8, 10, 12])
            cuti_dns = random.choice([0, 2, 4])
            new_c = Cuti(
                nik=rec['nik'],
                cuti_tahunan=float(cuti_thn),
                cuti_dinas=float(cuti_dns)
            )
            db.session.add(new_c)
            inserted_karyawan += 1
            all_niks.append(rec['nik'])
            
    db.session.commit()
    print(f"  + {inserted_karyawan} Data Karyawan & Cuti berhasil dibuat")

    # 5. SAMPLE CUTI MANUAL
    print("\n=== SEEDING SAMPLE CUTI MANUAL ===")
    cm_count = 0
    for nik in all_niks[:30]:
        tgl = (datetime(2026, 1, 1) + timedelta(days=random.randint(5, 180))).strftime("%Y-%m-%d")
        cm = CutiManual(
            nik=nik,
            tanggal_input=tgl,
            jumlah=float(random.choice([1, 2, 3])),
            tipe=random.choice(['CT', 'CD']),
            keterangan="Cuti Keperluan Keluarga / Tugas Luar",
            ba_nomor=f"BA/SDM/2026/{random.randint(100, 999)}",
            ba_tanggal=tgl,
            ba_keterangan="Disetujui oleh Manajemen"
        )
        db.session.add(cm)
        cm_count += 1
    db.session.commit()
    print(f"  + {cm_count} Data Cuti Manual dibuat")

    # 6. KEHADIRAN SAMPLE
    print("\n=== SEEDING SAMPLE KEHADIRAN ===")
    kehadiran_count = 0
    target_months = [('Juli', 7, 31, 2026), ('Agustus', 8, 31, 2026)]
    
    for nik in all_niks[:50]:  # Seed kehadiran untuk 50 karyawan
        for bln_nama, bln_num, bln_days, thn in target_months:
            existing_kh = db.session.execute(
                db.select(Kehadiran).where(Kehadiran.nik == nik, Kehadiran.bulan == bln_nama, Kehadiran.tahun == thn)
            ).scalar_one_or_none()
            
            if not existing_kh:
                status_dict = {}
                masuk_dict = {}
                pulang_dict = {}
                
                for d in range(1, bln_days + 1):
                    d_str = str(d)
                    dt = date(thn, bln_num, d)
                    
                    # Minggu / Sabtu (Weekend)
                    if dt.weekday() == 6: # Minggu
                        status_dict[d_str] = 'OFF'
                    elif dt.weekday() == 5: # Sabtu
                        status_dict[d_str] = 'OFF'
                    elif dt == date(2026, 8, 17): # Libur Kemerdekaan
                        status_dict[d_str] = 'L'
                    else:
                        # Hari Kerja
                        r = random.random()
                        if r < 0.92:
                            status_dict[d_str] = 'M'
                            # Scan masuk (07:40 - 08:15)
                            m_minute = random.randint(40, 75)
                            m_hour = 7 if m_minute < 60 else 8
                            m_min = m_minute % 60
                            masuk_dict[d_str] = f"{m_hour:02d}:{m_min:02d}"
                            
                            # Scan pulang (17:00 - 17:45)
                            p_min = random.randint(0, 45)
                            pulang_dict[d_str] = f"17:{p_min:02d}"
                        elif r < 0.95:
                            status_dict[d_str] = random.choice(['S', 'DL'])
                        elif r < 0.98:
                            status_dict[d_str] = 'CT'
                        else:
                            status_dict[d_str] = random.choice(['CD', 'CN'])

                new_kh = Kehadiran(
                    nik=nik,
                    bulan=bln_nama,
                    tahun=thn,
                    status_hari=status_dict,
                    scan_masuk_hari=masuk_dict,
                    scan_pulang_hari=pulang_dict,
                    keterangan_hari={},
                    izin_hari={}
                )
                db.session.add(new_kh)
                kehadiran_count += 1
                
    db.session.commit()
    print(f"  + {kehadiran_count} Data Rekap Kehadiran dibuat")

    # 7. SDM ACTIVITY LOGS
    print("\n=== SEEDING SDM ACTIVITY LOGS ===")
    log_actions = [
        ("TAMBAH_KARYAWAN", "KARYAWAN", "Menambahkan data karyawan baru ke sistem"),
        ("UPDATE_JABATAN", "KARYAWAN", "Memperbarui jabatan dan divisi karyawan"),
        ("INPUT_CUTI_MANUAL", "CUTI", "Menambahkan pengajuan cuti manual karyawan"),
        ("IMPORT_KEHADIRAN", "KEHADIRAN", "Mengimpor rekap kehadiran bulanan")
    ]
    log_count = 0
    for nik in all_niks[:40]:
        aksi, kat, det = random.choice(log_actions)
        k_obj = db.session.get(KaryawanEntry, nik)
        log = SdmActivityLog(
            aksi=aksi,
            kategori=kat,
            nik=nik,
            nama_karyawan=k_obj.nama if k_obj else "Karyawan",
            detail=f"{det} - {nik}",
            dilakukan_oleh=ACTOR,
            tanggal_aksi=datetime.now() - timedelta(days=random.randint(1, 60))
        )
        db.session.add(log)
        log_count += 1
        
    db.session.commit()
    print(f"  + {log_count} Activity Log dibuat")

    # =========================================================
    # SUMMARY
    # =========================================================
    from sqlalchemy import func
    print("\n" + "="*60)
    print("SELESAI! Ringkasan Data SDM:")
    for Model, label in [
        (SdmPT, 'Master PT SDM'), (SdmDivisi, 'Master Divisi'),
        (SdmDepartemen, 'Master Departemen'), (Jabatan, 'Master Jabatan'),
        (HariLibur, 'Master Hari Libur'), (KaryawanEntry, 'Karyawan Entries'),
        (Cuti, 'Data Cuti'), (CutiManual, 'Cuti Manual'),
        (Kehadiran, 'Rekap Kehadiran'), (SdmActivityLog, 'Activity Logs')
    ]:
        cnt = db.session.execute(db.select(func.count()).select_from(Model)).scalar()
        print(f"  {label:<22}: {cnt}")
    print("="*60)
