#!/usr/bin/env python
"""
Import script to load data from an Excel file into the PostgreSQL database.
Usage:
    venv\\Scripts\\python import_excel.py <path_to_excel_file>
"""

import os
import sys
from datetime import datetime, date
import openpyxl
from sqlalchemy.exc import SQLAlchemyError

# Import Flask app and db components
try:
    from app import app, db, DataEntry, AuditLog
except ImportError as e:
    print(f"Error: Could not import Flask application components: {e}")
    sys.exit(1)

# Excel Column matching mapping
HEADER_MAPPINGS = {
    'pt': ['pt', 'nama pt', 'nama_pt'],
    'pulau': ['pulau'],
    'provinsi': ['site(provinsi)', 'site (provinsi)', 'provinsi', 'site', 'provinsi/site'],
    'cn': ['cn', 'cn unit', 'nomor cn', 'cn_unit'],
    'no_polisi': ['no_police', 'no. polisi', 'no polisi', 'no. police', 'no police', 'no_polisi'],
    'varian': ['varian'],
    'kategori': ['categori', 'kategori', 'category'],
    'eqp_model': ['eqp_model', 'equipment model', 'eqp model', 'equipment_model'],
    'sn_equipment': ['sn_equipment', 'sn equipment', 's/n equipment'],
    'sn_engine': ['sn_engine', 'sn engine', 's/n engine'],
    'year': ['year', 'tahun', 'tahun pembuatan'],
    'remaks': ['remaks', 'remarks', 'keterangan'],
    'no_polis_2025': ['no_polis_2025', 'no. polis 2025', 'no polis 2025'],
    'no_polis_2026': ['no_polis_2026', 'no. polis 2026', 'no polis 2026'],
    'nama_2025': ['nama_2025', 'nama asuransi 2025', 'nama_asuransi_2025'],
    'nama_2026': ['nama_2026', 'nama asuransi 2026', 'nama_asuransi_2026'],
    'akhir_2025': ['akhir_2025', 'masa berlaku akhir asuransi 2025', 'akhir_asuransi_2025'],
    'akhir_2026': ['akhir_2026', 'masa berlaku akhir asuransi 2026', 'akhir_asuransi_2026'],
    'keterangan_stnk': ['keterangan_stnk', 'keterangan stnk'],
    'tanggal_berakhir_stnk': ['stnk', 'masa berlaku stnk', 'tanggal stnk', 'stnk_date'],
    'notes': ['catatan', 'notes', 'catatan stnk', 'catatan asuransi', 'catatan_stnk']
}

# Indonesian month mapping for date parser
INDONESIAN_MONTHS = {
    'jan': 1, 'januari': 1,
    'feb': 2, 'peb': 2, 'februari': 2,
    'mar': 3, 'maret': 3,
    'apr': 4, 'april': 4,
    'mei': 5, 'may': 5,
    'jun': 6, 'juni': 6,
    'jul': 7, 'juli': 7,
    'ags': 8, 'agst': 8, 'agt': 8, 'agustus': 8,
    'sep': 9, 'sept': 9, 'september': 9,
    'okt': 10, 'oct': 10, 'oktober': 10,
    'nov': 11, 'november': 11,
    'des': 12, 'dec': 12, 'desember': 12
}

import re

def parse_indonesian_date(val_str):
    val_str = val_str.lower().strip()
    parts = re.split(r'[\s\-\/\.]+', val_str)
    if len(parts) == 3:
        p0, p1, p2 = parts
        
        # Check which part is the month
        month = None
        for p in (p0, p1, p2):
            if p in INDONESIAN_MONTHS:
                month = INDONESIAN_MONTHS[p]
                break
                
        if month is not None:
            remaining = [p for p in (p0, p1, p2) if p not in INDONESIAN_MONTHS]
            if len(remaining) == 2:
                try:
                    val1 = int(remaining[0])
                    val2 = int(remaining[1])
                    if val1 > 31:
                        year = val1
                        day = val2
                    elif val2 > 31:
                        year = val2
                        day = val1
                    else:
                        if val2 >= 100 or val2 > val1:
                            year = val2
                            day = val1
                        else:
                            year = val1
                            day = val2
                    
                    if year < 100:
                        year += 2000
                    return f"{year:04d}-{month:02d}-{day:02d}"
                except ValueError:
                    pass
    return None

