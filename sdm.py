# ===============================================================================================================
# SDM (HUMAN RESOURCES) MODULE
# ===============================================================================================================

from flask import render_template, request, redirect, url_for, flash, session, jsonify
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional, Length
from werkzeug.security import generate_password_hash

from app import app, db, UserEntry, KaryawanEntry, Bulan, Kehadiran, Cuti, HariLibur

@app.template_filter('is_late_scan')
def is_late_scan(time_str):
    if not time_str:
        return False
    time_str = str(time_str).strip()
    if time_str.lower() in ('nat', 'nan', 'none', '-', ''):
        return False
    try:
        parts = time_str.split(':')
        if len(parts) >= 2:
            hour = int(parts[0])
            minute = int(parts[1])
            if hour > 8 or (hour == 8 and minute > 30):
                return True
    except Exception:
        pass
    return False

@app.template_filter('is_early_checkout')
def is_early_checkout(pulang_scan_str, scheduled_pulang_time):
    if not pulang_scan_str or not scheduled_pulang_time:
        return False
    pulang_scan_str = str(pulang_scan_str).strip()
    if pulang_scan_str.lower() in ('nat', 'nan', 'none', '-', ''):
        return False
    try:
        parts = pulang_scan_str.split(':')
        if len(parts) >= 2:
            scan_hour = int(parts[0])
            scan_minute = int(parts[1])
            
            scan_minutes = scan_hour * 60 + scan_minute
            scheduled_minutes = scheduled_pulang_time.hour * 60 + scheduled_pulang_time.minute
            
            if scan_minutes < scheduled_minutes:
                return True
    except Exception:
        pass
    return False

class UserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=50)])
    password = StringField('Password (Isi jika ingin diubah)', validators=[Optional(), Length(min=6)])
    role = SelectField('Role', choices=[('user', 'Staff Operasional'), ('hr', 'Staff SDM'), ('admin', 'Administrator')], validators=[DataRequired()])
    submit = SubmitField('Simpan Pengguna')

@app.route('/sdm-dashboard')
def sdm_dashboard():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    # Fetch all kehadiran records to look for Pending ('P') statuses
    all_kehadiran = db.session.execute(db.select(Kehadiran)).scalars().all()
    
    # Ambil list bulan & metadata
    bulan_list = db.session.execute(db.select(Bulan)).scalars().all()
    bulan_days_map = {b.nama: b.jumlah_hari for b in bulan_list}
    
    # Ambil semua hari libur
    all_holidays = db.session.execute(db.select(HariLibur)).scalars().all()

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    
    import datetime
    
    reminders = []
    for k in all_kehadiran:
        selected_bulan = k.bulan
        selected_tahun = k.tahun
        
        jumlah_hari = bulan_days_map.get(selected_bulan, 31)
        if selected_bulan == 'Februari':
            if (selected_tahun % 4 == 0 and selected_tahun % 100 != 0) or (selected_tahun % 400 == 0):
                jumlah_hari = 29
            else:
                jumlah_hari = 28
                
        month_num = MONTH_NUMBERS.get(selected_bulan, 1)

        # Cek jika karyawan sudah resign sebelum bulan ini
        if k.karyawan and k.karyawan.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.karyawan.tanggal_resign, "%Y-%m-%d")
                if selected_tahun > dt_resign.year:
                    continue
                if selected_tahun == dt_resign.year and month_num > dt_resign.month:
                    continue
            except ValueError:
                pass
        
        # Hitung weekends
        weekends = set()
        for d in range(1, jumlah_hari + 1):
            try:
                dt = datetime.date(selected_tahun, month_num, d)
                if dt.weekday() in (5, 6):  # Saturday, Sunday
                    weekends.add(d)
            except ValueError:
                pass
                
        # Hitung holidays
        holidays = set()
        for h in all_holidays:
            if h.tanggal.month == month_num and h.tanggal.year == selected_tahun:
                holidays.add(h.tanggal.day)
                
        pending_days = []
        for d in range(1, jumlah_hari + 1):
            # Jika karyawan resign di bulan ini, lewati pengecekan untuk hari >= tanggal resign
            if k.karyawan and k.karyawan.tanggal_resign:
                try:
                    dt_resign = datetime.datetime.strptime(k.karyawan.tanggal_resign, "%Y-%m-%d")
                    if selected_tahun == dt_resign.year and month_num == dt_resign.month and d >= dt_resign.day:
                        continue
                except ValueError:
                    pass

            day_str = str(d)
            db_status = k.status_hari.get(day_str, '')
            
            # Jangan masukkan hari libur/weekend ke pending (kecuali masuk 'M')
            if (d in weekends or d in holidays) and db_status != 'M':
                continue
                
            if db_status == 'P' or db_status == '':
                pending_days.append(d)
                
        if pending_days:
            pending_days.sort()
            reminders.append({
                'nik': k.nik,
                'absen': k.karyawan.absen if k.karyawan else None,
                'nama': k.nama,
                'bulan': k.bulan,
                'tahun': k.tahun,
                'hari': pending_days
            })
            
    # Sort reminders by employee name
    reminders.sort(key=lambda x: x['absen'])

    # Fetch all cuti entries
    cuti_list = db.session.execute(db.select(Cuti)).scalars().all()

    return render_template(
        'sdm/sdm_dashboard.html', 
        reminders=reminders, 
        cuti_list=cuti_list,
        active_page='sdm-dashboard'
    )

