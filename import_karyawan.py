import os
import sys
import pandas as pd
from datetime import datetime, time

# Add current folder to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app, db, KaryawanEntry, Cuti

def import_karyawan_excel(filepath):
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
        
    col_absen = normalized_cols.get('absen')
    col_nama = normalized_cols.get('nama')
    col_nik = normalized_cols.get('nik')
    col_tmk = normalized_cols.get('tmk')
    col_masuk = normalized_cols.get('jam masuk')
    col_pulang = normalized_cols.get('jam pulang')
    
    # Validation
    missing = []
    if not col_absen: missing.append("absen")
    if not col_nama: missing.append("nama")
    if not col_nik: missing.append("nik")
    if not col_tmk: missing.append("tmk")
    if not col_masuk: missing.append("jam_masuk")
    if not col_pulang: missing.append("jam_pulang")
    
    if missing:
        print(f"❌ Galat: Berkas Excel kekurangan kolom wajib: {', '.join(missing)}")
        return
        
    print("🚀 Memulai proses impor data karyawan...")
    success_count = 0
    skip_count = 0
    error_count = 0
    
    with app.app_context():
        for idx, row in df.iterrows():
            try:
                # Absen
                val_absen = row[col_absen]
                if pd.isna(val_absen):
                    skip_count += 1
                    continue
                absen = int(val_absen)
                
                # NIK
                val_nik = str(row[col_nik]).strip().upper()
                if not val_nik or pd.isna(row[col_nik]):
                    skip_count += 1
                    continue
                
                # Nama
                val_nama = str(row[col_nama]).strip()
                if not val_nama or pd.isna(row[col_nama]):
                    skip_count += 1
                    continue
                
                # TMK
                val_tmk = row[col_tmk]
                if isinstance(val_tmk, datetime):
                    tmk_str = val_tmk.strftime("%Y-%m-%d")
                else:
                    tmk_str = str(val_tmk).strip()
                    parsed = False
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%m-%d-%Y"):
                        try:
                            dt = datetime.strptime(tmk_str.split()[0], fmt)
                            tmk_str = dt.strftime("%Y-%m-%d")
                            parsed = True
                            break
                        except ValueError:
                            continue
                    if not parsed:
                        print(f"⚠️ Baris {idx+2}: Format TMK '{tmk_str}' tidak valid, dilewati.")
                        skip_count += 1
                        continue
                        
                # Jam Masuk & Pulang
                def parse_time(val):
                    if isinstance(val, time):
                        return val
                    if isinstance(val, datetime):
                        return val.time()
                    t_str = str(val).strip()
                    for fmt in ("%H:%M:%S", "%H:%M"):
                        try:
                            return datetime.strptime(t_str, fmt).time()
                        except ValueError:
                            continue
                    return time(8, 0, 0)
                    
                jam_masuk = parse_time(row[col_masuk])
                jam_pulang = parse_time(row[col_pulang])
                
                # Cek duplikat NIK
                exists_nik = db.session.execute(
                    db.select(KaryawanEntry).where(KaryawanEntry.nik == val_nik)
                ).scalar_one_or_none()
                
                # Cek duplikat Absen
                exists_absen = db.session.execute(
                    db.select(KaryawanEntry).where(KaryawanEntry.absen == absen)
                ).scalar_one_or_none()
                
                if exists_nik or exists_absen:
                    print(f"⚠️ Baris {idx+2}: NIK '{val_nik}' atau Absen '{absen}' sudah digunakan, dilewati.")
                    skip_count += 1
                    continue
                    
                # Buat KaryawanEntry & Cuti
                new_k = KaryawanEntry(
                    nik=val_nik,
                    absen=absen,
                    nama=val_nama,
                    jabatan='STAFF', # Sesuai request
                    tmk=tmk_str,
                    jam_masuk=jam_masuk,
                    jam_pulang=jam_pulang
                )
                new_c = Cuti(
                    nik=val_nik,
                    cuti_tahunan=0,
                    cuti_dinas=0
                )
                
                db.session.add(new_k)
                db.session.add(new_c)
                success_count += 1
                
            except Exception as e:
                print(f"❌ Baris {idx+2}: Gagal memproses data: {str(e)}")
                error_count += 1
                
        try:
            db.session.commit()
            print("\n🎉 Proses Impor Selesai!")
            print(f"   - Berhasil diimpor: {success_count}")
            print(f"   - Dilewati/Duplikat: {skip_count}")
            print(f"   - Galat/Error: {error_count}")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Gagal menyimpan ke database (Rollback): {str(e)}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Penggunaan: python import_karyawan.py <path_berkas_excel>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    import_karyawan_excel(filepath)