def parse_date_value(val):
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime('%Y-%m-%d')
    
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ['-', '', 'none', 'null', 'n/a']:
        return None
        
    formats = [
        '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%m-%d-%Y',
        '%Y/%m/%d', '%Y.%m.%d', '%d.%m.%Y',
        '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f'
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
            
    # Try parsing Indonesian date string
    indo_date = parse_indonesian_date(val_str)
    if indo_date:
        return indo_date
        
    print(f"Warning: Could not parse date value '{val_str}'. Setting to None.")
    return None

def parse_status(val):
    if val is None:
        return "OFF"
    val_str = str(val).strip().lower()
    if val_str in ['on', 'aktif', 'active', 'yes', 'y', '1', '1.0']:
        return "ON"
    return "OFF"

def parse_year(val):
    if val is None:
        return 0
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return 0

def map_headers(header_row):
    col_map = {}
    for col_idx, cell in enumerate(header_row):
        if cell.value is None:
            continue
        val = str(cell.value).strip().lower()
        # Find match in mappings
        matched = False
        for field, aliases in HEADER_MAPPINGS.items():
            if val in aliases:
                col_map[field] = col_idx
                matched = True
                break
        if not matched:
            for field, aliases in HEADER_MAPPINGS.items():
                if any(alias in val for alias in aliases):
                    col_map[field] = col_idx
                    break
    return col_map

def import_excel(file_path):
    print(f"Opening workbook: {file_path}")
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.active
        print(f"Loaded active sheet: {ws.title}")
    except Exception as e:
        print(f"Error loading Excel file: {e}")
        return

    rows = list(ws.iter_rows())
    if not rows:
        print("Error: Excel file is empty.")
        return

    header_row = rows[0]
    col_map = map_headers(header_row)
    
    # Check if critical column 'CN' is mapped
    if 'cn' not in col_map:
        print("Warning: Could not identify 'CN' (Primary Key) column in Excel headers.")
        print("A unique dummy CN (e.g. DMY-2, DMY-3) will be automatically generated for each row.")

    print("\nDetected Column Mappings:")
    for field, idx in col_map.items():
        print(f"  - Database field '{field}' -> Excel Column '{header_row[idx].value}' (index {idx})")
    print("")

    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = 0

    with app.app_context():
        for row_idx, row in enumerate(rows[1:], start=2):
            cn_val = None
            if 'cn' in col_map:
                cn_cell = row[col_map['cn']]
                if cn_cell.value is not None:
                    cn_val = str(cn_cell.value).strip().upper().replace(" ", "")

            if not cn_val:
                # If CN is empty, see if the whole row is empty
                is_empty_row = all(cell.value is None for cell in row)
                if is_empty_row:
                    continue
                
                # Generate a unique dummy CN
                dummy_base = f"DMY-{row_idx}"
                cn_val = dummy_base
                counter = 1
                while db.session.query(DataEntry).filter_by(cn=cn_val).first() is not None:
                    cn_val = f"DMY-{row_idx}-{counter}"
                    counter += 1
                print(f"Row {row_idx}: Generated dummy CN '{cn_val}' because CN column was empty/missing.")

            try:
                # Extract values from columns with defaults
                def get_val(field, default="-"):
                    if field in col_map:
                        cell_val = row[col_map[field]].value
                        if cell_val is None:
                            return "-"
                        val_str = str(cell_val).strip()
                        if val_str.lower() in ['x', '-', 'none', 'null', '']:
                            return "-"
                        return val_str
                    return default

                def get_date_val(field):
                    if field in col_map:
                        return parse_date_value(row[col_map[field]].value)
                    return None

                # Extract and logic for specific fields
                pt_val = get_val('pt', '-').upper()
                pulau_val = get_val('pulau', '-').upper()
                provinsi_val = get_val('provinsi', '-').upper()
                
                # Varian, kategori, eqp_model, SNs
                no_polisi_val = get_val('no_polisi', '-')
                if no_polisi_val and no_polisi_val != '-':
                    no_polisi_val = no_polisi_val.upper().replace(" ", "")
                
                varian_val = get_val('varian', '-').upper()
                kategori_val = get_val('kategori', '-').upper()
                eqp_model_val = get_val('eqp_model', '-').upper()
                sn_equipment_val = get_val('sn_equipment', '-')
                sn_engine_val = get_val('sn_engine', '-')
                
                year_val = parse_year(row[col_map['year']].value) if 'year' in col_map else 0
                status_stnk_val = parse_status(row[col_map['status_stnk']].value) if 'status_stnk' in col_map else 'OFF'
                status_asuransi_val = parse_status(row[col_map['status_asuransi']].value) if 'status_asuransi' in col_map else 'OFF'
                
                remaks_val = get_val('remaks', None)
                keterangan_stnk = get_val('keterangan_stnk', None)
                if keterangan_stnk and keterangan_stnk.lower() not in ['-', 'none', 'null', '']:
                    if remaks_val and remaks_val.lower() not in ['-', 'none', 'null', '']:
                        remaks_val = f"{remaks_val} | STNK: {keterangan_stnk}"
                    else:
                        remaks_val = f"STNK: {keterangan_stnk}"
                
                notes_val = get_val('notes', None)

                # Prioritize 2026 for Asuransi Name & Polis Number, fallback to 2025
                nama_asuransi_val = get_val('nama_2026', None)
                if not nama_asuransi_val or nama_asuransi_val == '-':
                    nama_asuransi_val = get_val('nama_2025', '-')
                nama_asuransi_val = nama_asuransi_val.upper()

                no_polis_val = get_val('no_polis_2026', None)
                if not no_polis_val or no_polis_val == '-':
                    no_polis_val = get_val('no_polis_2025', '-')
                no_polis_val = no_polis_val.upper()

                # Parse dates
                tanggal_berakhir_asuransi_val = get_date_val('akhir_2026')
                if not tanggal_berakhir_asuransi_val:
                    tanggal_berakhir_asuransi_val = get_date_val('akhir_2025')
                
                tanggal_berakhir_stnk_val = get_date_val('tanggal_berakhir_stnk')

                # Auto change status to ON if date is in the future, otherwise OFF
                today_str = date.today().strftime('%Y-%m-%d')
                if tanggal_berakhir_stnk_val and tanggal_berakhir_stnk_val > today_str:
                    status_stnk_val = "ON"
                else:
                    status_stnk_val = "OFF"

                if tanggal_berakhir_asuransi_val and tanggal_berakhir_asuransi_val > today_str:
                    status_asuransi_val = "ON"
                else:
                    status_asuransi_val = "OFF"

                # Ensure unique CN to allow insert and avoid unique constraint error
                orig_cn = cn_val
                counter = 1
                while db.session.query(DataEntry).filter_by(cn=cn_val).first() is not None:
                    cn_val = f"{orig_cn}-{counter}"
                    counter += 1

                # Insert new record
                new_record = DataEntry(
                    pt=pt_val,
                    nama_asuransi=nama_asuransi_val,
                    pulau=pulau_val,
                    provinsi=provinsi_val,
                    cn=cn_val,
                    no_polis=no_polis_val,
                    no_polisi=no_polisi_val,
                    varian=varian_val,
                    kategori=kategori_val,
                    eqp_model=eqp_model_val,
                    sn_equipment=sn_equipment_val,
                    sn_engine=sn_engine_val,
                    status_stnk=status_stnk_val,
                    status_asuransi=status_asuransi_val,
                    tanggal_berakhir_stnk=tanggal_berakhir_stnk_val,
                    tanggal_berakhir_asuransi=tanggal_berakhir_asuransi_val,
                    year=year_val,
                    remaks=remaks_val,
                    notes=notes_val,
                    # Set default values for finance columns to be safe
                    biaya_perpanjang_stnk=0.0,
                    biaya_administrasi_stnk=0.0,
                    biaya_perpanjang_asuransi=0.0,
                    biaya_administrasi_asuransi=0.0,
                    pembulatan_stnk=0.0,
                    pembulatan_asuransi=0.0,
                    total_stnk=0.0,
                    total_asuransi=0.0,
                    harus_dibayar_stnk=0.0,
                    harus_dibayar_asuransi=0.0,
                    tanggal_input=date.today().strftime('%Y-%m-%d'),
                    diinput_oleh="Excel Import"
                )
                db.session.add(new_record)
                
                log_add = AuditLog(
                    cn=cn_val,
                    aksi="TAMBAH",
                    kolom_diubah="Semua Kolom (Unit Baru via Excel)",
                    nilai_lama="-",
                    nilai_baru=f"CN={cn_val}, PT={pt_val}, No Polis={no_polis_val}",
                    diubah_oleh="Excel Import",
                    tanggal_aksi=datetime.now()
                )
                db.session.add(log_add)
                inserted_count += 1

            except Exception as e:
                print(f"Row {row_idx} (CN={cn_val if 'cn_val' in locals() else 'Unknown'}): Error processing row - {e}")
                db.session.rollback()
                error_count += 1
                continue

        try:
            db.session.commit()
            print("Import completed successfully!")
            print(f"Summary:")
            print(f"  - Total processed: {inserted_count + updated_count + skipped_count + error_count}")
            print(f"  - Inserted (new records): {inserted_count}")
            print(f"  - Updated (existing records): {updated_count}")
            print(f"  - Skipped: {skipped_count}")
            print(f"  - Errors: {error_count}")
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Database transaction error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Check if there is a default file
        default_file = "data.xlsx"
        if os.path.exists(default_file):
            print(f"No file path specified. Using default file: {default_file}")
            import_excel(default_file)
        else:
            print("Usage: venv\\Scripts\\python import_excel.py <path_to_excel_file>")
            print("Or place 'data.xlsx' in the root directory and run: venv\\Scripts\\python import_excel.py")
    else:
        file_path = sys.argv[1]
        if not os.path.exists(file_path):
            print(f"Error: File '{file_path}' does not exist.")
        else:
            import_excel(file_path)