@app.route('/sdm-transaksi')
def sdm_transaksi():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    return render_template('sdm/sdm_transaksi.html', active_page='sdm-transaksi')

@app.route('/master-sdm')
def master_sdm():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    return render_template('sdm/master_landing.html', active_page='master-sdm')

@app.route('/master-karyawan')
def master_karyawan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    entries=db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()
    return render_template('sdm/master_karyawan.html', entries=entries, active_page='master-sdm')

@app.route('/upload-karyawan', methods=['POST'])
def upload_karyawan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    import pandas as pd
    
    file = request.files.get('file')
    if not file or file.filename == '':
        flash("⚠️ Silakan pilih berkas Excel terlebih dahulu!", "danger")
        return redirect(url_for('master_karyawan'))
        
    ext = file.filename.split('.')[-1].lower()
    if ext not in ('xlsx', 'xls'):
        flash("⚠️ Format berkas tidak didukung! Pastikan berkas Anda bertipe .xlsx atau .xls", "danger")
        return redirect(url_for('master_karyawan'))
        
    try:
        engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
        df = pd.read_excel(file, engine=engine)
        
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
        
        # Validation of required columns
        missing = []
        if not col_absen: missing.append("absen")
        if not col_nama: missing.append("nama")
        if not col_nik: missing.append("nik")
        if not col_tmk: missing.append("tmk")
        if not col_masuk: missing.append("jam_masuk")
        if not col_pulang: missing.append("jam_pulang")
        
        if missing:
            flash(f"⚠️ Berkas Excel kekurangan kolom wajib: {', '.join(missing)}", "danger")
            return redirect(url_for('master_karyawan'))
            
        success_count = 0
        skip_count = 0
        error_count = 0
        
        from datetime import datetime, time
        
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
                    # Coba parse berbagai format tanggal
                    parsed = False
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
                        try:
                            dt = datetime.strptime(tmk_str.split()[0], fmt)
                            tmk_str = dt.strftime("%Y-%m-%d")
                            parsed = True
                            break
                        except ValueError:
                            continue
                    if not parsed:
                        skip_count += 1
                        continue
                            
                # Jam Masuk & Pulang
                def parse_time(val):
                    if isinstance(val, time):
                        return val
                    if isinstance(val, datetime):
                        return val.time()
                    # String
                    t_str = str(val).strip()
                    for fmt in ("%H:%M:%S", "%H:%M"):
                        try:
                            return datetime.strptime(t_str, fmt).time()
                        except ValueError:
                            continue
                    return time(8, 0, 0) # default fallback
                    
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
                    skip_count += 1
                    continue
                    
                # Buat KaryawanEntry & Cuti
                new_k = KaryawanEntry(
                    nik=val_nik,
                    absen=absen,
                    nama=val_nama,
                    jabatan='STAFF', # Sesuai request: "jabatan buat staff semua saja"
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
                print(f"Error parsing row {idx}: {str(e)}")
                error_count += 1
                
        db.session.commit()
        flash(f"✅ Berhasil mengimpor {success_count} karyawan. (Dilewati/Duplikat: {skip_count}, Galat: {error_count})", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Terjadi kesalahan saat memproses berkas Excel: {str(e)}", "danger")
        
    return redirect(url_for('master_karyawan'))

@app.route('/nonaktifkan-karyawan', methods=['GET', 'POST'])
def nonaktifkan_karyawan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nik = request.form.get('nik', '').strip().upper()
        tanggal_resign_str = request.form.get('tanggal_resign', '').strip()
        
        if not (nik and tanggal_resign_str):
            flash("⚠️ Semua kolom wajib diisi!", "danger")
            return redirect(url_for('nonaktifkan_karyawan'))
            
        karyawan = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
        ).scalar_one_or_none()
        
        if not karyawan:
            flash("⚠️ Karyawan tidak ditemukan!", "danger")
            return redirect(url_for('nonaktifkan_karyawan'))
            
        try:
            from datetime import datetime
            import calendar
            
            dt_resign = datetime.strptime(tanggal_resign_str, "%Y-%m-%d")
            year = dt_resign.year
            month_num = dt_resign.month
            day_resign = dt_resign.day
            
            MONTH_MAPPING = {
                1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
                5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
                9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
            }
            bulan_name = MONTH_MAPPING.get(month_num)
            
            # Set tanggal resign di KaryawanEntry
            karyawan.tanggal_resign = tanggal_resign_str
            
            # Cari hari terakhir bulan resign
            _, last_day = calendar.monthrange(year, month_num)
            
            # Update/create Kehadiran untuk bulan resign
            entry = db.session.execute(
                db.select(Kehadiran).where(
                    Kehadiran.nik == nik,
                    Kehadiran.bulan == bulan_name,
                    Kehadiran.tahun == year
                )
            ).scalar_one_or_none()
            
            if not entry:
                entry = Kehadiran(
                    nik=nik,
                    bulan=bulan_name,
                    tahun=year,
                    status_hari={},
                    scan_masuk_hari={},
                    scan_pulang_hari={}
                )
                db.session.add(entry)
                
            status_dict = dict(entry.status_hari)
            scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
            scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}
            
            for d in range(day_resign, last_day + 1):
                day_str = str(d)
                status_dict[day_str] = 'R'
                scan_masuk_dict[day_str] = ''
                scan_pulang_dict[day_str] = ''
                
            entry.status_hari = status_dict
            entry.scan_masuk_hari = scan_masuk_dict
            entry.scan_pulang_hari = scan_pulang_dict
            
            db.session.commit()
            flash(f"✅ Karyawan '{karyawan.nama}' (NIK: {nik}) berhasil dinonaktifkan sebagai Resign per {tanggal_resign_str}!", "success")
            return redirect(url_for('master_karyawan'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"⚠️ Terjadi kesalahan: {str(e)}", "danger")
            return redirect(url_for('nonaktifkan_karyawan'))
            
    # GET
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).where(
            (KaryawanEntry.tanggal_resign == None) | (KaryawanEntry.tanggal_resign == '')
        ).order_by(KaryawanEntry.absen)
    ).scalars().all()
    
    return render_template('sdm/nonaktifkan_karyawan.html', karyawan_list=karyawan_list, active_page='sdm-transaksi')

