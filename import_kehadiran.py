import os
import sys
import pandas as pd
from datetime import datetime, time, date

# Add current folder to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app, db, KaryawanEntry, Kehadiran

MONTH_MAPPING = {
    1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
    5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
    9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
}

def import_kehadiran_excel(filepath):
    # Verify file existence
    if not os.path.exists(filepath):
        print(f"❌ Galat: Berkas '{filepath}' tidak ditemukan.")
        return
        
    ext = filepath.split('.')[-1].lower()
    if ext not in ('xlsx', 'xls'):
        print("❌ Galat: Format berkas tidak didukung! Harus .xlsx atau .xls.")
        return
        
    print(f"🔄 Membaca berkas Excel: {filepath}...")
    try:
        engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
        df = pd.read_excel(filepath, engine=engine)
    except Exception as e:
        print(f"❌ Galat saat membaca Excel: {str(e)}")
        return
        
    # Normalize headers
    normalized_cols = {}
    for col in df.columns:
        norm = str(col).strip().lower().replace('_', ' ')
        norm = ' '.join(norm.split())
        normalized_cols[norm] = col
        
    col_nik = normalized_cols.get('nik')
    col_tanggal = normalized_cols.get('tanggal')
    col_masuk = normalized_cols.get('scan masuk')
    col_pulang = normalized_cols.get('scan pulang')
    
    # Validation
    missing = []
    if not col_nik: missing.append("nik")
    if not col_tanggal: missing.append("tanggal")
    if not col_masuk: missing.append("scan masuk")
    if not col_pulang: missing.append("scan pulang")
    
    if missing:
        print(f"❌ Galat: Berkas Excel kekurangan kolom wajib: {', '.join(missing)}")
        return
        
    print("🚀 Memulai proses impor data kehadiran...")
    
    # Auto-detect dominant month and date format from the column
    sample_dates = df[col_tanggal].dropna().tolist()
    first_parts = []
    second_parts = []
    parsed_months = []
    
    for d in sample_dates:
        if isinstance(d, (datetime, pd.Timestamp)):
            parsed_months.append(d.month)
            # Use string parsing parts
            d_str = d.strftime('%d/%m/%Y')
            parts = d_str.split('/')
        else:
            d_str = str(d).strip().split()[0]
            parts = []
            if '/' in d_str:
                parts = d_str.split('/')
            elif '-' in d_str:
                parts = d_str.split('-')
        if len(parts) >= 2:
            try:
                first_parts.append(int(parts[0]))
                second_parts.append(int(parts[1]))
            except ValueError:
                pass

    from collections import Counter
    all_months_candidates = []
    if parsed_months:
        all_months_candidates.extend(parsed_months)
    all_months_candidates.extend(first_parts)
    all_months_candidates.extend(second_parts)
    
    all_months_candidates = [x for x in all_months_candidates if 1 <= x <= 12]
    
    dominant_month = None
    if all_months_candidates:
        dominant_month = Counter(all_months_candidates).most_common(1)[0][0]
        
    is_month_first = True
    if dominant_month:
        first_count = first_parts.count(dominant_month)
        second_count = second_parts.count(dominant_month)
        if first_count > second_count:
            is_month_first = True
        elif second_count > first_count:
            is_month_first = False
        else:
            if any(x > 12 for x in first_parts):
                is_month_first = False
            elif any(x > 12 for x in second_parts):
                is_month_first = True

    if is_month_first:
        date_formats = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%d-%m-%Y")
    else:
        date_formats = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%m-%d-%Y")
        
    print(f"ℹ️ Deteksi Format Tanggal: Dominant Month = {dominant_month}, Month First = {is_month_first}")
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    with app.app_context():
        # Dictionary to cache database entry states and prevent redundant SELECT queries
        # key: (nik, bulan, tahun) -> Kehadiran object
        kehadiran_cache = {}

        # First pass to pre-load all KaryawanEntry to memory for quick check
        all_k = db.session.execute(db.select(KaryawanEntry)).scalars().all()
        karyawan_map = {k.nik: k for k in all_k}

        for idx, row in df.iterrows():
            try:
                # 1. NIK
                val_nik = str(row[col_nik]).strip().upper()
                if not val_nik or pd.isna(row[col_nik]) or val_nik in ('', 'NAT', 'NAN', 'NONE', '-'):
                    print(f"⚠️ Baris {idx+2}: NIK kosong atau tidak valid, dilewati.")
                    skip_count += 1
                    continue
                
                # Verify employee is registered
                if val_nik not in karyawan_map:
                    print(f"⚠️ Baris {idx+2}: NIK '{val_nik}' tidak terdaftar di database, dilewati.")
                    skip_count += 1
                    continue
                    
                karyawan = karyawan_map[val_nik]

                # 2. Tanggal
                raw_tanggal = row[col_tanggal]
                if pd.isna(raw_tanggal) or str(raw_tanggal).strip() in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                    print(f"⚠️ Baris {idx+2}: Kolom tanggal kosong atau tidak valid, dilewati.")
                    skip_count += 1
                    continue
                
                # Parse date
                ts = None
                if isinstance(raw_tanggal, (datetime, pd.Timestamp)):
                    # Check if pandas incorrectly swapped month/day
                    if dominant_month and raw_tanggal.month != dominant_month and raw_tanggal.day == dominant_month:
                        try:
                            ts = pd.Timestamp(year=raw_tanggal.year, month=raw_tanggal.day, day=raw_tanggal.month)
                        except ValueError:
                            ts = pd.Timestamp(raw_tanggal)
                    else:
                        ts = pd.Timestamp(raw_tanggal)
                else:
                    date_str = str(raw_tanggal).strip()
                    for fmt in date_formats:
                        try:
                            dt = datetime.strptime(date_str.split()[0], fmt)
                            ts = pd.Timestamp(dt)
                            break
                        except ValueError:
                            continue

                if ts is None or pd.isna(ts):
                    print(f"⚠️ Baris {idx+2}: Format tanggal '{raw_tanggal}' tidak valid, dilewati.")
                    skip_count += 1
                    continue

                # 3. Check TMK (Tanggal Mulai Kerja) constraint
                if karyawan.tmk:
                    tmk_date = None
                    for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
                        try:
                            tmk_date = datetime.strptime(karyawan.tmk.strip(), fmt).date()
                            break
                        except ValueError:
                            pass
                    if tmk_date and ts.date() < tmk_date:
                        print(f"⚠️ Baris {idx+2}: Tanggal log ({ts.strftime('%Y-%m-%d')}) sebelum TMK karyawan ({tmk_date.strftime('%Y-%m-%d')}), dilewati.")
                        skip_count += 1
                        continue

                # 4. Check Resign Date constraint
                if karyawan.tanggal_resign:
                    try:
                        dt_resign = datetime.strptime(karyawan.tanggal_resign, "%Y-%m-%d").date()
                        if ts.date() >= dt_resign:
                            print(f"⚠️ Baris {idx+2}: Karyawan ({val_nik}) sudah resign per {dt_resign.strftime('%Y-%m-%d')} (tanggal log: {ts.strftime('%Y-%m-%d')}), dilewati.")
                            skip_count += 1
                            continue
                    except ValueError:
                        pass

                day = str(ts.day)
                bulan_num = ts.month
                tahun = ts.year
                
                if bulan_num not in MONTH_MAPPING:
                    print(f"⚠️ Baris {idx+2}: Bulan '{bulan_num}' tidak valid, dilewati.")
                    skip_count += 1
                    continue
                bulan = MONTH_MAPPING[bulan_num]

                # 5. Parse scan times
                val_masuk = ''
                val_pulang = ''
                is_incomplete = False
                
                # Check scan masuk
                raw_masuk = row[col_masuk]
                if pd.isna(raw_masuk) or str(raw_masuk).strip() in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                    is_incomplete = True
                else:
                    val_masuk = str(raw_masuk).strip()
                    
                # Check scan pulang
                raw_pulang = row[col_pulang]
                if pd.isna(raw_pulang) or str(raw_pulang).strip() in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                    is_incomplete = True
                else:
                    val_pulang = str(raw_pulang).strip()

                status = 'P' if is_incomplete else 'M'
                if is_incomplete:
                    val_masuk = ''
                    val_pulang = ''

                # 6. Retrieve or create Kehadiran object
                cache_key = (val_nik, bulan, tahun)
                if cache_key in kehadiran_cache:
                    entry = kehadiran_cache[cache_key]
                else:
                    entry = db.session.execute(
                        db.select(Kehadiran).where(Kehadiran.nik == val_nik, Kehadiran.bulan == bulan, Kehadiran.tahun == tahun)
                    ).scalar_one_or_none()
                    
                    if not entry:
                        entry = Kehadiran(
                            nik=val_nik,
                            bulan=bulan,
                            tahun=tahun,
                            status_hari={},
                            scan_masuk_hari={},
                            scan_pulang_hari={}
                        )
                        db.session.add(entry)
                    kehadiran_cache[cache_key] = entry

                # Mutate dict fields
                status_dict = dict(entry.status_hari)
                scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
                scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}

                # Do not overwrite if currently marked Resign or a valid permission
                current_status = status_dict.get(day, '')
                if current_status == 'R':
                    pass
                elif current_status in ('S', 'C', 'CT', 'CN', 'CD', 'DL', 'L') and status in ('A', 'P'):
                    pass
                else:
                    status_dict[day] = status
                    entry.status_hari = status_dict
                    
                    if status == 'M':
                        scan_masuk_dict[day] = val_masuk
                        scan_pulang_dict[day] = val_pulang
                    else:
                        scan_masuk_dict[day] = ''
                        scan_pulang_dict[day] = ''
                        
                    entry.scan_masuk_hari = scan_masuk_dict
                    entry.scan_pulang_hari = scan_pulang_dict
                
                success_count += 1
                
            except Exception as e:
                print(f"❌ Baris {idx+2}: Gagal memproses data: {str(e)}")
                error_count += 1

        try:
            db.session.commit()
            print("\n🎉 Proses Impor Kehadiran Selesai!")
            print(f"   - Berhasil diproses/diimpor: {success_count} baris log")
            print(f"   - Dilewati/Duplikat/Tidak Valid: {skip_count}")
            print(f"   - Galat/Error: {error_count}")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Gagal menyimpan ke database (Rollback): {str(e)}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Penggunaan: python import_kehadiran.py <path_berkas_excel>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    import_kehadiran_excel(filepath)
