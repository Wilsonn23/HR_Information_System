import os
import sys
import pandas as pd
from datetime import datetime, time

# Add current folder to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app, db, KaryawanEntry, Cuti, Jabatan, SdmPT, SdmDivisi, SdmDepartemen

def import_karyawan_excel(filepath):
    # Verify file existence
    if not os.path.exists(filepath):
        print(f"Error: Berkas '{filepath}' tidak ditemukan.")
        return
        
    ext = filepath.split('.')[-1].lower()
    if ext not in ('xlsx', 'xls'):
        print("Error: Format berkas tidak didukung! Harus .xlsx atau .xls.")
        return
        
    print(f"Membaca berkas Excel: {filepath}...")
    try:
        engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
        df = pd.read_excel(filepath, engine=engine)
    except Exception as e:
        print(f"Error saat membaca Excel: {str(e)}")
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
    col_pt = normalized_cols.get('pt') or normalized_cols.get('perusahaan')
    col_staff = normalized_cols.get('staff') or normalized_cols.get('status') or normalized_cols.get('tipe')
    col_jabatan = normalized_cols.get('jabatan') or normalized_cols.get('posisi') or normalized_cols.get('position')
    col_divisi = (
        normalized_cols.get('divisi') or 
        normalized_cols.get('division') or 
        normalized_cols.get('div') or 
        normalized_cols.get('bagian') or 
        normalized_cols.get('seksi') or 
        normalized_cols.get('div.') or 
        normalized_cols.get('divisi / unit')
    )
    col_departemen = (
        normalized_cols.get('departemen') or 
        normalized_cols.get('dept') or 
        normalized_cols.get('department')
    )
    col_priority_level = (
        normalized_cols.get('priority level') or 
        normalized_cols.get('priority') or 
        normalized_cols.get('level priority') or 
        normalized_cols.get('prioritas') or 
        normalized_cols.get('prioritylevel') or 
        normalized_cols.get('level prioritas')
    )
    
    # Validation
    missing = []
    if not col_absen: missing.append("absen")
    if not col_nama: missing.append("nama")
    if not col_nik: missing.append("nik")
    if not col_tmk: missing.append("tmk")
    if not col_masuk: missing.append("jam_masuk")
    if not col_pulang: missing.append("jam_pulang")
    
    if missing:
        print(f"Error: Berkas Excel kekurangan kolom wajib: {', '.join(missing)}")
        return
        
    print("Memulai proses impor data karyawan...")
    success_count = 0
    updated_count = 0
    skip_count = 0
    error_count = 0
    new_dept_count = 0
    new_pt_count = 0
    new_divisi_count = 0
    new_jabatan_count = 0
    
    with app.app_context():
        existing_karyawans = {k.nik: k for k in db.session.execute(db.select(KaryawanEntry)).scalars().all()}
        existing_absens_map = {k.absen: k.nik for k in existing_karyawans.values()}
        existing_jabatans = {j.strip().lower() for j in db.session.execute(db.select(Jabatan.nama)).scalars().all() if j}
        existing_pts = {p.strip().upper() for p in db.session.execute(db.select(SdmPT.nama)).scalars().all() if p}
        existing_divisis = {d.strip().upper() for d in db.session.execute(db.select(SdmDivisi.nama)).scalars().all() if d}
        existing_departemens = {dept.strip().upper() for dept in db.session.execute(db.select(SdmDepartemen.nama)).scalars().all() if dept}
        
        for idx, row in df.iterrows():
            try:
                # Absen
                val_absen = row[col_absen]
                if pd.isna(val_absen):
                    skip_count += 1
                    continue
                try:
                    absen = int(float(val_absen))
                except (ValueError, TypeError):
                    print(f"Warning: Baris {idx+2}: Nilai absen '{val_absen}' tidak valid (harus angka), dilewati.")
                    skip_count += 1
                    continue
                
                # NIK
                val_nik = str(row[col_nik]).strip().upper()
                if not val_nik or pd.isna(row[col_nik]) or val_nik in ('NAN', 'NONE', 'NAT', '-'):
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
                        print(f"Warning: Baris {idx+2}: Format TMK '{tmk_str}' tidak valid, dilewati.")
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
                
                val_pt = str(row[col_pt]).strip() if col_pt and not pd.isna(row[col_pt]) else val_nik[:3]
                val_pt_upper = val_pt.upper()
                
                # Daftarkan PT ke master sdm_pt jika belum ada
                if val_pt_upper and val_pt_upper not in existing_pts:
                    new_pt = SdmPT(
                        nama=val_pt_upper,
                        dilakukan_oleh='excel_import'
                    )
                    db.session.add(new_pt)
                    existing_pts.add(val_pt_upper)
                    new_pt_count += 1
                    
                val_jabatan = str(row[col_jabatan]).strip() if col_jabatan and not pd.isna(row[col_jabatan]) else 'STAFF'
                
                # Daftarkan ke master jabatan jika belum ada
                val_jabatan_lower = val_jabatan.lower()
                if val_jabatan and val_jabatan_lower not in existing_jabatans:
                    new_j = Jabatan(
                        nama=val_jabatan,
                        dilakukan_oleh='excel_import'
                    )
                    db.session.add(new_j)
                    existing_jabatans.add(val_jabatan_lower)
                    new_jabatan_count += 1
                
                # Deteksi status staff/non-staff
                if col_staff and not pd.isna(row[col_staff]):
                    s_lower = str(row[col_staff]).strip().lower()
                    if 'non' in s_lower:
                        val_staff = 'Non-Staff'
                    else:
                        val_staff = 'Staff'
                else:
                    val_staff = 'Staff'

                # Divisi
                val_divisi = str(row[col_divisi]).strip() if col_divisi and not pd.isna(row[col_divisi]) else ""
                if val_divisi.lower() in ('nan', 'none', 'null', '-', ''):
                    val_divisi = ""

                # Departemen
                val_departemen = str(row[col_departemen]).strip() if col_departemen and not pd.isna(row[col_departemen]) else ""
                if val_departemen.lower() in ('nan', 'none', 'null', '-', ''):
                    val_departemen = ""
                
                # Auto register divisi ke master divisi (SdmDivisi)
                if val_divisi:
                    val_divisi_upper = val_divisi.upper()
                    if val_divisi_upper not in existing_divisis:
                        new_div = SdmDivisi(
                            nama=val_divisi,
                            dilakukan_oleh='excel_import'
                        )
                        db.session.add(new_div)
                        existing_divisis.add(val_divisi_upper)
                        new_divisi_count += 1

                # Auto register departemen ke master departemen (SdmDepartemen)
                if val_departemen:
                    val_departemen_upper = val_departemen.upper()
                    if val_departemen_upper not in existing_departemens:
                        new_dept = SdmDepartemen(
                            nama=val_departemen,
                            dilakukan_oleh='excel_import'
                        )
                        db.session.add(new_dept)
                        existing_departemens.add(val_departemen_upper)
                        new_dept_count += 1
                    
                # Parsing priority level (angka)
                val_priority = None
                if col_priority_level and not pd.isna(row[col_priority_level]):
                    try:
                        raw_priority = row[col_priority_level]
                        if isinstance(raw_priority, str):
                            raw_priority = raw_priority.strip()
                        val_priority = int(float(raw_priority))
                    except (ValueError, TypeError):
                        val_priority = None
                    
                # Jika NIK sudah ada di database -> Perbarui data (Upsert)
                if val_nik in existing_karyawans:
                    k = existing_karyawans[val_nik]
                    # Cek konflik nomor absen dengan karyawan lain
                    if absen != k.absen and absen in existing_absens_map and existing_absens_map[absen] != val_nik:
                        print(f"Warning: Baris {idx+2}: Nomor Absen '{absen}' sudah digunakan oleh NIK lain ({existing_absens_map[absen]}), nomor absen tidak diubah.")
                    else:
                        existing_absens_map.pop(k.absen, None)
                        k.absen = absen
                        existing_absens_map[absen] = val_nik
                        
                    k.nama = val_nama
                    k.jabatan = val_jabatan
                    k.tmk = tmk_str
                    k.jam_masuk = jam_masuk
                    k.jam_pulang = jam_pulang
                    k.pt = val_pt_upper
                    k.staff = val_staff
                    if val_divisi:
                        k.divisi = val_divisi
                    if val_departemen:
                        k.departemen = val_departemen
                    if val_priority is not None:
                        k.priority_level = val_priority
                        
                    # Pastikan baris cuti tersedia
                    if not db.session.get(Cuti, val_nik):
                        db.session.add(Cuti(nik=val_nik, cuti_tahunan=0, cuti_dinas=0))
                        
                    updated_count += 1
                else:
                    # Karyawan baru -> Cek konflik nomor absen
                    if absen in existing_absens_map:
                        print(f"Warning: Baris {idx+2}: Nomor Absen '{absen}' sudah digunakan oleh NIK '{existing_absens_map[absen]}', dilewati.")
                        skip_count += 1
                        continue
                        
                    new_k = KaryawanEntry(
                        nik=val_nik,
                        absen=absen,
                        nama=val_nama,
                        jabatan=val_jabatan,
                        tmk=tmk_str,
                        jam_masuk=jam_masuk,
                        jam_pulang=jam_pulang,
                        pt=val_pt_upper,
                        staff=val_staff,
                        divisi=val_divisi if val_divisi else None,
                        departemen=val_departemen if val_departemen else None,
                        priority_level=val_priority,
                        dilakukan_oleh='excel_import'
                    )
                    new_c = Cuti(
                        nik=val_nik,
                        cuti_tahunan=0,
                        cuti_dinas=0
                    )
                    
                    db.session.add(new_k)
                    db.session.add(new_c)
                    existing_karyawans[val_nik] = new_k
                    existing_absens_map[absen] = val_nik
                    success_count += 1
                
            except Exception as e:
                print(f"Error: Baris {idx+2}: Gagal memproses data: {str(e)}")
                error_count += 1
                
        try:
            db.session.commit()
            print("\nProses Impor Selesai!")
            print(f"   - Berhasil diimpor (Baru): {success_count} karyawan")
            if updated_count > 0:
                print(f"   - Berhasil diperbarui (Update Data): {updated_count} karyawan")
            if new_divisi_count > 0:
                print(f"   - Master Divisi baru ditambahkan: {new_divisi_count}")
            if new_dept_count > 0:
                print(f"   - Master Departemen baru ditambahkan: {new_dept_count}")
            if new_pt_count > 0:
                print(f"   - Master PT baru ditambahkan: {new_pt_count}")
            if new_jabatan_count > 0:
                print(f"   - Master Jabatan baru ditambahkan: {new_jabatan_count}")
            print(f"   - Dilewati/Duplikat: {skip_count}")
            print(f"   - Galat/Error: {error_count}")
        except Exception as e:
            db.session.rollback()
            print(f"Error: Gagal menyimpan ke database (Rollback): {str(e)}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Penggunaan: python import_karyawan.py <path_berkas_excel>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    import_karyawan_excel(filepath)