@app.route('/master-cuti')
def master_cuti():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()
    
    existing_cuti = db.session.execute(
        db.select(Cuti)
    ).scalars().all()
    
    cuti_map = {c.nik: c for c in existing_cuti}
    entries = []
    for k in karyawan_list:
        if k.nik in cuti_map:
            entries.append(cuti_map[k.nik])
        else:
            temp_cuti = Cuti(
                nik=k.nik,
                cuti_tahunan=0.0,
                cuti_normatif=0.0,
                cuti_dinas=0.0
            )
            temp_cuti.karyawan = k
            entries.append(temp_cuti)
            
    return render_template('sdm/master_cuti.html', entries=entries, active_page='master-sdm')



@app.route('/master-bulan')
def master_bulan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    entries=db.session.execute(
        db.select(Bulan)
    ).scalars().all()
    return render_template('sdm/master_bulan.html', entries=entries, active_page='master-sdm')

@app.route('/master-kehadiran')
def master_kehadiran():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    
    selected_bulan = request.args.get('bulan', 'Januari').strip()
    selected_tahun = request.args.get('tahun', '2026').strip()
    
    try:
        selected_tahun = int(selected_tahun)
    except ValueError:
        selected_tahun = 2026

    bulan_meta = db.session.execute(db.select(Bulan).where(Bulan.nama == selected_bulan)).scalar_one_or_none()
    jumlah_hari = bulan_meta.jumlah_hari if bulan_meta else 31
    if selected_bulan == 'Februari':
        if (selected_tahun % 4 == 0 and selected_tahun % 100 != 0) or (selected_tahun % 400 == 0):
            jumlah_hari = 29
        else:
            jumlah_hari = 28

    # Ambil semua data karyawan terdaftar, diurutkan berdasarkan nomor absen
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    view_month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    import datetime
    filtered_karyawan_list = []
    for k in karyawan_list:
        if k.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.tanggal_resign, "%Y-%m-%d")
                if selected_tahun > dt_resign.year:
                    continue
                if selected_tahun == dt_resign.year and view_month_num > dt_resign.month:
                    continue
            except ValueError:
                pass
        filtered_karyawan_list.append(k)

    # Ambil data kehadiran dari DB yang sudah ada untuk periode terpilih
    existing_entries = db.session.execute(
        db.select(Kehadiran)
        .where(Kehadiran.bulan == selected_bulan, Kehadiran.tahun == selected_tahun)
    ).scalars().all()

    # Buat mapping NIK ke entri Kehadiran yang ada
    kehadiran_map = {e.nik: e for e in existing_entries}

    # Gabungkan data: jika karyawan belum ada di DB, buat entri transient kosong di memori
    final_entries = []
    for k in filtered_karyawan_list:
        if k.nik in kehadiran_map:
            final_entries.append(kehadiran_map[k.nik])
        else:
            temp_entry = Kehadiran(
                nik=k.nik,
                bulan=selected_bulan,
                tahun=selected_tahun,
                status_hari={},
                scan_masuk_hari={},
                scan_pulang_hari={}
            )
            temp_entry.karyawan = k
            final_entries.append(temp_entry)

    # List bulan untuk filter dropdown
    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()

    # Hitung hari sabtu & minggu (weekends) untuk bulan & tahun terpilih
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    month_num = MONTH_NUMBERS.get(selected_bulan, 1)
    
    import datetime
    weekends = []
    for d in range(1, jumlah_hari + 1):
        try:
            dt = datetime.date(selected_tahun, month_num, d)
            if dt.weekday() in (5, 6):  # 5 = Sabtu, 6 = Minggu
                weekends.append(d)
        except ValueError:
            pass

    # Ambil hari libur untuk bulan & tahun terpilih
    all_holidays = db.session.execute(
        db.select(HariLibur)
    ).scalars().all()
    
    holiday_days = {}
    for h in all_holidays:
        if h.tanggal.month == month_num and h.tanggal.year == selected_tahun:
            holiday_days[h.tanggal.day] = h.keterangan

    current_year = datetime.datetime.now().year
    list_tahun = list(range(current_year - 5, current_year + 6))

    return render_template(
        'sdm/master_kehadiran.html',
        entries=final_entries,
        list_bulan=list_bulan,
        karyawan_list=karyawan_list,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        list_tahun=list_tahun,
        jumlah_hari=jumlah_hari,
        range_hari=range(1, jumlah_hari + 1),
        weekends=weekends,
        holiday_days=holiday_days,
        active_page='master-sdm'
    )

