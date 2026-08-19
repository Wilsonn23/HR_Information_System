# ============================================================
# MOCK DATA SEEDER -- Modul Aset
# Jalankan: python mock_aset.py
# ============================================================

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules['app'] = __import__('app', fromlist=['*'])

from app import app, db
from app import (
    Pulau, Kota, PT, Unit, KodeUnit, NamaAsuransi, Merk, Kategori,
    LokasiKerja, DataEntry, ReportEntry, AuditLog
)
from datetime import datetime, timedelta
import random

ACTOR = 'admin'

def future_date(months):
    d = datetime.today() + timedelta(days=months * 30)
    return d.strftime('%Y-%m-%d')

def past_date(months):
    d = datetime.today() - timedelta(days=months * 30)
    return d.strftime('%Y-%m-%d')

def rand_date(y1=2023, y2=2025):
    s = datetime(y1, 1, 1)
    e = datetime(y2, 12, 31)
    return (s + timedelta(days=random.randint(0, (e - s).days))).strftime('%Y-%m-%d')

def rand_plate():
    pfx = random.choice(['B', 'D', 'F', 'BG', 'BE', 'BN', 'DK', 'DE'])
    num = random.randint(1000, 9999)
    suf = ''.join(random.choices('ABCDEFGHJKLMNPQRST', k=random.randint(2,3)))
    return f"{pfx} {num} {suf}"

def rand_sn(pfx='SN', n=8):
    return pfx + ''.join(random.choices('0123456789ABCDEF', k=n))

