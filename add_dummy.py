#!/usr/bin/env python
"""
Script to populate the PostgreSQL database with random dummy equipment entries for testing.
"""

from datetime import datetime, timedelta
import random
import sys
from app import app, db, DataEntry, AuditLog, Pulau, Kota, PT, Unit, NamaAsuransi, Merk, Kategori

# Define valid option maps to keep data entries valid for forms validation
PULAU_KOTA_MAPPINGS = [
    ("PAPUA", "MERAUKE"),
    ("JAWA", "JAKARTA"),
    ("SUMATRA", "PALEMBANG"),
    ("SUMATRA", "JAMBI"),
    ("SUMATRA", "BANGKA"),
    ("NUSA TENGGARA BARAT", "LOMBOK")
]

PT_LIST = ["BDP", "IJS", "MM", "SALE"]

CATEGORIES = [
    ("EXCAVATOR", "KOMATSU", "PC2008", "PC"),
    ("DUMP TRUCK", "HINO", "FM260JD", "DT"),
    ("LIGHT VEHICLE", "TOYOTA", "HILUX 2.4", "LV"),
    ("COMPACTOR", "CAT", "CS11GC", "CP"),
    ("DOZER", "CATERPILLAR", "D6R", "DZ"),
    ("WHEEL LOADER", "KOMATSU", "WA350", "WL"),
    ("MOTOR GRADER", "CATERPILLAR", "120K", "MG")
]

INSURANCE_COMPANIES = ["ZURICH INSURANCE", "TUGU PRATAMA", "ASURANSI SINAR MAS", "ASURANSI ALLIANZ", "ASURANSI ASTRA"]

def populate_master_tables():
    print("Populating master tables...")
    # 1. Pulau and Kota
    for p_name, k_name in PULAU_KOTA_MAPPINGS:
        p = db.session.execute(db.select(Pulau).where(Pulau.nama == p_name)).scalar_one_or_none()
        if not p:
            p = Pulau(nama=p_name, dilakukan_oleh="System Dummy Setup")
            db.session.add(p)
            db.session.commit()
        
        k = db.session.execute(db.select(Kota).where(Kota.nama == k_name)).scalar_one_or_none()
        if not k:
            k = Kota(nama=k_name, reference=p.id, dilakukan_oleh="System Dummy Setup")
            db.session.add(k)
            db.session.commit()
            
    # 2. PT under all Kotas
    kotas = db.session.execute(db.select(Kota)).scalars().all()
    for k in kotas:
        for pt_name in PT_LIST:
            pt = db.session.execute(db.select(PT).where(PT.nama == pt_name, PT.reference == k.id)).scalar_one_or_none()
            if not pt:
                pt = PT(nama=pt_name, reference=k.id, dilakukan_oleh="System Dummy Setup")
                db.session.add(pt)
                db.session.commit()
                
    # 3. Unit under all PTs
    pts = db.session.execute(db.select(PT)).scalars().all()
    for pt in pts:
        # Create unit with same name as PT to match f"{pt}-{pt}" structure in old dummy
        u = db.session.execute(db.select(Unit).where(Unit.nama == pt.nama, Unit.reference == pt.id)).scalar_one_or_none()
        if not u:
            u = Unit(nama=pt.nama, reference=pt.id, dilakukan_oleh="System Dummy Setup")
            db.session.add(u)
            db.session.commit()
            
    # 4. Asuransi
    for asu_name in INSURANCE_COMPANIES:
        a = db.session.execute(db.select(NamaAsuransi).where(NamaAsuransi.nama == asu_name)).scalar_one_or_none()
        if not a:
            a = NamaAsuransi(nama=asu_name, dilakukan_oleh="System Dummy Setup")
            db.session.add(a)
            db.session.commit()
            
    # 5. Merk and Kategori from CATEGORIES
    for cat_name, brand, model, cat_prefix in CATEGORIES:
        m = db.session.execute(db.select(Merk).where(Merk.nama == brand)).scalar_one_or_none()
        if not m:
            m = Merk(nama=brand, dilakukan_oleh="System Dummy Setup")
            db.session.add(m)
            db.session.commit()
            
        kat = db.session.execute(db.select(Kategori).where(Kategori.nama == cat_name)).scalar_one_or_none()
        if not kat:
            kat = Kategori(nama=cat_name, dilakukan_oleh="System Dummy Setup")
            db.session.add(kat)
            db.session.commit()
            
    print("Master tables populated successfully.")

def generate_random_string(prefix, length=6):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return f"{prefix}" + "".join(random.choice(chars) for _ in range(length))

def generate_random_date(today, category_offset):
    # category_offset can be: 'expired', 'warning', 'notice', 'safe', 'none'
    if category_offset == 'none':
        return None
    elif category_offset == 'expired':
        days = random.randint(1, 60)
        return today - timedelta(days=days)
    elif category_offset == 'warning':
        days = random.randint(1, 29)
        return today + timedelta(days=days)
    elif category_offset == 'notice':
        days = random.randint(30, 90)
        return today + timedelta(days=days)
    else: # 'safe'
        days = random.randint(91, 365)
        return today + timedelta(days=days)