@app.route('/master-kehadiran/update-cell', methods=['POST'])
def update_kehadiran_cell():
    # AJAX endpoint untuk auto-save harian
    if 'logged_user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    data = request.get_json()
    entry_id = data.get('id')
    nik = data.get('nik')
    bulan = data.get('bulan')
    tahun = data.get('tahun')
    day = str(data.get('day'))
    status = data.get('status').strip()
    scan_masuk = data.get('scan_masuk', '').strip()
    scan_pulang = data.get('scan_pulang', '').strip()
    keterangan = data.get('keterangan', '').strip()
    is_izin = bool(data.get('is_izin', False))
    
    if status not in ['M', 'S', 'DL', 'A', 'CT', 'CN', 'CD', 'L', 'P', 'C']:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    entry = None
    if entry_id:
        entry = db.session.get(Kehadiran, entry_id)
    elif nik and bulan and tahun:
        try:
            tahun = int(tahun)
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid year'}), 400
            
        entry = db.session.execute(
            db.select(Kehadiran).where(
                Kehadiran.nik == nik,
                Kehadiran.bulan == bulan,
                Kehadiran.tahun == tahun
            )
        ).scalar_one_or_none()
        
        if not entry:
            entry = Kehadiran(
                nik=nik,
                bulan=bulan,
                tahun=tahun,
                status_hari={},
                scan_masuk_hari={},
                scan_pulang_hari={},
                keterangan_hari={},
                izin_hari={}
            )
            db.session.add(entry)

    if not entry:
        return jsonify({'success': False, 'message': 'Data tidak ditemukan'}), 404

    # Update data status_hari JSON
    status_dict = dict(entry.status_hari)
    status_dict[day] = status
    entry.status_hari = status_dict # paksa SQLAlchemy mendeteksi mutasi data JSON
    
    scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
    scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}
    keterangan_dict = dict(entry.keterangan_hari) if entry.keterangan_hari else {}
    izin_dict = dict(entry.izin_hari) if entry.izin_hari else {}
    
    if status == 'M':
        scan_masuk_dict[day] = scan_masuk
        scan_pulang_dict[day] = scan_pulang
    else:
        scan_masuk_dict[day] = ''
        scan_pulang_dict[day] = ''
        
    keterangan_dict[day] = keterangan
    izin_dict[day] = is_izin
        
    entry.scan_masuk_hari = scan_masuk_dict
    entry.scan_pulang_hari = scan_pulang_dict
    entry.keterangan_hari = keterangan_dict
    entry.izin_hari = izin_dict
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if 'logged_user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    form = UserForm()
    
    if form.validate_on_submit():
        username_clean = form.username.data.strip()
        existing_user = db.session.execute(db.select(UserEntry).where(UserEntry.username == username_clean)).scalar_one_or_none()
        
        if existing_user:
            flash(f"⚠️ Gagal! Username '{username_clean}' sudah digunakan oleh orang lain.", "danger")
        else:
            if not form.password.data:
                flash("⚠️ Password wajib diisi untuk pengguna baru!", "danger")
            else:
                hashed_pw = generate_password_hash(form.password.data)
                new_user = UserEntry(username=username_clean, password=hashed_pw, role=form.role.data)
                db.session.add(new_user)
                db.session.commit()
                flash(f"Pengguna '{username_clean}' berhasil didaftarkan.", "success")
                return redirect(url_for('manage_users'))

    all_users = db.session.execute(db.select(UserEntry).order_by(UserEntry.id)).scalars().all()
    return render_template('sdm/users.html', form=form, users=all_users, active_page='users')

@app.route('/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'logged_user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    user_to_delete = db.session.get(UserEntry, user_id)
    
    if user_to_delete and user_to_delete.username == session['logged_user']:
        flash("⚠️ Anda tidak bisa menghapus akun Anda sendiri yang sedang aktif digunakan!", "danger")
    elif user_to_delete:
        username_deleted = user_to_delete.username
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"Akun pengguna '{username_deleted}' berhasil dihapus dari sistem.", "success")
    
    return redirect(url_for('manage_users'))