with app.app_context():

    # 1. PULAU
    print("=== MASTER DATA ===")
    pulau_list = ['SUMATRA', 'JAWA', 'KALIMANTAN', 'SULAWESI', 'NUSA TENGGARA BARAT', 'PAPUA']
    pulau_map = {}
    for nm in pulau_list:
        obj = db.session.execute(db.select(Pulau).where(Pulau.nama == nm)).scalar_one_or_none()
        if not obj:
            obj = Pulau(nama=nm, dilakukan_oleh=ACTOR)
            db.session.add(obj)
            db.session.flush()
            print(f"  + Pulau: {nm}")
        pulau_map[nm] = obj.id
    db.session.commit()

    # 2. KOTA
    kota_tree = {
        'SUMATRA':              [('PALEMBANG', 'Palembang'), ('JAMBI', 'Jambi'), ('BANGKA', 'Bangka')],
        'JAWA':                 [('JAKARTA', 'Jakarta'), ('BANDUNG', 'Bandung'), ('SURABAYA', 'Surabaya')],
        'KALIMANTAN':           [('PONTIANAK', 'Pontianak'), ('BANJARMASIN', 'Banjarmasin')],
        'SULAWESI':             [('MAKASSAR', 'Makassar'), ('KENDARI', 'Kendari')],
        'NUSA TENGGARA BARAT':  [('LOMBOK', 'Lombok'), ('SUMBAWA', 'Sumbawa')],
        'PAPUA':                [('MERAUKE', 'Merauke'), ('JAYAPURA', 'Jayapura')],
    }
    kota_map = {}
    for pulau_nm, kts in kota_tree.items():
        for code, nm in kts:
            obj = db.session.execute(db.select(Kota).where(Kota.nama == nm)).scalar_one_or_none()
            if not obj:
                obj = Kota(nama=nm, reference=pulau_map[pulau_nm], dilakukan_oleh=ACTOR)
                db.session.add(obj)
                db.session.flush()
                print(f"  + Kota: {nm}")
            kota_map[code] = obj.id
    db.session.commit()

    # 3. PT
    pt_tree = {
        'PALEMBANG':   [('PT Mitra Palembang Sejahtera', 'MPS'), ('PT Sriwijaya Energi', 'SWE')],
        'JAMBI':       [('PT Jambi Persada Utama', 'JPU')],
        'BANGKA':      [('PT Bangka Timah Resources', 'BTR')],
        'JAKARTA':     [('PT Nusantara Prima', 'NP'), ('PT Garudaindo Nusantara', 'GN')],
        'BANDUNG':     [('PT Parahyangan Motor', 'PM')],
        'SURABAYA':    [('PT Surya Jaya Abadi', 'SJA')],
        'PONTIANAK':   [('PT Borneo Pratama', 'BP')],
        'BANJARMASIN': [('PT Mahakam Sentosa', 'MS')],
        'MAKASSAR':    [('PT Celebes Makmur', 'CM')],
        'KENDARI':     [('PT Sultra Persada', 'SP')],
        'LOMBOK':      [('PT Lombok Bersatu', 'LB')],
        'SUMBAWA':     [('PT Sumbawa Agro', 'SA')],
        'MERAUKE':     [('PT Merauke Sejahtera', 'MKE')],
        'JAYAPURA':    [('PT Cenderawasih Resources', 'CR')],
    }
    pt_map = {}
    for kota_code, pts in pt_tree.items():
        kota_id = kota_map.get(kota_code)
        if not kota_id:
            continue
        for pt_nm, abbr in pts:
            obj = db.session.execute(
                db.select(PT).where(PT.nama == pt_nm, PT.reference == kota_id)
            ).scalar_one_or_none()
            if not obj:
                obj = PT(nama=pt_nm, reference=kota_id, dilakukan_oleh=ACTOR)
                db.session.add(obj)
                db.session.flush()
                print(f"  + PT: {pt_nm}")
            pt_map[(kota_code, pt_nm)] = obj.id
    db.session.commit()

    # 4. UNIT
    unit_templates = ['Workshop Pusat', 'Workshop Cabang', 'Bengkel Mobile', 'Pool Kendaraan', 'Operasional']
    unit_map = {}
    for (kota_code, pt_nm), pt_id in pt_map.items():
        for unit_nm in random.sample(unit_templates, k=2):
            obj = db.session.execute(
                db.select(Unit).where(Unit.nama == unit_nm, Unit.reference == pt_id)
            ).scalar_one_or_none()
            if not obj:
                obj = Unit(nama=unit_nm, reference=pt_id, dilakukan_oleh=ACTOR)
                db.session.add(obj)
                db.session.flush()
                print(f"  + Unit: {unit_nm} [{pt_nm}]")
            unit_map[(kota_code, pt_nm, unit_nm)] = obj.id
    db.session.commit()

    # 5. LOKASI KERJA
    lokasi_map = {}  # (kota_code, pt_nm, unit_nm) -> nama lokasi
    for (kota_code, pt_nm, unit_nm), uid in unit_map.items():
        kota_id = kota_map.get(kota_code)
        if not kota_id: continue
        kota_obj = db.session.get(Kota, kota_id)
        pulau_obj = db.session.get(Pulau, kota_obj.reference) if kota_obj else None
        if not pulau_obj: continue

        # Buat 2 lokasi kerja per unit
        for suffix in ['Utama', 'Cadangan']:
            lokasi_nama = f"{unit_nm} {suffix}"
            pt_obj = db.session.execute(
                db.select(PT).where(PT.nama == pt_nm)
            ).scalar_one_or_none()
            unit_obj = db.session.execute(
                db.select(Unit).where(Unit.nama == unit_nm, Unit.reference == pt_obj.id)
            ).scalar_one_or_none() if pt_obj else None

            # Buat KodeUnit dummy untuk lokasi
            cn = f"{kota_code[:2]}{suffix[:2].upper()}"
            kode_unit_obj = db.session.execute(
                db.select(KodeUnit).where(KodeUnit.nama == cn)
            ).scalar_one_or_none() if unit_obj else None
            if unit_obj and not kode_unit_obj:
                kode_unit_obj = KodeUnit(nama=cn, reference=unit_obj.id, dilakukan_oleh=ACTOR)
                db.session.add(kode_unit_obj)
                db.session.flush()

            existing = db.session.execute(
                db.select(LokasiKerja).where(
                    LokasiKerja.nama == lokasi_nama,
                    LokasiKerja.pt == pt_nm
                )
            ).scalar_one_or_none()
            if not existing:
                existing = LokasiKerja(
                    kode_unit = cn,
                    owner     = unit_nm,
                    pulau     = pulau_obj.nama,
                    kota      = kota_obj.nama,
                    pt        = pt_nm,
                    nama      = lokasi_nama,
                    dilakukan_oleh = ACTOR,
                )
                db.session.add(existing)
                db.session.flush()
                print(f"  + LokasiKerja: {lokasi_nama} [{pt_nm}]")
            lokasi_map[(kota_code, pt_nm, unit_nm, suffix)] = lokasi_nama
    db.session.commit()

    # 6. ASURANSI
    asuransi_list = [
        'Jasindo', 'Astra Buana', 'Sinar Mas', 'Adira Insurance',
        'Tugu Pratama', 'Bumiputera Muda', 'Central Asia Raya',
        'Ramayana', 'Mega Insurance', 'Takaful Umum'
    ]
    for nm in asuransi_list:
        if not db.session.execute(db.select(NamaAsuransi).where(NamaAsuransi.nama == nm)).scalar_one_or_none():
            db.session.add(NamaAsuransi(nama=nm, dilakukan_oleh=ACTOR))
    db.session.commit()
    print(f"  + {len(asuransi_list)} Asuransi")

    # 6. MERK
    merk_list = [
        'Toyota', 'Mitsubishi', 'Hino', 'Isuzu', 'Komatsu',
        'Caterpillar', 'Volvo', 'Nissan', 'Daihatsu', 'Honda',
        'Suzuki', 'Hyundai', 'Doosan', 'Liebherr', 'Wacker Neuson'
    ]
    for nm in merk_list:
        if not db.session.execute(db.select(Merk).where(Merk.nama == nm)).scalar_one_or_none():
            db.session.add(Merk(nama=nm, dilakukan_oleh=ACTOR))
    db.session.commit()
    print(f"  + {len(merk_list)} Merk")

    # 7. KATEGORI
    kat_list = [
        'Pick Up', 'Dump Truck', 'Excavator', 'Crane', 'Forklift',
        'Bus', 'Truck Box', 'Trailer', 'Mini Bus', 'Motor',
        'Vibro Roller', 'Grader', 'Loader', 'Bulldozer', 'Generator Set'
    ]
    for nm in kat_list:
        if not db.session.execute(db.select(Kategori).where(Kategori.nama == nm)).scalar_one_or_none():
            db.session.add(Kategori(nama=nm, dilakukan_oleh=ACTOR))
    db.session.commit()
    print(f"  + {len(kat_list)} Kategori")

    # =========================================================
    # 8. DATA ENTRIES (60 ASET)
    # =========================================================
    print("\n=== DATA ENTRIES ===")

    merk_kat_model = [
        ('Toyota',       'Pick Up',     ['Hilux', 'Hilux Double Cabin', 'Fortuner']),
        ('Toyota',       'Mini Bus',    ['HiAce', 'Innova']),
        ('Mitsubishi',   'Pick Up',     ['L200 Strada', 'Triton']),
        ('Mitsubishi',   'Dump Truck',  ['Canter FE74', 'Fuso FJ2523']),
        ('Hino',         'Dump Truck',  ['Hino 300', 'Hino 500', 'Hino Ranger']),
        ('Hino',         'Truck Box',   ['Hino 300 Box', 'Hino 500 Box']),
        ('Isuzu',        'Truck Box',   ['Isuzu Giga', 'Isuzu ELF']),
        ('Komatsu',      'Excavator',   ['PC200-8', 'PC300-8', 'PC400-7']),
        ('Komatsu',      'Bulldozer',   ['D85ESS-2', 'D65PX-18']),
        ('Caterpillar',  'Excavator',   ['CAT 320', 'CAT 330', 'CAT 390']),
        ('Caterpillar',  'Grader',      ['CAT 140M', 'CAT 120M']),
        ('Volvo',        'Excavator',   ['EC210', 'EC300']),
        ('Mitsubishi',   'Forklift',    ['FD30N', 'FD50N']),
        ('Komatsu',      'Loader',      ['WA270-7', 'WA380-7']),
        ('Hyundai',      'Excavator',   ['R220LC-9S', 'R290LC-9']),
        ('Honda',        'Motor',       ['Supra GTR 150', 'Vario 160']),
        ('Suzuki',       'Motor',       ['Satria F150', 'Smash 115']),
        ('Daihatsu',     'Pick Up',     ['Gran Max PU', 'Gran Max STD']),
        ('Hino',         'Bus',         ['Hino AK8 JRBS', 'Hino RK8']),
        ('Wacker Neuson','Vibro Roller',['RD12', 'RD16']),
    ]

    loc_list = []
    for (kota_code, pt_nm, unit_nm), uid in unit_map.items():
        kota_id = kota_map.get(kota_code)
        if not kota_id: continue
        kota_obj = db.session.get(Kota, kota_id)
        pulau_obj = db.session.get(Pulau, kota_obj.reference) if kota_obj else None
        if not pulau_obj: continue
        for suffix in ['Utama', 'Cadangan']:
            lokasi_nama = lokasi_map.get((kota_code, pt_nm, unit_nm, suffix), f"{unit_nm} {suffix}")
            loc_list.append({'pulau': pulau_obj.nama, 'kota': kota_obj.nama, 'pt': pt_nm, 'unit': unit_nm, 'lokasi_kerja': lokasi_nama, 'kota_code': kota_code})

    random.shuffle(loc_list)
    inserted = 0

    for i in range(60):
        loc = loc_list[i % len(loc_list)]
        merk, kat, models = merk_kat_model[i % len(merk_kat_model)]
        model = random.choice(models)
        year = random.randint(2015, 2024)

        unit_code = ''.join([w[0] for w in loc['unit'].split()])[:3].upper()
        pt_code   = ''.join([w[0] for w in loc['pt'].split() if w[0].isupper()])[:4].upper()
        pkey = f"{loc['kota'].upper()[:3]}-{pt_code}-{unit_code}-{str(i+1).zfill(4)}"

        if db.session.execute(db.select(DataEntry).where(DataEntry.pkey == pkey)).scalar_one_or_none():
            pkey += f"-{i}"

        stnk_mo  = random.choice([-3, -1, 2, 5, 8, 14])
        asuransi_mo = random.choice([-2, 1, 4, 7, 11, 13])

        st_stnk = 'BELUM BAYAR' if stnk_mo < 0 else ('SUDAH BAYAR' if stnk_mo <= 2 else 'AKTIF')
        st_asi  = 'BELUM BAYAR' if asuransi_mo < 0 else ('SUDAH BAYAR' if asuransi_mo <= 2 else 'AKTIF')

        tgl_stnk  = future_date(stnk_mo)  if stnk_mo > 0  else past_date(-stnk_mo)
        tgl_asi   = future_date(asuransi_mo) if asuransi_mo > 0 else past_date(-asuransi_mo)

        entry = DataEntry(
            pulau         = loc['pulau'],
            kota          = loc['kota'],
            pt            = loc['pt'],
            unit          = loc['unit'],
            kode_unit     = unit_code,
            pkey          = pkey,
            status        = random.choice(['ON','ON','ON','ON','OFF']),
            lokasi_kerja  = loc['lokasi_kerja'],
            nama_asuransi = random.choice(asuransi_list),
            no_polis      = f"POL-{random.randint(100000,999999)}",
            no_polisi     = rand_plate(),
            merk          = merk,
            kategori      = kat,
            eqp_model     = model,
            sn_equipment  = rand_sn('EQP', 8),
            sn_engine     = rand_sn('ENG', 8),
            status_stnk   = st_stnk,
            status_asuransi = st_asi,
            tanggal_berakhir_stnk      = tgl_stnk,
            tanggal_berakhir_asuransi  = tgl_asi,
            year          = year,
            pembulatan_stnk      = round(random.uniform(0, 50000), 0),
            pembulatan_asuransi  = round(random.uniform(0, 100000), 0),
            total_stnk           = round(random.uniform(500000, 3000000), 0),
            total_asuransi       = round(random.uniform(2000000, 15000000), 0),
            harus_dibayar_stnk   = round(random.uniform(500000, 3000000), 0),
            harus_dibayar_asuransi = round(random.uniform(2000000, 15000000), 0),
            notes         = None,
            tanggal_input = rand_date(),
            diinput_oleh  = ACTOR,
        )
        db.session.add(entry)
        db.session.flush()
        inserted += 1
        print(f"  [{i+1:02d}/60] {pkey:35s} {merk} {model} | {loc['unit']}, {loc['kota']}")

    db.session.commit()
    print(f"Total DataEntry inserted: {inserted}")

    # =========================================================
    # 9. REPORT ENTRIES (Riwayat Perpanjang)
    # =========================================================
    print("\n=== REPORT ENTRIES ===")
    all_pkeys = [r.pkey for r in db.session.execute(db.select(DataEntry)).scalars().all()]
    rpt_count = 0
    for pkey in all_pkeys[:40]:
        for jenis in random.sample(['STNK', 'Asuransi'], k=random.randint(1, 2)):
            for _ in range(random.randint(1, 3)):
                pay_date = past_date(random.randint(3, 36))
                rpt = ReportEntry(
                    jenis=jenis,
                    pkey=pkey,
                    tanggal_berakhir_baru=future_date(random.randint(6, 14)),
                    jumlah_dibayar=round(random.uniform(500000, 15000000), 0),
                    tanggal_bayar=pay_date,
                    tanggal_input=pay_date,
                    diinput_oleh=ACTOR,
                )
                db.session.add(rpt)
                rpt_count += 1
    db.session.commit()
    print(f"Total ReportEntry inserted: {rpt_count}")

    # =========================================================
    # 10. AUDIT LOGS
    # =========================================================
    print("\n=== AUDIT LOGS ===")
    actions = ['TAMBAH', 'EDIT', 'MUTASI', 'PERPANJANG', 'DISABLE', 'ENABLE']
    users   = ['admin', 'operasional1', 'operasional2']
    aud_count = 0
    for pkey in all_pkeys[:30]:
        for _ in range(random.randint(1, 4)):
            aksi = random.choice(actions)
            log = AuditLog(
                pkey=pkey,
                aksi=aksi,
                kolom_diubah='status' if aksi in ('DISABLE', 'ENABLE') else 'no_polisi',
                nilai_lama='ON' if aksi == 'DISABLE' else None,
                nilai_baru='OFF' if aksi == 'DISABLE' else 'ON',
                dilakukan_oleh=random.choice(users),
                tanggal_aksi=datetime.strptime(rand_date(2024, 2026), '%Y-%m-%d'),
            )
            db.session.add(log)
            aud_count += 1
    db.session.commit()
    print(f"Total AuditLog inserted: {aud_count}")

    # =========================================================
    # SUMMARY
    # =========================================================
    from sqlalchemy import func
    print("\n" + "="*60)
    print("SELESAI! Ringkasan data:")
    for Model, label in [
        (Pulau, 'Pulau'), (Kota, 'Kota'), (PT, 'PT'), (Unit, 'Unit'),
        (NamaAsuransi, 'Asuransi'), (Merk, 'Merk'), (Kategori, 'Kategori'),
        (DataEntry, 'DataEntry'), (ReportEntry, 'ReportEntry'), (AuditLog, 'AuditLog'),
    ]:
        cnt = db.session.execute(db.select(func.count()).select_from(Model)).scalar()
        print(f"  {label:<15}: {cnt}")
    print("="*60)

