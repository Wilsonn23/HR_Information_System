import random
import pandas as pd
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app import app, db
from sqlalchemy import text

# Names list to generate unique combinations
first_names = [
    "Ahmad", "Budi", "Candra", "Dedi", "Eko", "Feri", "Gita", "Hadi", "Indra", "Joko",
    "Kartika", "Lestari", "Mulyono", "Novi", "Oki", "Putra", "Rini", "Siti", "Tri", "Utami",
    "Wibowo", "Yanto", "Zainal", "Aditya", "Bayu", "Dewi", "Elisa", "Farhan", "Gilang", "Hani",
    "Irfan", "Julia", "Kevin", "Lia", "maulana", "Nanda", "Oscar", "Pratiwi", "Rian", "Siska",
    "Taufik", "Umar", "Vina", "Wahyu", "Yuda", "Zahra", "Aldo", "Bagas", "Citra", "Dian"
]
last_names = [
    "Pratama", "Wijaya", "Santoso", "Saputra", "Hidayat", "Kusuma", "Setiawan", "Lestari", 
    "Siregar", "Nasution", "Ginting", "Sitompul", "Simanjuntak", "Pane", "Harahap", "Lubis", 
    "Pohan", "Sitorus", "Tampubolon", "Pangaribuan", "Gunawan", "Suharto", "Susilo", "Yudhoyono", 
    "Widodo", "Prabowo", "Megawati", "Sukarno", "Habibie", "Gusdur", "Wahyuni", "Sari", "Rahayu",
    "Ningsih", "Astuti", "Fitriani", "Ramadhan", "Akbar", "Kurniawan", "Sholeh", "Hadi", "Putri"
]

def generate_unique_names(count):
    names = set()
    while len(names) < count:
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        names.add(f"{fn} {ln}")
    return list(names)

def generate_data(count):
    unique_names = generate_unique_names(count)
    
    org_structure = {
        "PT Sinergi Mandiri": {
            "Finance": ["Accounting", "Treasury", "Tax"],
            "HR": ["Recruitment", "Training", "Compensation"]
        },
        "PT Wahana Karya": {
            "Operations": ["Logistics", "Warehouse", "Production"],
            "IT": ["Software Dev", "Tech Support", "Cyber Security"]
        },
        "PT Global Niaga": {
            "Marketing": ["Sales", "Branding", "Digital Marketing"],
            "Public Relations": ["Media Relations", "Internal Comms"]
        }
    }
    
    records = []
    name_idx = 0
    absen_counter = 1000
    
    # 1. Generate Heads of Divisions (1 per Division)
    for pt, divisions in org_structure.items():
        for divisi in divisions.keys():
            absen = absen_counter
            nik = f"NIK{absen}"
            nama = unique_names[name_idx]
            
            records.append({
                "absen": absen,
                "nik": nik,
                "nama": nama,
                "tmk": (datetime(2015, 1, 1) + timedelta(days=random.randint(0, 2000))).strftime("%Y-%m-%d"),
                "jam masuk": "08:00",
                "jam pulang": "17:00",
                "pt": pt,
                "staff": "Staff",
                "jabatan": f"Kepala Divisi {divisi}",
                "divisi": divisi,
                "departemen": "",
                "priority level": 1
            })
            absen_counter += 1
            name_idx += 1

    # 2. Generate Heads of Departments (1 per Department)
    # Collect all departments to make random picking of staff easier
    all_depts = []
    for pt, divisions in org_structure.items():
        for divisi, depts in divisions.items():
            for dept in depts:
                all_depts.append((pt, divisi, dept))
                
                absen = absen_counter
                nik = f"NIK{absen}"
                nama = unique_names[name_idx]
                
                records.append({
                    "absen": absen,
                    "nik": nik,
                    "nama": nama,
                    "tmk": (datetime(2017, 1, 1) + timedelta(days=random.randint(0, 2000))).strftime("%Y-%m-%d"),
                    "jam masuk": "08:00",
                    "jam pulang": "17:00",
                    "pt": pt,
                    "staff": "Staff",
                    "jabatan": f"Kepala Departemen {dept}",
                    "divisi": divisi,
                    "departemen": dept,
                    "priority level": 2
                })
                absen_counter += 1
                name_idx += 1

    # 3. Generate remaining as Staff (Priority 3)
    remaining_count = count - len(records)
    for _ in range(remaining_count):
        pt, divisi, dept = random.choice(all_depts)
        
        absen = absen_counter
        nik = f"NIK{absen}"
        nama = unique_names[name_idx]
        
        records.append({
            "absen": absen,
            "nik": nik,
            "nama": nama,
            "tmk": (datetime(2019, 1, 1) + timedelta(days=random.randint(0, 2000))).strftime("%Y-%m-%d"),
            "jam masuk": "08:00",
            "jam pulang": "17:00",
            "pt": pt,
            "staff": "Staff",
            "jabatan": f"Staff {dept}",
            "divisi": divisi,
            "departemen": dept,
            "priority level": 3
        })
        absen_counter += 1
        name_idx += 1
        
    return records

if __name__ == "__main__":
    print("Clearing employee records and related tables from database...")
    with app.app_context():
        try:
            # PostgreSQL Cascade truncate
            db.session.execute(text("TRUNCATE TABLE cuti_manual, cuti, kehadiran, karyawan_entries CASCADE"))
            db.session.commit()
            print("Successfully cleared database tables!")
        except Exception as e:
            db.session.rollback()
            print("Error clearing tables:", e)
            sys.exit(1)
            
    print("Generating 200 dummy employees...")
    records = generate_data(200)
    df = pd.DataFrame(records)
    
    excel_path = "dummy_karyawan_test.xlsx"
    df.to_excel(excel_path, index=False)
    print(f"Successfully generated {excel_path}!")