@app.route('/tambah-karyawan', methods=['GET', 'POST'])
def tambah_karyawan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nik = request.form.get('nik', '').strip().upper()
        absen_raw = request.form.get('absen', '').strip()
        nama = request.form.get('nama', '').strip()
        jabatan = request.form.get('jabatan', '').strip()
        tmk = request.form.get('tmk', '').strip()
        jam_masuk_raw = request.form.get('jam_masuk', '').strip()
        jam_pulang_raw = request.form.get('jam_pulang', '').strip()
        
        # Validasi
        if not (nik and absen_raw and nama and jabatan and tmk and jam_masuk_raw and jam_pulang_raw):
            flash("⚠️ Semua kolom wajib diisi!", "danger")
            return redirect(url_for('tambah_karyawan'))
            
        try:
            absen = int(absen_raw)
        except ValueError:
            flash("⚠️ Nomor absen harus berupa angka!", "danger")
            return redirect(url_for('tambah_karyawan'))
            
        # Cek duplikat NIK
        existing_nik = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
        ).scalar_one_or_none()
        if existing_nik:
            flash(f"⚠️ Gagal! NIK '{nik}' sudah digunakan.", "danger")
            return redirect(url_for('tambah_karyawan'))
            
        # Cek duplikat Absen
        existing_absen = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.absen == absen)
        ).scalar_one_or_none()
        if existing_absen:
            flash(f"⚠️ Gagal! Nomor absen '{absen}' sudah digunakan.", "danger")
            return redirect(url_for('tambah_karyawan'))
            
        # Parse jam_masuk dan jam_pulang
        from datetime import datetime
        try:
            jam_masuk_dt = datetime.strptime(jam_masuk_raw, "%H:%M")
            jam_masuk = jam_masuk_dt.time()
        except ValueError:
            try:
                jam_masuk_dt = datetime.strptime(jam_masuk_raw, "%H:%M:%S")
                jam_masuk = jam_masuk_dt.time()
            except ValueError:
                flash("⚠️ Format Jam Masuk tidak valid!", "danger")
                return redirect(url_for('tambah_karyawan'))
                
        try:
            jam_pulang_dt = datetime.strptime(jam_pulang_raw, "%H:%M")
            jam_pulang = jam_pulang_dt.time()
        except ValueError:
            try:
                jam_pulang_dt = datetime.strptime(jam_pulang_raw, "%H:%M:%S")
                jam_pulang = jam_pulang_dt.time()
            except ValueError:
                flash("⚠️ Format Jam Pulang tidak valid!", "danger")
                return redirect(url_for('tambah_karyawan'))
                
        # Simpan karyawan baru
        try:
            new_karyawan = KaryawanEntry(
                nik=nik,
                absen=absen,
                nama=nama,
                jabatan=jabatan,
                tmk=tmk,
                jam_masuk=jam_masuk,
                jam_pulang=jam_pulang
            )
            new_cuti = Cuti(
                nik=nik,
                cuti_tahunan=0,
                cuti_dinas=0
            )
            db.session.add(new_karyawan)
            db.session.add(new_cuti)
            db.session.commit()
            flash(f"✅ Karyawan '{nama}' (NIK: {nik}) berhasil ditambahkan!", "success")
            return redirect(url_for('master_karyawan'))
        except Exception as e:
            db.session.rollback()
            flash(f"⚠️ Terjadi kesalahan saat menyimpan data: {str(e)}", "danger")
            return redirect(url_for('tambah_karyawan'))
            
    return render_template('sdm/tambah_karyawan.html', active_page='sdm-transaksi')