def create_dummy_data(count=50):
    print(f"Generating {count} randomized dummy records...")
    
    # Base date
    today = datetime.strptime("2026-07-14", "%Y-%m-%d").date()
    
    with app.app_context():
        populate_master_tables()
        
        inserted_count = 0
        skipped_count = 0
        
        # Pull distinct existing keys in db to avoid duplicate insert checks
        existing_pkeys = {r[0] for r in db.session.query(DataEntry.pkey).all()}
        
        for i in range(1, count + 1):
            pulau, kota = random.choice(PULAU_KOTA_MAPPINGS)
            pt = random.choice(PT_LIST)
            unit = f"{pt}-{pt}"
            
            cat_name, brand, model, cat_prefix = random.choice(CATEGORIES)
            
            # Formulate random unique CN code number
            cn_code = f"DMY{cat_prefix}{random.randint(100, 999)}"
            
            # Format pkey: pulau-kota-pt-unit-kode_unit
            pkey_val = f"{pulau}-{kota}-{unit}-{cn_code}"
            
            # Safeguard unique constraints
            if pkey_val in existing_pkeys:
                skipped_count += 1
                continue
                
            # Randomly assign status brackets
            stnk_bracket = random.choice(['expired', 'warning', 'notice', 'safe', 'none'])
            asu_bracket = random.choice(['expired', 'warning', 'notice', 'safe', 'none'])
            
            stnk_date = generate_random_date(today, stnk_bracket)
            asu_date = generate_random_date(today, asu_bracket)
            
            stnk_status = "ON" if stnk_date is not None else "OFF"
            asu_status = "ON" if asu_date is not None else "OFF"
            
            stnk_date_str = stnk_date.strftime("%Y-%m-%d") if stnk_date else None
            asu_date_str = asu_date.strftime("%Y-%m-%d") if asu_date else None
            
            # Generate random finance values for realistic reporting
            biaya_stnk = round(random.uniform(500000, 5000000), 2)
            biaya_admin_stnk = round(random.uniform(50000, 200000), 2)
            total_stnk_raw = biaya_stnk + biaya_admin_stnk
            total_stnk_val = float(round(total_stnk_raw, 0))
            pembulatan_stnk_val = round(total_stnk_val - total_stnk_raw, 2)
            
            biaya_asu = round(random.uniform(1000000, 15000000), 2)
            biaya_admin_asu = round(random.uniform(100000, 500000), 2)
            total_asu_raw = biaya_asu + biaya_admin_asu
            total_asu_val = float(round(total_asu_raw, 0))
            pembulatan_asu_val = round(total_asu_val - total_asu_raw, 2)
            
            new_entry = DataEntry(
                pulau=pulau,
                kota=kota,
                pt=pt,
                unit=unit,
                kode_unit=cn_code,
                pkey=pkey_val,
                lokasi_kerja=unit, # Make it refer to a valid PT-Unit combined name
                nama_asuransi=random.choice(INSURANCE_COMPANIES),
                no_polis=generate_random_string("POL", 8),
                no_polisi=generate_random_string("B", 5),
                merk=brand,
                kategori=cat_name,
                eqp_model=model,
                sn_equipment=generate_random_string("SEQ", 7),
                sn_engine=generate_random_string("SEN", 7),
                status_stnk=stnk_status,
                status_asuransi=asu_status,
                tanggal_berakhir_stnk=stnk_date_str,
                tanggal_berakhir_asuransi=asu_date_str,
                year=random.randint(2018, 2026),
                notes=f"Random Mock Unit: STNK bracket={stnk_bracket}, Asuransi bracket={asu_bracket}",
                # Finance properties
                biaya_perpanjang_stnk=biaya_stnk,
                biaya_administrasi_stnk=biaya_admin_stnk,
                biaya_perpanjang_asuransi=biaya_asu,
                biaya_administrasi_asuransi=biaya_admin_asu,
                pembulatan_stnk=pembulatan_stnk_val,
                pembulatan_asuransi=pembulatan_asu_val,
                total_stnk=total_stnk_val,
                total_asuransi=total_asu_val,
                harus_dibayar_stnk=total_stnk_val,
                harus_dibayar_asuransi=total_asu_val,
                tanggal_input=today.strftime("%Y-%m-%d"),
                diinput_oleh="Random Dummy Script"
            )
            db.session.add(new_entry)
            existing_pkeys.add(pkey_val)
            
            # Add corresponding audit trace log
            new_log = AuditLog(
                pkey=pkey_val,
                aksi="TAMBAH",
                kolom_diubah="Tambah Unit Dummy Acak",
                nilai_lama="-",
                nilai_baru=f"Unit dummy acak {cn_code} dimasukkan.",
                dilakukan_oleh="Random Dummy Script",
                tanggal_aksi=datetime.now()
            )
            db.session.add(new_log)
            inserted_count += 1
            
        if inserted_count > 0:
            try:
                db.session.commit()
                print(f"Successfully generated and saved {inserted_count} new random dummy records (skipped {skipped_count} duplicates)!")
            except Exception as e:
                db.session.rollback()
                print(f"Database commit failed: {e}")
        else:
            print("No new dummy records were added.")

if __name__ == "__main__":
    count_val = 500
    if len(sys.argv) > 1:
        try:
            count_val = int(sys.argv[1])
        except ValueError:
            pass
    create_dummy_data(count_val)