@app.route('/upload-kehadiran', methods=['GET', 'POST'])
def upload_kehadiran():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    # Check if there are any pending attendance entries (warnings on dashboard)
    all_kehadiran = db.session.execute(db.select(Kehadiran)).scalars().all()
    bulan_list = db.session.execute(db.select(Bulan)).scalars().all()
    bulan_days_map = {b.nama: b.jumlah_hari for b in bulan_list}
    all_holidays = db.session.execute(db.select(HariLibur)).scalars().all()

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    
    import datetime
    has_warning = False
    for k in all_kehadiran:
        selected_bulan = k.bulan
        selected_tahun = k.tahun
        
        jumlah_hari = bulan_days_map.get(selected_bulan, 31)
        if selected_bulan == 'Februari':
            if (selected_tahun % 4 == 0 and selected_tahun % 100 != 0) or (selected_tahun % 400 == 0):
                jumlah_hari = 29
            else:
                jumlah_hari = 28
                
        month_num = MONTH_NUMBERS.get(selected_bulan, 1)

        # Cek jika karyawan sudah resign sebelum bulan ini
        if k.karyawan and k.karyawan.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.karyawan.tanggal_resign, "%Y-%m-%d")
                if selected_tahun > dt_resign.year:
                    continue
                if selected_tahun == dt_resign.year and month_num > dt_resign.month:
                    continue
            except ValueError:
                pass
        
        # Calculate weekends
        weekends = set()
        for d in range(1, jumlah_hari + 1):
            try:
                dt = datetime.date(selected_tahun, month_num, d)
                if dt.weekday() in (5, 6):
                    weekends.add(d)
            except ValueError:
                pass
                
        # Calculate holidays
        holidays = set()
        for h in all_holidays:
            if h.tanggal.month == month_num and h.tanggal.year == selected_tahun:
                holidays.add(h.tanggal.day)
                
        for d in range(1, jumlah_hari + 1):
            # Jika karyawan resign di bulan ini, lewati pengecekan untuk hari >= tanggal resign
            if k.karyawan and k.karyawan.tanggal_resign:
                try:
                    dt_resign = datetime.datetime.strptime(k.karyawan.tanggal_resign, "%Y-%m-%d")
                    if selected_tahun == dt_resign.year and month_num == dt_resign.month and d >= dt_resign.day:
                        continue
                except ValueError:
                    pass

            day_str = str(d)
            db_status = k.status_hari.get(day_str, '')
            if (d in weekends or d in holidays) and db_status != 'M':
                continue
            if db_status == 'P' or db_status == '':
                has_warning = True
                break
        if has_warning:
            break

    if request.method == 'POST':
        if has_warning:
            flash("⚠️ Gagal! Anda tidak dapat mengunggah berkas baru karena masih ada data kehadiran berstatus Pending di Dashboard.", "danger")
            return redirect(url_for('upload_kehadiran'))
            
        import pandas as pd
        
        file = request.files.get('file')
        if not file or file.filename == '':
            flash("⚠️ Silakan pilih berkas Excel terlebih dahulu!", "danger")
            return redirect(url_for('upload_kehadiran'))
            
        # Get extension
        ext = file.filename.split('.')[-1].lower()
        if ext not in ('xlsx', 'xls'):
            flash("⚠️ Format berkas tidak didukung! Pastikan berkas Anda bertipe .xlsx atau .xls", "danger")
            return redirect(url_for('upload_kehadiran'))
            
        try:
            # Read Excel using pandas, specify engine based on extension
            engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
            df = pd.read_excel(file, engine=engine)
            
            # Normalisasi nama-nama kolom agar pencarian lebih fleksibel (lowercase, hapus underscore, hapus spasi berlebih)
            normalized_cols = {}
            for col in df.columns:
                norm = str(col).strip().lower().replace('_', ' ')
                norm = ' '.join(norm.split()) # hapus multiple spaces
                normalized_cols[norm] = col
                
            col_nik = normalized_cols.get('nik')
            col_tanggal = normalized_cols.get('tanggal')
            col_masuk = normalized_cols.get('scan masuk')
            col_pulang = normalized_cols.get('scan pulang')
            
            if not col_nik or not col_tanggal:
                flash("⚠️ Berkas Excel wajib memiliki kolom 'NIK' dan 'tanggal'!", "danger")
                return redirect(url_for('upload_kehadiran'))
                
            success_count = 0
            skipped_nik_count = 0
            unique_employees = set()
            
            MONTH_MAPPING = {
                1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
                5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
                9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
            }
            
            # Iterasi setiap baris log harian
            for index, row in df.iterrows():
                nik = str(row[col_nik]).strip().upper()
                
                # Validasi NIK terdaftar
                karyawan = db.session.execute(
                    db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
                ).scalar_one_or_none()
                if not karyawan:
                    skipped_nik_count += 1
                    continue
                    
                # Parsing tanggal
                raw_tanggal = row[col_tanggal]
                from datetime import datetime
                if isinstance(raw_tanggal, (datetime, pd.Timestamp)):
                    try:
                        # Swap month and day since Excel parsed MM/DD/YYYY as DD/MM/YYYY
                        ts = pd.Timestamp(year=raw_tanggal.year, month=raw_tanggal.day, day=raw_tanggal.month)
                    except ValueError:
                        ts = pd.to_datetime(raw_tanggal, errors='coerce')
                else:
                    ts = pd.to_datetime(raw_tanggal, format='%m/%d/%Y', errors='coerce')
                    if pd.isna(ts):
                        ts = pd.to_datetime(raw_tanggal, errors='coerce')
                if pd.isna(ts):
                    continue
                    
                day = str(ts.day)
                bulan_num = ts.month
                tahun = ts.year
                
                if bulan_num not in MONTH_MAPPING:
                    continue
                bulan = MONTH_MAPPING[bulan_num]
                
                # Check scan times
                has_scan = False
                val_masuk = ''
                val_pulang = ''
                if col_masuk and pd.notna(row[col_masuk]):
                    val_masuk = str(row[col_masuk]).strip()
                    if val_masuk not in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                        has_scan = True
                    else:
                        val_masuk = ''
                if col_pulang and pd.notna(row[col_pulang]):
                    val_pulang = str(row[col_pulang]).strip()
                    if val_pulang not in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                        has_scan = True
                    else:
                        val_pulang = ''
                        
                status = 'M' if has_scan else 'P'
                
                # Ambil atau buat entri Kehadiran untuk periode ini
                entry = db.session.execute(
                    db.select(Kehadiran).where(Kehadiran.nik == nik, Kehadiran.bulan == bulan, Kehadiran.tahun == tahun)
                ).scalar_one_or_none()
                
                if not entry:
                    # Inisialisasi entri kehadiran baru
                    entry = Kehadiran(
                        nik=nik,
                        bulan=bulan,
                        tahun=tahun,
                        status_hari={},
                        scan_masuk_hari={},
                        scan_pulang_hari={}
                    )
                    db.session.add(entry)
                    
                status_dict = dict(entry.status_hari)
                scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
                scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}
                
                # Aturan bisnis: Jika status di DB saat ini adalah izin resmi (S, C, CT, CN, CD, DL, L)
                # dan status baru adalah 'A' (Alpa) atau 'P' (Pending), jangan overwrite izin resmi tersebut!
                current_status = status_dict.get(day, '')
                if current_status in ('S', 'C', 'CT', 'CN', 'CD', 'DL', 'L') and status in ('A', 'P'):
                    pass
                else:
                    status_dict[day] = status
                    entry.status_hari = status_dict  # deteksi mutasi JSON
                    
                    if status == 'M':
                        scan_masuk_dict[day] = val_masuk
                        scan_pulang_dict[day] = val_pulang
                    else:
                        scan_masuk_dict[day] = ''
                        scan_pulang_dict[day] = ''
                        
                    entry.scan_masuk_hari = scan_masuk_dict
                    entry.scan_pulang_hari = scan_pulang_dict
                    
                success_count += 1
                unique_employees.add(nik)
                
            db.session.commit()
            
            # Flash success message
            msg = f"✅ Berhasil memproses {success_count} baris log kehadiran harian untuk {len(unique_employees)} karyawan."
            if skipped_nik_count > 0:
                msg += f" (⚠️ {skipped_nik_count} baris dilewati karena NIK tidak terdaftar)."
            flash(msg, "success")
            return redirect(url_for('master_kehadiran'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"⚠️ Terjadi kesalahan saat membaca berkas Excel: {str(e)}", "danger")
            return redirect(url_for('upload_kehadiran'))
            
    return render_template('sdm/upload_kehadiran.html', has_warning=has_warning, active_page='sdm-transaksi')

@app.route('/atur-libur')
def atur_libur():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    selected_bulan = request.args.get('bulan', 'Januari').strip()
    selected_tahun = request.args.get('tahun', '2026').strip()
    
    try:
        selected_tahun = int(selected_tahun)
    except ValueError:
        selected_tahun = 2026
        
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    month_num = MONTH_NUMBERS.get(selected_bulan, 1)
    
    # Query all holidays and filter in python
    all_holidays = db.session.execute(
        db.select(HariLibur).order_by(HariLibur.tanggal)
    ).scalars().all()
    
    filtered_holidays = []
    for h in all_holidays:
        if h.tanggal.month == month_num and h.tanggal.year == selected_tahun:
            filtered_holidays.append(h)
            
    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()
    
    return render_template(
        'sdm/atur_libur.html',
        holidays=filtered_holidays,
        list_bulan=list_bulan,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        active_page='sdm-transaksi'
    )

@app.route('/atur-libur/add', methods=['POST'])
def add_libur():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    tanggal_raw = request.form.get('tanggal')
    keterangan = request.form.get('keterangan', '').strip()
    
    if not tanggal_raw or not keterangan:
        flash("⚠️ Kolom tanggal dan keterangan wajib diisi!", "danger")
        return redirect(url_for('atur_libur'))
        
    try:
        from datetime import datetime
        tanggal_dt = datetime.strptime(tanggal_raw, "%Y-%m-%d").date()
        
        # Check duplicate
        exists = db.session.execute(
            db.select(HariLibur).where(HariLibur.tanggal == tanggal_dt)
        ).scalar_one_or_none()
        if exists:
            flash(f"⚠️ Tanggal {tanggal_raw} sudah terdaftar sebagai hari libur!", "danger")
            return redirect(url_for('atur_libur'))
            
        new_libur = HariLibur(tanggal=tanggal_dt, keterangan=keterangan)
        db.session.add(new_libur)
        db.session.commit()
        
        MONTH_MAPPING_REV = {
            1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
            5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
            9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
        }
        flash(f"✅ Hari libur '{keterangan}' berhasil ditambahkan!", "success")
        return redirect(url_for('atur_libur', bulan=MONTH_MAPPING_REV[tanggal_dt.month], tahun=tanggal_dt.year))
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Terjadi kesalahan: {str(e)}", "danger")
        return redirect(url_for('atur_libur'))

@app.route('/atur-libur/delete/<int:id>', methods=['POST'])
def delete_libur(id):
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    libur = db.session.execute(
        db.select(HariLibur).where(HariLibur.id == id)
    ).scalar_one_or_none()
    
    if not libur:
        flash("⚠️ Hari libur tidak ditemukan!", "danger")
        return redirect(url_for('atur_libur'))
        
    MONTH_MAPPING_REV = {
        1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
        5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
        9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
    }
    bulan_redirect = MONTH_MAPPING_REV[libur.tanggal.month]
    tahun_redirect = libur.tanggal.year
    
    try:
        db.session.delete(libur)
        db.session.commit()
        flash("✅ Hari libur berhasil dihapus.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Gagal menghapus hari libur: {str(e)}", "danger")
        
    return redirect(url_for('atur_libur', bulan=bulan_redirect, tahun=tahun_redirect))

@app.route('/izin', methods=['GET'])
def izin():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    
    selected_bulan = request.args.get('bulan', 'Januari').strip()
    selected_tahun = request.args.get('tahun', '2026').strip()
    
    try:
        selected_tahun = int(selected_tahun)
    except ValueError:
        selected_tahun = 2026

    bulan_meta = db.session.execute(db.select(Bulan).where(Bulan.nama == selected_bulan)).scalar_one_or_none()
    jumlah_hari = bulan_meta.jumlah_hari if bulan_meta else 31
    if selected_bulan == 'Februari':
        if (selected_tahun % 4 == 0 and selected_tahun % 100 != 0) or (selected_tahun % 400 == 0):
            jumlah_hari = 29
        else:
            jumlah_hari = 28

    # Ambil semua data karyawan terdaftar, diurutkan berdasarkan nomor absen
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    view_month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    import datetime
    filtered_karyawan_list = []
    for k in karyawan_list:
        if k.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.tanggal_resign, "%Y-%m-%d")
                if selected_tahun > dt_resign.year:
                    continue
                if selected_tahun == dt_resign.year and view_month_num > dt_resign.month:
                    continue
            except ValueError:
                pass
        filtered_karyawan_list.append(k)

    # Ambil data kehadiran dari DB yang sudah ada untuk periode terpilih
    existing_entries = db.session.execute(
        db.select(Kehadiran)
        .where(Kehadiran.bulan == selected_bulan, Kehadiran.tahun == selected_tahun)
    ).scalars().all()

    # Buat mapping NIK ke entri Kehadiran yang ada
    kehadiran_map = {e.nik: e for e in existing_entries}

    # Gabungkan data: jika karyawan belum ada di DB, buat entri transient kosong di memori
    final_entries = []
    for k in filtered_karyawan_list:
        if k.nik in kehadiran_map:
            final_entries.append(kehadiran_map[k.nik])
        else:
            temp_entry = Kehadiran(
                nik=k.nik,
                bulan=selected_bulan,
                tahun=selected_tahun,
                status_hari={},
                scan_masuk_hari={},
                scan_pulang_hari={}
            )
            temp_entry.karyawan = k
            final_entries.append(temp_entry)

    # List bulan untuk filter dropdown
    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()

    # Hitung hari sabtu & minggu (weekends) untuk bulan & tahun terpilih
    weekends = []
    for d in range(1, jumlah_hari + 1):
        try:
            dt = datetime.date(selected_tahun, view_month_num, d)
            if dt.weekday() in (5, 6):  # 5 = Sabtu, 6 = Minggu
                weekends.append(d)
        except ValueError:
            pass

    # Ambil hari libur untuk bulan & tahun terpilih
    all_holidays = db.session.execute(
        db.select(HariLibur)
    ).scalars().all()
    
    holiday_days = {}
    for h in all_holidays:
        if h.tanggal.month == view_month_num and h.tanggal.year == selected_tahun:
            holiday_days[h.tanggal.day] = h.keterangan

    current_year = datetime.datetime.now().year
    list_tahun = list(range(current_year - 5, current_year + 6))

    return render_template(
        'sdm/izin.html',
        entries=final_entries,
        list_bulan=list_bulan,
        karyawan_list=filtered_karyawan_list,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        list_tahun=list_tahun,
        jumlah_hari=jumlah_hari,
        range_hari=range(1, jumlah_hari + 1),
        weekends=weekends,
        holiday_days=holiday_days,
        active_page='sdm-transaksi'
    )

@app.route('/edit-kehadiran', methods=['GET'])
def edit_kehadiran():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    
    selected_bulan = request.args.get('bulan', 'Januari').strip()
    selected_tahun = request.args.get('tahun', '2026').strip()
    
    try:
        selected_tahun = int(selected_tahun)
    except ValueError:
        selected_tahun = 2026

    bulan_meta = db.session.execute(db.select(Bulan).where(Bulan.nama == selected_bulan)).scalar_one_or_none()
    jumlah_hari = bulan_meta.jumlah_hari if bulan_meta else 31
    if selected_bulan == 'Februari':
        if (selected_tahun % 4 == 0 and selected_tahun % 100 != 0) or (selected_tahun % 400 == 0):
            jumlah_hari = 29
        else:
            jumlah_hari = 28

    # Ambil semua data karyawan terdaftar, diurutkan berdasarkan nomor absen
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    view_month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    import datetime
    filtered_karyawan_list = []
    for k in karyawan_list:
        if k.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.tanggal_resign, "%Y-%m-%d")
                if selected_tahun > dt_resign.year:
                    continue
                if selected_tahun == dt_resign.year and view_month_num > dt_resign.month:
                    continue
            except ValueError:
                pass
        filtered_karyawan_list.append(k)

    # Ambil data kehadiran dari DB yang sudah ada untuk periode terpilih
    existing_entries = db.session.execute(
        db.select(Kehadiran)
        .where(Kehadiran.bulan == selected_bulan, Kehadiran.tahun == selected_tahun)
    ).scalars().all()

    # Buat mapping NIK ke entri Kehadiran yang ada
    kehadiran_map = {e.nik: e for e in existing_entries}

    # Gabungkan data: jika karyawan belum ada di DB, buat entri transient kosong di memori
    final_entries = []
    for k in filtered_karyawan_list:
        if k.nik in kehadiran_map:
            final_entries.append(kehadiran_map[k.nik])
        else:
            temp_entry = Kehadiran(
                nik=k.nik,
                bulan=selected_bulan,
                tahun=selected_tahun,
                status_hari={},
                scan_masuk_hari={},
                scan_pulang_hari={}
            )
            temp_entry.karyawan = k
            final_entries.append(temp_entry)

    # List bulan untuk filter dropdown
    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()

    # Hitung hari sabtu & minggu (weekends) untuk bulan & tahun terpilih
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    month_num = MONTH_NUMBERS.get(selected_bulan, 1)
    
    import datetime
    weekends = []
    for d in range(1, jumlah_hari + 1):
        try:
            dt = datetime.date(selected_tahun, month_num, d)
            if dt.weekday() in (5, 6):  # 5 = Sabtu, 6 = Minggu
                weekends.append(d)
        except ValueError:
            pass

    # Ambil hari libur untuk bulan & tahun terpilih
    all_holidays = db.session.execute(
        db.select(HariLibur)
    ).scalars().all()
    
    holiday_days = {}
    for h in all_holidays:
        if h.tanggal.month == month_num and h.tanggal.year == selected_tahun:
            holiday_days[h.tanggal.day] = h.keterangan

    import datetime
    current_year = datetime.datetime.now().year
    list_tahun = list(range(current_year - 5, current_year + 6))

    return render_template(
        'sdm/edit_kehadiran.html',
        entries=final_entries,
        list_bulan=list_bulan,
        karyawan_list=filtered_karyawan_list,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        list_tahun=list_tahun,
        jumlah_hari=jumlah_hari,
        range_hari=range(1, jumlah_hari + 1),
        weekends=weekends,
        holiday_days=holiday_days,
        active_page='sdm-transaksi'
    )



