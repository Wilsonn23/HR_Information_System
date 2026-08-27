# ===============================================================================================================
# SDM (HUMAN RESOURCES) MODULE
# ===============================================================================================================

from flask import render_template, request, redirect, url_for, flash, session, jsonify
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, Regexp
from werkzeug.security import generate_password_hash

from app import app, db, csrf, UserEntry, KaryawanEntry, Bulan, Kehadiran, Cuti, HariLibur, CutiManual, SdmActivityLog, Jabatan, PT, Kota, Unit, SdmPT, SdmDivisi, SdmDepartemen

def sdm_log(aksi: str, kategori: str, detail: str, nik: str = None, nama_karyawan: str = None):
    """Helper untuk mencatat log aktivitas SDM ke tabel sdm_activity_logs."""
    try:
        log = SdmActivityLog(
            aksi=aksi,
            kategori=kategori,
            nik=nik,
            nama_karyawan=nama_karyawan,
            detail=detail,
            dilakukan_oleh=session.get('logged_user', 'system')
        )
        db.session.add(log)
        # commit dilakukan oleh caller, tidak di sini, untuk menghindari partial commit
    except Exception:
        pass  # jangan sampai logging error mengganggu flow utama

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

import datetime

def add_months(start_date, months):
    year = start_date.year + (start_date.month + months - 1) // 12
    month = (start_date.month + months - 1) % 12 + 1
    return datetime.date(year, month, 1)

def get_cuti_tahunan_balance(karyawan, ref_date=None, kehadiran_entries=None, cuti_manual_entries=None, bulan_days_map=None):
    if not ref_date:
        if 'simulation_date' in session:
            try:
                ref_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
            except Exception:
                ref_date = datetime.date.today()
        else:
            ref_date = datetime.date.today()
            
    # Force ref_date to be compared at month start level or using first day of month
    ref_month_start = datetime.date(ref_date.year, ref_date.month, 1)
        
    # Parse TMK — semua jalur input (tambah_karyawan & upload_karyawan) menyimpan format YYYY-MM-DD.
    # Fallback ke format lama untuk kompatibilitas data sebelumnya.
    raw_tmk = None
    for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
        try:
            raw_tmk = datetime.datetime.strptime(karyawan.tmk.strip(), fmt).date()
            break
        except (ValueError, AttributeError):
            continue

    if not raw_tmk:
        return {
            'accrued': 0,
            'used': 0,
            'expired': 0,
            'balance': 0,
            'leaves': []
        }

    tmk_date = datetime.date(raw_tmk.year, raw_tmk.month, 1)
        
    leaves = []
    if kehadiran_entries is None:
        kehadiran_entries = db.session.execute(
            db.select(Kehadiran).where(Kehadiran.nik == karyawan.nik)
        ).scalars().all()
    
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    
    for entry in kehadiran_entries:
        m_num = MONTH_NUMBERS.get(entry.bulan)
        if not m_num:
            continue
        if entry.status_hari:
            for d_str, status in entry.status_hari.items():
                if status == 'CT':
                    try:
                        leave_dt = datetime.date(entry.tahun, m_num, int(d_str))
                        if leave_dt <= ref_date:
                            leaves.append(leave_dt)
                    except ValueError:
                        pass
                        
    leaves.sort()
    
    max_accrual_date = ref_date
    if leaves:
        max_accrual_date = max(ref_date, leaves[-1])
        
    accruals = []
    m = 12
    while True:
        accrual_date = add_months(tmk_date, m)
        if accrual_date > max_accrual_date:
            break

        if m < 24:
            # Blok tahun ke-1:
            #   m=12  → 12 hari sekaligus (jatah tahun pertama)
            #   m=13-23 → 1 hari/bulan
            # Semua hangus di TMK+28 bulan → total maksimal 23 hari
            amount = 12 if m == 12 else 1
            expiration_date = add_months(tmk_date, 28)
        else:
            # Blok tahun ke-2 dst: 1 hari/bulan
            #   m=24-35 → year_idx=2 → hangus TMK+40
            #   m=36-47 → year_idx=3 → hangus TMK+52, dst.
            amount = 1
            year_idx = m // 12
            expiration_date = add_months(tmk_date, 12 * year_idx + 16)

        accruals.append({
            'date': accrual_date,
            'amount': amount,
            'expiration': expiration_date,
            'remaining': amount
        })
        m += 1

    used_leaves_count = 0
    unmatched_leaves_count = 0
    for leave_date in leaves:
        matched = False
        for acc in accruals:
            if acc['date'] <= leave_date and acc['remaining'] > 0:
                acc['remaining'] -= 1
                used_leaves_count += 1
                matched = True
                break
        if not matched:
            active_accs = [acc for acc in accruals if acc['date'] <= leave_date]
            if active_accs:
                active_accs[-1]['remaining'] -= 1
                used_leaves_count += 1
            else:
                if accruals:
                    accruals[-1]['remaining'] -= 1
                    used_leaves_count += 1
                else:
                    unmatched_leaves_count += 1

    # 1. Pengurangan manual cuti tahunan (CutiManual tipe='CT') secara FIFO
    ref_date_str = ref_date.strftime("%Y-%m-%d")
    if cuti_manual_entries is None:
        manual_used_sum = db.session.execute(
            db.select(db.func.sum(CutiManual.jumlah)).where(
                CutiManual.nik == karyawan.nik,
                CutiManual.tipe == 'CT',
                CutiManual.tanggal_input <= ref_date_str
            )
        ).scalar() or 0.0
    else:
        manual_used_sum = sum(
            m.jumlah for m in cuti_manual_entries 
            if m.tipe == 'CT' and (not m.tanggal_input or m.tanggal_input <= ref_date_str)
        )

    remaining_manual_to_consume = manual_used_sum
    for acc in accruals:
        if remaining_manual_to_consume <= 0:
            break
        if acc['remaining'] > 0:
            consume_amount = min(acc['remaining'], remaining_manual_to_consume)
            acc['remaining'] -= consume_amount
            remaining_manual_to_consume -= consume_amount
            used_leaves_count += consume_amount

    # 2. Pengurangan manual cuti hangus (CutiManual tipe='HANGUS') secara FIFO dari jatah yang sudah kedaluwarsa
    if cuti_manual_entries is None:
        manual_expired_sum = db.session.execute(
            db.select(db.func.sum(CutiManual.jumlah)).where(
                CutiManual.nik == karyawan.nik,
                CutiManual.tipe == 'HANGUS',
                CutiManual.tanggal_input <= ref_date_str
            )
        ).scalar() or 0.0
    else:
        manual_expired_sum = sum(
            m.jumlah for m in cuti_manual_entries 
            if m.tipe == 'HANGUS' and (not m.tanggal_input or m.tanggal_input <= ref_date_str)
        )

    remaining_expired_to_consume = manual_expired_sum
    # Dahulukan pemotongan dari accrual yang sudah lewat tanggal hangusnya
    for acc in accruals:
        if remaining_expired_to_consume <= 0:
            break
        if acc['expiration'] <= ref_date and acc['remaining'] > 0:
            consume_amount = min(acc['remaining'], remaining_expired_to_consume)
            acc['remaining'] -= consume_amount
            remaining_expired_to_consume -= consume_amount

    # Jika masih ada sisa pemotongan jatah hangus (safety fallback), potong dari accrual mana saja
    for acc in accruals:
        if remaining_expired_to_consume <= 0:
            break
        if acc['remaining'] > 0:
            consume_amount = min(acc['remaining'], remaining_expired_to_consume)
            acc['remaining'] -= consume_amount
            remaining_expired_to_consume -= consume_amount

    # 3. Pengurangan akibat penalti jam kerja (potong_cuti) secara FIFO
    # Hitung pemotongan cuti akibat penalti jam kerja
    history = get_karyawan_jam_kerja_history(
        karyawan, 
        kehadiran_entries=kehadiran_entries, 
        bulan_days_map=bulan_days_map,
        target_year=ref_date.year,
        target_month=ref_date.month
    )
    total_potong_cuti = 0
    ref_month_start = datetime.date(ref_date.year, ref_date.month, 1)
    
    for (thn, bln), info in history.items():
        p_month_start = datetime.date(thn, MONTH_NUMBERS.get(bln, 1), 1)
        if p_month_start < ref_month_start:
            total_potong_cuti += info['potong_cuti']

    remaining_potong_cuti = total_potong_cuti
    for acc in accruals:
        if remaining_potong_cuti <= 0:
            break
        if acc['date'] <= ref_date and acc['remaining'] > 0:
            consume_amount = min(acc['remaining'], remaining_potong_cuti)
            acc['remaining'] -= consume_amount
            remaining_potong_cuti -= consume_amount

    # Kalkulasi saldo akhir
    total_accrued = 0
    total_expired = manual_expired_sum  # Jatah hangus yang diakui hanya yang didelete manual
    active_balance = 0
    pending_expiration_amount = 0

    for acc in accruals:
        if acc['date'] <= ref_date:
            total_accrued += acc['amount']
            
            # Jika tanggal kedaluwarsa sudah terlampaui tetapi belum di-consume (belum di-delete manual)
            # masukkan ke pending_expiration_amount
            if acc['expiration'] <= ref_date:
                pending_expiration_amount += acc['remaining']
            
            # Saldo aktif mencakup semua jatah akrual yang tersisa (termasuk yang sudah lewat waktu hangus tapi belum didelete manual)
            active_balance += acc['remaining']

    # Hitung akrual jatah cuti pada periode aktif berjalan
    current_period_accrued = 0
    months_since_tmk = (ref_date.year - tmk_date.year) * 12 + (ref_date.month - tmk_date.month)
    if months_since_tmk >= 12:
        current_year_idx = months_since_tmk // 12
        current_period_start = add_months(tmk_date, current_year_idx * 12)
        for acc in accruals:
            if current_period_start <= acc['date'] <= ref_date:
                current_period_accrued += acc['amount']

    # Cari tanggal hangus terdekat dan jatah yang akan hangus berikutnya (hanya dari jatah yang belum hangus/dihapus)
    next_expiration_date = None
    next_expiration_amount = 0
    active_accruals = [acc for acc in accruals if acc['date'] <= ref_date and acc['expiration'] > ref_date and acc['remaining'] > 0]
    if active_accruals:
        active_accruals.sort(key=lambda x: x['expiration'])
        next_expiration_date = active_accruals[0]['expiration']
        next_expiration_amount = sum(
            acc['remaining'] for acc in active_accruals
            if acc['expiration'] == next_expiration_date
        )

    return {
        'accrued': total_accrued,
        'period_accrued': current_period_accrued + pending_expiration_amount,
        'current_period_accrued': current_period_accrued,
        'used': len(leaves) + manual_used_sum + total_potong_cuti,
        'used_leaves': len(leaves) + manual_used_sum,
        'potong_cuti': total_potong_cuti,
        'expired': total_expired,
        'balance': active_balance - unmatched_leaves_count,
        'pending_expiration_amount': pending_expiration_amount,
        'leaves': leaves,
        'next_expiration_date': next_expiration_date,
        'next_expiration_amount': next_expiration_amount,
        'accruals': accruals
    }

MONTH_NUMBERS_GLOBAL = {
    'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
    'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
    'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
}

def get_cuti_dinas_balance(karyawan, ref_date=None, kehadiran_entries=None, cuti_manual_entries=None):
    """
    Hitung saldo cuti dinas (ADD_CD) secara FIFO berdasarkan tanggal TMK karyawan.
    Masa berlaku jatah cuti dinas = sama dengan akhir periode cuti tahunan aktif saat cuti dinas didapat.
    """
    if not ref_date:
        if 'simulation_date' in session:
            try:
                ref_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
            except Exception:
                ref_date = datetime.date.today()
        else:
            ref_date = datetime.date.today()

    # Parse TMK
    raw_tmk = None
    for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
        try:
            raw_tmk = datetime.datetime.strptime(karyawan.tmk.strip(), fmt).date()
            break
        except (ValueError, AttributeError):
            continue

    if not raw_tmk:
        return {
            'added': 0.0,
            'used': 0.0,
            'expired': 0.0,
            'balance': 0.0,
            'pending_expiration_amount': 0.0,
            'detail': []
        }

    tmk_date = datetime.date(raw_tmk.year, raw_tmk.month, 1)

    # 1. Kumpulkan semua ADD_CD
    if cuti_manual_entries is None:
        add_manuals = db.session.execute(
            db.select(CutiManual).where(
                CutiManual.nik == karyawan.nik,
                CutiManual.tipe == 'ADD_CD'
            )
        ).scalars().all()
    else:
        add_manuals = [m for m in cuti_manual_entries if m.tipe == 'ADD_CD']

    allocations = []
    for m in add_manuals:
        try:
            m_date = datetime.datetime.strptime(m.tanggal_input, "%Y-%m-%d").date()
        except Exception:
            continue

        if m_date > ref_date:
            continue

        # Check if user inputted a specific expiration date
        if m.tanggal_kadaluarsa:
            try:
                expiration_date = datetime.datetime.strptime(m.tanggal_kadaluarsa, "%Y-%m-%d").date()
            except Exception:
                n = 1
                while True:
                    expiration_date = add_months(tmk_date, 28 + 12 * (n - 1))
                    if expiration_date >= m_date:
                        break
                    n += 1
        else:
            # Cari E_n (tanggal hangus block cuti tahunan) >= tanggal_input cuti dinas
            n = 1
            while True:
                expiration_date = add_months(tmk_date, 28 + 12 * (n - 1))
                if expiration_date >= m_date:
                    break
                n += 1

        allocations.append({
            'date': m_date,
            'amount': m.jumlah,
            'expiration': expiration_date,
            'remaining': m.jumlah,
            'keterangan': m.keterangan or ''
        })

    # Sort alokasi berdasarkan tanggal hangus dahulu, baru tanggal didapat
    allocations.sort(key=lambda x: (x['expiration'], x['date']))

    # 2. Penggunaan cuti dinas (Kehadiran CD & CutiManual CD)
    usages = []

    # Kehadiran CD
    if kehadiran_entries is None:
        kehadiran_entries = db.session.execute(
            db.select(Kehadiran).where(Kehadiran.nik == karyawan.nik)
        ).scalars().all()

    for entry in kehadiran_entries:
        m_num = MONTH_NUMBERS_GLOBAL.get(entry.bulan)
        if not m_num:
            continue
        if entry.status_hari:
            for d_str, status in entry.status_hari.items():
                if status == 'CD':
                    try:
                        u_date = datetime.date(entry.tahun, m_num, int(d_str))
                        if u_date <= ref_date:
                            usages.append({
                                'date': u_date,
                                'amount': 1.0,
                                'keterangan': f"Absensi CD ({entry.bulan} {entry.tahun})"
                            })
                    except ValueError:
                        pass

    # CutiManual CD
    if cuti_manual_entries is None:
        cd_manuals = db.session.execute(
            db.select(CutiManual).where(
                CutiManual.nik == karyawan.nik,
                CutiManual.tipe == 'CD'
            )
        ).scalars().all()
    else:
        cd_manuals = [m for m in cuti_manual_entries if m.tipe == 'CD']

    for m in cd_manuals:
        try:
            m_date = datetime.datetime.strptime(m.tanggal_input, "%Y-%m-%d").date()
            if m_date <= ref_date:
                usages.append({
                    'date': m_date,
                    'amount': m.jumlah,
                    'keterangan': m.keterangan or 'Pengurangan cuti dinas manual'
                })
        except Exception:
            pass

    usages.sort(key=lambda x: x['date'])

    # 3. Potong FIFO
    for u in usages:
        use_date = u['date']
        use_amt = u['amount']
        for acc in allocations:
            if use_amt <= 0:
                break
            if acc['date'] <= use_date and acc['remaining'] > 0:
                consume = min(acc['remaining'], use_amt)
                acc['remaining'] -= consume
                use_amt -= consume

    # 4. Potong HANGUS_CD manual
    if cuti_manual_entries is None:
        hangus_manuals = db.session.execute(
            db.select(CutiManual).where(
                CutiManual.nik == karyawan.nik,
                CutiManual.tipe == 'HANGUS_CD'
            )
        ).scalars().all()
    else:
        hangus_manuals = [m for m in cuti_manual_entries if m.tipe == 'HANGUS_CD']

    valid_hangus_manuals = []
    for m in hangus_manuals:
        try:
            m_date = datetime.datetime.strptime(m.tanggal_input, "%Y-%m-%d").date()
            if m_date <= ref_date:
                valid_hangus_manuals.append(m)
        except Exception:
            valid_hangus_manuals.append(m)

    total_deleted_manual = sum(m.jumlah for m in valid_hangus_manuals)
    remaining_hangus = total_deleted_manual

    # Dahulukan alokasi yang sudah expired
    for acc in allocations:
        if remaining_hangus <= 0:
            break
        if acc['expiration'] <= ref_date and acc['remaining'] > 0:
            consume = min(acc['remaining'], remaining_hangus)
            acc['remaining'] -= consume
            remaining_hangus -= consume

    # Fallback ke alokasi lain jika ada sisa
    for acc in allocations:
        if remaining_hangus <= 0:
            break
        if acc['remaining'] > 0:
            consume = min(acc['remaining'], remaining_hangus)
            acc['remaining'] -= consume
            remaining_hangus -= consume

    # 5. Hitung total saldo
    total_added = sum(acc['amount'] for acc in allocations)
    active_balance = 0.0
    pending_expiration = 0.0
    detail_hangus = {}

    for acc in allocations:
        if acc['date'] <= ref_date:
            active_balance += acc['remaining']
            if acc['expiration'] <= ref_date:
                pending_expiration += acc['remaining']
                if acc['remaining'] > 0:
                    detail_hangus[acc['expiration']] = detail_hangus.get(acc['expiration'], 0.0) + acc['remaining']

    detail_list = []
    for exp_date, amt in detail_hangus.items():
        periods = []
        for acc in allocations:
            if acc['expiration'] == exp_date:
                p_str = f"{list(MONTH_NUMBERS_GLOBAL.keys())[acc['date'].month - 1]} {acc['date'].year}"
                if p_str not in periods:
                    periods.append(p_str)
        detail_list.append({
            'period': ", ".join(periods),
            'expired_amount': amt,
            'period_end': exp_date
        })

    # next expiration info for cuti dinas
    next_expiration_date = None
    next_expiration_amount = 0.0
    active_allocs = [acc for acc in allocations if acc['date'] <= ref_date and acc['expiration'] > ref_date and acc['remaining'] > 0]
    if active_allocs:
        active_allocs.sort(key=lambda x: x['expiration'])
        next_expiration_date = active_allocs[0]['expiration']
        next_expiration_amount = sum(
            acc['remaining'] for acc in active_allocs
            if acc['expiration'] == next_expiration_date
        )

    return {
        'added': total_added,
        'used': sum(u['amount'] for u in usages),
        'expired': total_deleted_manual,
        'balance': active_balance,
        'pending_expiration_amount': pending_expiration,
        'detail': detail_list,
        'next_expiration_date': next_expiration_date,
        'next_expiration_amount': next_expiration_amount,
        'allocations': allocations,
    }

def get_adjusted_cuti_balances(karyawan, ref_date=None, kehadiran_entries=None, cuti_manual_entries=None, bulan_days_map=None):
    tahunan_info = get_cuti_tahunan_balance(
        karyawan, ref_date,
        kehadiran_entries=kehadiran_entries,
        cuti_manual_entries=cuti_manual_entries,
        bulan_days_map=bulan_days_map
    )
    dinas_info = get_cuti_dinas_balance(
        karyawan, ref_date,
        kehadiran_entries=kehadiran_entries,
        cuti_manual_entries=cuti_manual_entries
    )
    
    tahunan_bal = tahunan_info['balance']
    dinas_bal = dinas_info['balance']
    
    offset = 0
    if tahunan_bal < 0:
        offset = min(-tahunan_bal, dinas_bal)
        
    tahunan_info['balance'] = tahunan_bal
    dinas_info['balance'] = dinas_bal
    tahunan_info['offset'] = offset
    dinas_info['offset'] = offset
    
    return tahunan_info, dinas_info

def get_cuti_dinas_hangus(nik, ref_date=None):
    """
    Wrapper untuk kompatibilitas pencarian cuti dinas hangus.
    """
    karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    if not karyawan:
        return {'total_hangus': 0.0, 'detail': []}

    res = get_cuti_dinas_balance(karyawan, ref_date)
    return {
        'total_hangus': res['pending_expiration_amount'],
        'detail': res['detail']
    }


@app.route('/simulasi-tanggal', methods=['POST'])
def simulasi_tanggal():
    sim_date = request.form.get('sim_date')
    if sim_date:
        session['simulation_date'] = sim_date
        flash(f"🕒 Tanggal simulasi diatur ke: {sim_date}", "warning")
    else:
        session.pop('simulation_date', None)
        flash("🕒 Tanggal simulasi direset ke Hari Ini.", "success")
    ref = request.referrer or url_for('sdm_dashboard')
    return redirect(ref)

@app.route('/simulasi-tanggal/reset')
def reset_simulasi_tanggal():
    session.pop('simulation_date', None)
    flash("🕒 Tanggal simulasi direset ke Hari Ini.", "success")
    ref = request.referrer or url_for('sdm_dashboard')
    return redirect(ref)

class UserForm(FlaskForm):
    nik = StringField('NIK', validators=[
        DataRequired(message="NIK wajib diisi!"),
        Length(min=3, max=50, message="NIK harus antara 3 sampai 50 karakter!"),
        Regexp(r'^[a-zA-Z0-9]+$', message="NIK hanya boleh berisi huruf dan angka (tanpa spasi/simbol)!")
    ])
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=50)])
    password = StringField('Password (Isi jika ingin diubah)', validators=[Optional(), Length(min=6)])
    role = SelectField('Role', choices=[('user', 'User'), ('operasional', 'Staff Operasional'), ('hr', 'Staff SDM'), ('admin', 'Administrator')], validators=[DataRequired()])
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

    # Bulk fetch CutiManual
    all_cuti_manual = db.session.execute(db.select(CutiManual)).scalars().all()
    
    from collections import defaultdict
    kehadiran_by_nik = defaultdict(list)
    for kh in all_kehadiran:
        kehadiran_by_nik[kh.nik].append(kh)
        
    cuti_manual_by_nik = defaultdict(list)
    for cm in all_cuti_manual:
        cuti_manual_by_nik[cm.nik].append(cm)

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    
    import datetime
    
    # Resolve system/simulation date
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass
            
    reminders_h1 = []
    reminders_lampau = []
    if system_date.weekday() == 0:  # Monday
        h1_date = system_date - datetime.timedelta(days=3)
        h1_label = "Kehadiran Pending Jumat (H-3)"
    else:
        h1_date = system_date - datetime.timedelta(days=1)
        h1_label = "Kehadiran Pending Kemarin (H-1)"

    # Pre-group holidays by (year, month)
    holidays_by_period = defaultdict(set)
    for h in all_holidays:
        holidays_by_period[(h.tanggal.year, h.tanggal.month)].add(h.tanggal.day)
    weekends_by_period = {}
    
    all_k = db.session.execute(db.select(KaryawanEntry).order_by(KaryawanEntry.absen)).scalars().all()
    karyawan_list = []
    for k in all_k:
        if k.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                if dt_resign <= system_date:
                    continue
            except ValueError:
                pass
        karyawan_list.append(k)

    kehadiran_map = {(k.nik, k.bulan, k.tahun): k for k in all_kehadiran}
    INV_MONTHS = {v: k for k, v in MONTH_NUMBERS_GLOBAL.items()}

    for karyawan in karyawan_list:
        # Resolve TMK date
        tmk_date = None
        if karyawan.tmk:
            for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                try:
                    tmk_date = datetime.datetime.strptime(karyawan.tmk.strip(), fmt).date()
                    break
                except ValueError:
                    pass

        # Resolve resign date
        resign_date = None
        if karyawan.tanggal_resign:
            try:
                resign_date = datetime.datetime.strptime(karyawan.tanggal_resign, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Skip if employee hasn't started yet relative to system_date
        if tmk_date and tmk_date > system_date:
            continue

        start_year = tmk_date.year if tmk_date else system_date.year
        start_month = tmk_date.month if tmk_date else system_date.month

        # Batasi agar perhitungan pengingat absensi pending di dashboard hanya mulai dari 1 Agustus 2026
        if start_year < 2026 or (start_year == 2026 and start_month < 8):
            start_year = 2026
            start_month = 8

        end_year = system_date.year
        end_month = system_date.month

        # Generate list of (year, month) to check
        periods = []
        curr_y, curr_m = start_year, start_month
        while (curr_y < end_year) or (curr_y == end_year and curr_m <= end_month):
            periods.append((curr_y, curr_m))
            curr_m += 1
            if curr_m > 12:
                curr_m = 1
                curr_y += 1

        for y, m in periods:
            bulan_nama = INV_MONTHS[m]
            jumlah_hari = bulan_days_map.get(bulan_nama, 31)
            if m == 2:
                if (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0):
                    jumlah_hari = 29
                else:
                    jumlah_hari = 28

            k = kehadiran_map.get((karyawan.nik, bulan_nama, y))
            status_hari = k.status_hari if k else {}

            # Get weekends from cache
            if (y, m) not in weekends_by_period:
                w_set = set()
                for d in range(1, jumlah_hari + 1):
                    try:
                        dt = datetime.date(y, m, d)
                        if dt.weekday() in (5, 6):  # Saturday, Sunday
                            w_set.add(d)
                    except ValueError:
                        pass
                weekends_by_period[(y, m)] = w_set
            weekends = weekends_by_period[(y, m)]

            # Get holidays from cache
            holidays = holidays_by_period.get((y, m), set())

            pending_h1_days = []
            pending_lampau_days = []
            for d in range(1, jumlah_hari + 1):
                try:
                    cell_date = datetime.date(y, m, d)
                except ValueError:
                    continue

                # Abaikan tanggal sebelum 1 Agustus 2026
                if cell_date < datetime.date(2026, 8, 1):
                    continue

                # Batasi sampai sebelum waktu sistem (H-1)
                if cell_date >= system_date:
                    continue

                # Jangan dihitung jika sebelum TMK
                if tmk_date and cell_date < tmk_date:
                    continue

                # Jika karyawan resign di/sebelum tanggal ini, lewati
                if resign_date and cell_date >= resign_date:
                    continue

                day_str = str(d)
                db_status = status_hari.get(day_str, '')

                # Jangan masukkan hari libur/weekend ke pending (kecuali masuk 'M')
                if (d in weekends or d in holidays) and db_status != 'M':
                    continue

                if db_status == 'P' or db_status == '':
                    if cell_date == h1_date:
                        pending_h1_days.append(d)
                    else:
                        pending_lampau_days.append(d)

            if pending_h1_days:
                pending_h1_days.sort()
                reminders_h1.append({
                    'nik': karyawan.nik,
                    'absen': karyawan.absen,
                    'nama': karyawan.nama,
                    'bulan': bulan_nama,
                    'tahun': y,
                    'hari': pending_h1_days
                })

            if pending_lampau_days:
                pending_lampau_days.sort()
                reminders_lampau.append({
                    'nik': karyawan.nik,
                    'absen': karyawan.absen,
                    'nama': karyawan.nama,
                    'jabatan': karyawan.jabatan,
                    'bulan': bulan_nama,
                    'tahun': y,
                    'hari': pending_lampau_days
                })

    # Sort reminders by employee name
    reminders_h1.sort(key=lambda x: x['absen'] or 0)
    reminders_lampau.sort(key=lambda x: x['absen'] or 0)

    # Fetch all cuti entries dynamically with expiration info
    # Hanya karyawan aktif (belum resign) yang dihitung jatah cutinya
    existing_cuti = db.session.execute(db.select(Cuti)).scalars().all()
    cuti_map = {c.nik: c for c in existing_cuti}

    # Precompute all balances once
    tahunan_balances = {}
    dinas_balances = {}
    for k in karyawan_list:
        t_info, d_info = get_adjusted_cuti_balances(
            k, system_date,
            kehadiran_entries=kehadiran_by_nik.get(k.nik, []),
            cuti_manual_entries=cuti_manual_by_nik.get(k.nik, []),
            bulan_days_map=bulan_days_map
        )
        tahunan_balances[k.nik] = t_info
        dinas_balances[k.nik] = d_info
    
    for k in karyawan_list:
        tahunan_bal = tahunan_balances[k.nik]['balance']
        dinas_bal = dinas_balances[k.nik]['balance']
        if k.nik in cuti_map:
            c = cuti_map[k.nik]
            c.cuti_tahunan = tahunan_bal
            c.cuti_dinas = dinas_bal
        else:
            c = Cuti(
                nik=k.nik,
                cuti_tahunan=tahunan_bal,
                cuti_dinas=dinas_bal
            )
            c.karyawan = k
            db.session.add(c)
    db.session.commit()
    
    dashboard_cuti_list = []
    cutoff_date = system_date + datetime.timedelta(days=90)
    for k in karyawan_list:
        # Cuti Tahunan Expiration Info
        tahunan_info = tahunan_balances[k.nik]
        t_next = tahunan_info.get('next_expiration_date')
        if t_next and system_date <= t_next <= cutoff_date:
            dashboard_cuti_list.append({
                'nik': k.nik,
                'absen': k.absen,
                'nama': k.nama,
                'jabatan': k.jabatan,
                'jenis_cuti': 'Cuti Tahunan',
                'sisa_saldo': max(0.0, tahunan_info['balance'] - tahunan_info['pending_expiration_amount']),
                'tanggal_hangus': t_next,
                'jumlah_akan_hangus': tahunan_info.get('next_expiration_amount', 0)
            })

        # Cuti Dinas Expiration Info
        dinas_info = dinas_balances[k.nik]
        d_next = dinas_info.get('next_expiration_date')
        if d_next and system_date <= d_next <= cutoff_date:
            dinas_balance_net = dinas_info['balance'] - dinas_info.get('offset', 0)
            if dinas_balance_net > 0:
                dashboard_cuti_list.append({
                    'nik': k.nik,
                    'absen': k.absen,
                    'nama': k.nama,
                    'jabatan': k.jabatan,
                    'jenis_cuti': 'Cuti Dinas',
                    'sisa_saldo': max(0.0, dinas_balance_net - dinas_info['pending_expiration_amount']),
                    'tanggal_hangus': d_next,
                    'jumlah_akan_hangus': min(dinas_balance_net, dinas_info.get('next_expiration_amount', 0))
                })

    dashboard_cuti_list.sort(key=lambda x: x['tanggal_hangus'])

    # Hitung karyawan dengan jatah cuti yang sudah hangus (tahunan atau dinas)
    expired_leaves_list = []
    for k in karyawan_list:
        tahunan_info = tahunan_balances[k.nik]
        pending_hangus = tahunan_info['pending_expiration_amount']
        
        dinas_info = dinas_balances[k.nik]
        pending_dinas = dinas_info['pending_expiration_amount']
        
        if pending_hangus > 0 or pending_dinas > 0:
            expired_leaves_list.append({
                'nik': k.nik,
                'absen': k.absen,
                'nama': k.nama,
                'jabatan': k.jabatan,
                'pending_hangus': pending_hangus,
                'pending_dinas': pending_dinas
            })
    expired_leaves_list.sort(key=lambda x: x['absen'])

    # Hitung karyawan dengan jatah cuti minus (tidak termasuk yang tertutup oleh cuti dinas)
    minus_leaves_list = []
    for k in karyawan_list:
        tahunan_info = tahunan_balances[k.nik]
        tahunan_bal = tahunan_info['balance']
        offset = tahunan_info.get('offset', 0)
        net_bal = tahunan_bal + offset
        if net_bal < 0:
            minus_leaves_list.append({
                'nik': k.nik,
                'absen': k.absen,
                'nama': k.nama,
                'jabatan': k.jabatan,
                'tahunan_balance': net_bal
            })
    minus_leaves_list.sort(key=lambda x: x['absen'] or 0)

    system_bulan = list(MONTH_NUMBERS_GLOBAL.keys())[system_date.month - 1]
    system_tahun = system_date.year
    h1_date_str = f"{h1_date.day} {list(MONTH_NUMBERS_GLOBAL.keys())[h1_date.month - 1]} {h1_date.year}"

    return render_template(
        'sdm/sdm_dashboard.html',
        reminders_h1=reminders_h1,
        reminders_lampau=reminders_lampau,
        cuti_list=dashboard_cuti_list,
        cutoff_date=cutoff_date,
        expired_leaves_list=expired_leaves_list,
        minus_leaves_list=minus_leaves_list,
        system_bulan=system_bulan,
        system_tahun=system_tahun,
        h1_date_str=h1_date_str,
        h1_label=h1_label,
        active_page='sdm-dashboard'
    )

@app.route('/sdm-transaksi')
def sdm_transaksi():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    return render_template('sdm/sdm_transaksi.html', active_page='sdm-transaksi')

@app.route('/sdm-report')
def sdm_report():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    return render_template('sdm/sdm_report.html', active_page='sdm-report')

@app.route('/master-sdm')
def master_sdm():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    return render_template('sdm/master_landing.html', active_page='master-sdm')


@app.route('/master-jabatan', methods=['GET', 'POST'])
def master_jabatan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nama_jabatan = request.form.get('nama', '').strip()
        if not nama_jabatan:
            flash("Nama jabatan tidak boleh kosong!", "danger")
        else:
            exist = db.session.execute(
                db.select(Jabatan).where(db.func.lower(Jabatan.nama) == nama_jabatan.lower())
            ).scalar_one_or_none()
            if exist:
                flash(f"Jabatan '{nama_jabatan}' sudah ada!", "danger")
            else:
                new_jab = Jabatan(
                    nama=nama_jabatan,
                    dilakukan_oleh=session.get('logged_user', 'system')
                )
                db.session.add(new_jab)
                db.session.commit()
                sdm_log("TAMBAH", "JABATAN", f"Menambahkan jabatan baru: {nama_jabatan}")
                flash(f"Jabatan '{nama_jabatan}' berhasil ditambahkan.", "success")
        return redirect(url_for('master_jabatan'))
        
    entries = db.session.execute(
        db.select(Jabatan).order_by(Jabatan.nama)
    ).scalars().all()
    
    return render_template('sdm/master_jabatan.html', entries=entries, active_page='master-sdm')

@app.route('/master-jabatan/delete/<int:id>', methods=['POST'])
def delete_jabatan(id):
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    jab = db.session.get(Jabatan, id)
    if not jab:
        flash("Data jabatan tidak ditemukan!", "danger")
        return redirect(url_for('master_jabatan'))
        
    used = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.jabatan == jab.nama)
    ).first()
    
    if used:
        flash(f"Tidak dapat menghapus jabatan '{jab.nama}' karena sedang digunakan oleh karyawan!", "danger")
    else:
        nama_del = jab.nama
        db.session.delete(jab)
        db.session.commit()
        sdm_log("HAPUS", "JABATAN", f"Menghapus jabatan: {nama_del}")
        flash(f"Jabatan '{nama_del}' berhasil dihapus.", "success")
        
    return redirect(url_for('master_jabatan'))


@app.route('/master-sdm-pt', methods=['GET', 'POST'])
def master_sdm_pt():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nama_pt = request.form.get('nama', '').strip()
        
        if not nama_pt:
            flash("Nama PT wajib diisi!", "danger")
        else:
            exist = db.session.execute(
                db.select(SdmPT).where(db.func.lower(SdmPT.nama) == nama_pt.lower())
            ).scalar_one_or_none()
            if exist:
                flash(f"PT '{nama_pt}' sudah terdaftar!", "danger")
            else:
                new_pt = SdmPT(
                    nama=nama_pt,
                    dilakukan_oleh=session.get('logged_user', 'system')
                )
                db.session.add(new_pt)
                db.session.commit()
                sdm_log("TAMBAH", "PT", f"Menambahkan PT baru: {nama_pt}")
                flash(f"PT '{nama_pt}' berhasil ditambahkan.", "success")
        return redirect(url_for('master_sdm_pt'))
        
    entries = db.session.execute(
        db.select(SdmPT).order_by(SdmPT.nama)
    ).scalars().all()
    
    return render_template('sdm/master_pt.html', entries=entries, active_page='master-sdm')

@app.route('/master-sdm-pt/delete/<int:id>', methods=['POST'])
def delete_sdm_pt(id):
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    pt = db.session.get(SdmPT, id)
    if not pt:
        flash("Data PT tidak ditemukan!", "danger")
        return redirect(url_for('master_sdm_pt'))
        
    # Cek relasi ke data Karyawan
    used_karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.pt == pt.nama)
    ).first()
    
    if used_karyawan:
        flash(f"Tidak dapat menghapus PT '{pt.nama}' karena sedang digunakan oleh data karyawan!", "danger")
    else:
        nama_del = pt.nama
        try:
            db.session.delete(pt)
            db.session.commit()
            sdm_log("HAPUS", "PT", f"Menghapus PT: {nama_del}")
            flash(f"PT '{nama_del}' berhasil dihapus.", "success")
        except Exception as e:
            db.session.rollback()
            if "foreign key" in str(e).lower() or "violates foreign key" in str(e).lower():
                flash(f"Tidak dapat menghapus PT '{nama_del}' karena masih dirujuk oleh data/referensi lain di database.", "danger")
            else:
                flash(f"Terjadi kesalahan saat menghapus PT: {str(e)}", "danger")
        
    return redirect(url_for('master_sdm_pt'))


@app.route('/master-sdm-divisi', methods=['GET', 'POST'])
def master_sdm_divisi():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nama_divisi = request.form.get('nama', '').strip()
        
        if not nama_divisi:
            flash("Nama Divisi wajib diisi!", "danger")
        else:
            exist = db.session.execute(
                db.select(SdmDivisi).where(db.func.lower(SdmDivisi.nama) == nama_divisi.lower())
            ).scalar_one_or_none()
            if exist:
                flash(f"Divisi '{nama_divisi}' sudah terdaftar!", "danger")
            else:
                new_div = SdmDivisi(
                    nama=nama_divisi,
                    dilakukan_oleh=session.get('logged_user', 'system')
                )
                db.session.add(new_div)
                db.session.commit()
                sdm_log("TAMBAH", "DIVISI", f"Menambahkan Divisi baru: {nama_divisi}")
                flash(f"Divisi '{nama_divisi}' berhasil ditambahkan.", "success")
        return redirect(url_for('master_sdm_divisi'))
        
    entries = db.session.execute(
        db.select(SdmDivisi).order_by(SdmDivisi.nama)
    ).scalars().all()
    
    return render_template('sdm/master_divisi.html', entries=entries, active_page='master-sdm')


@app.route('/master-sdm-divisi/delete/<int:id>', methods=['POST'])
def delete_sdm_divisi(id):
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    div = db.session.get(SdmDivisi, id)
    if not div:
        flash("Data Divisi tidak ditemukan!", "danger")
        return redirect(url_for('master_sdm_divisi'))
        
    # Cek relasi ke data Karyawan
    used_karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.divisi == div.nama)
    ).first()
    
    if used_karyawan:
        flash(f"Tidak dapat menghapus Divisi '{div.nama}' karena sedang digunakan oleh data karyawan!", "danger")
    else:
        nama_del = div.nama
        try:
            db.session.delete(div)
            db.session.commit()
            sdm_log("HAPUS", "DIVISI", f"Menghapus Divisi: {nama_del}")
            flash(f"Divisi '{nama_del}' berhasil dihapus.", "success")
        except Exception as e:
            db.session.rollback()
            if "foreign key" in str(e).lower() or "violates foreign key" in str(e).lower():
                flash(f"Tidak dapat menghapus Divisi '{nama_del}' karena masih dirujuk oleh data/referensi lain di database.", "danger")
            else:
                flash(f"Terjadi kesalahan saat menghapus Divisi: {str(e)}", "danger")
        
    return redirect(url_for('master_sdm_divisi'))


@app.route('/master-sdm-departemen', methods=['GET', 'POST'])
def master_sdm_departemen():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nama_dept = request.form.get('nama', '').strip()
        
        if not nama_dept:
            flash("Nama Departemen wajib diisi!", "danger")
        else:
            exist = db.session.execute(
                db.select(SdmDepartemen).where(db.func.lower(SdmDepartemen.nama) == nama_dept.lower())
            ).scalar_one_or_none()
            if exist:
                flash(f"Departemen '{nama_dept}' sudah terdaftar!", "danger")
            else:
                new_dept = SdmDepartemen(
                    nama=nama_dept,
                    dilakukan_oleh=session.get('logged_user', 'system')
                )
                db.session.add(new_dept)
                db.session.commit()
                sdm_log("TAMBAH", "DEPARTEMEN", f"Menambahkan Departemen baru: {nama_dept}")
                flash(f"Departemen '{nama_dept}' berhasil ditambahkan.", "success")
        return redirect(url_for('master_sdm_departemen'))
        
    entries = db.session.execute(
        db.select(SdmDepartemen).order_by(SdmDepartemen.nama)
    ).scalars().all()
    
    return render_template('sdm/master_departemen.html', entries=entries, active_page='master-sdm')


@app.route('/master-sdm-departemen/delete/<int:id>', methods=['POST'])
def delete_sdm_departemen(id):
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    dept = db.session.get(SdmDepartemen, id)
    if not dept:
        flash("Data Departemen tidak ditemukan!", "danger")
        return redirect(url_for('master_sdm_departemen'))
        
    # Cek relasi ke data Karyawan
    used_karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.departemen == dept.nama)
    ).first()
    
    if used_karyawan:
        flash(f"Tidak dapat menghapus Departemen '{dept.nama}' karena sedang digunakan oleh data karyawan!", "danger")
    else:
        nama_del = dept.nama
        try:
            db.session.delete(dept)
            db.session.commit()
            sdm_log("HAPUS", "DEPARTEMEN", f"Menghapus Departemen: {nama_del}")
            flash(f"Departemen '{nama_del}' berhasil dihapus.", "success")
        except Exception as e:
            db.session.rollback()
            if "foreign key" in str(e).lower() or "violates foreign key" in str(e).lower():
                flash(f"Tidak dapat menghapus Departemen '{nama_del}' karena masih dirujuk oleh data/referensi lain di database.", "danger")
            else:
                flash(f"Terjadi kesalahan saat menghapus Departemen: {str(e)}", "danger")
        
    return redirect(url_for('master_sdm_departemen'))


@app.route('/master-karyawan')

def master_karyawan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except Exception:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()

    entries = db.session.execute(
        db.select(KaryawanEntry).order_by(
            KaryawanEntry.pt,
            KaryawanEntry.divisi,
            db.func.coalesce(KaryawanEntry.departemen, ''),
            KaryawanEntry.priority_level.nulls_last(),
            KaryawanEntry.absen
        )
    ).scalars().all()

    for entry in entries:
        is_resign = False
        if entry.tanggal_resign:
            try:
                dt_resign = dt_module.datetime.strptime(entry.tanggal_resign, "%Y-%m-%d").date()
                if dt_resign <= system_date:
                    is_resign = True
            except ValueError:
                pass
        entry.is_actually_resigned = is_resign

    return render_template('sdm/master_karyawan.html', entries=entries, active_page='master-sdm')

@app.route('/db-clear', methods=['POST'])
def db_clear():
    if 'logged_user' not in session or session.get('role') != 'admin':
        flash("Anda tidak memiliki akses untuk melakukan tindakan ini.", "danger")
        return redirect(url_for('login'))
        
    try:
        excluded = {
            "users", 
            "pulau", 
            "kota", 
            "pt", 
            "unit", 
            "nama_asuransi", 
            "merk", 
            "kategori", 
            "bulan", 
            "hari_libur",
            "jabatan"
        }

        # Dapatkan daftar tabel untuk dihapus (mengikuti urutan relasi foreign key)
        sorted_tables = [table for table in db.metadata.sorted_tables if table.name not in excluded]

        # Hapus tabel dengan urutan terbalik (anak tabel terlebih dahulu)
        db.metadata.drop_all(bind=db.engine, tables=reversed(sorted_tables))
        
        # Buat ulang tabel kosong
        db.metadata.create_all(bind=db.engine, tables=sorted_tables)
        
        # Catat aktivitas ke log
        try:
            sdm_log("HAPUS", "DATABASE", f"Membersihkan database (dbclear) oleh user {session.get('logged_user')}")
            db.session.commit()
        except Exception:
            db.session.rollback()
            
        flash("Database berhasil dibersihkan (kecuali data master)!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Gagal membersihkan database: {str(e)}", "danger")
        
    return redirect(url_for('master_karyawan'))

@app.route('/hapus-cuti', methods=['GET', 'POST'])
def hapus_cuti():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    # Resolve system/simulation date
    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()
    tanggal_input = system_date.strftime("%Y-%m-%d")

    if request.method == 'POST':
        action_type = request.form.get('action_type', 'hangus')

        if action_type == 'manual_hangus':
            # Hapus cuti hangus individu
            nik = request.form.get('nik', '').strip().upper()
            jumlah_raw = request.form.get('jumlah', '').strip()
            keterangan = request.form.get('keterangan', '').strip()

            if not (nik and jumlah_raw and keterangan):
                flash("⚠️ Pilih karyawan, isi jumlah hari, dan isi keterangan penghapusan cuti!", "danger")
                return redirect(url_for('hapus_cuti'))

            try:
                jumlah = float(jumlah_raw)
                if jumlah <= 0:
                    raise ValueError
            except ValueError:
                flash("⚠️ Jumlah hari harus berupa angka positif!", "danger")
                return redirect(url_for('hapus_cuti'))

            karyawan = db.session.execute(
                db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
            ).scalar_one_or_none()
            if not karyawan:
                flash("⚠️ Karyawan tidak ditemukan!", "danger")
                return redirect(url_for('hapus_cuti'))

            # Pastikan hanya bisa hapus sejumlah pending_hangus
            balance_info = get_cuti_tahunan_balance(karyawan, system_date)
            pending_hangus = balance_info['pending_expiration_amount']

            if pending_hangus <= 0:
                flash(f"⚠️ {karyawan.nama} tidak memiliki cuti yang sudah hangus!", "danger")
                return redirect(url_for('hapus_cuti'))

            if jumlah > pending_hangus:
                flash(f"⚠️ Jumlah melebihi saldo cuti hangus! Sisa hangus: {pending_hangus} hari.", "danger")
                return redirect(url_for('hapus_cuti'))

            try:
                new_hangus = CutiManual(
                    nik=nik,
                    tanggal_input=tanggal_input,
                    jumlah=jumlah,
                    tipe='HANGUS',
                    keterangan=keterangan
                )
                db.session.add(new_hangus)
                sdm_log('HAPUS_CUTI_HANGUS', 'CUTI', f"Hapus cuti hangus individu {karyawan.nama} ({nik}) sebanyak {jumlah} hari. Ket: {keterangan}", nik=nik, nama_karyawan=karyawan.nama)
                db.session.commit()
                flash(f"✅ Berhasil menghapus {jumlah} hari cuti hangus milik {karyawan.nama}.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"⚠️ Terjadi kesalahan: {str(e)}", "danger")

            return redirect(url_for('hapus_cuti'))

        elif action_type == 'manual_hangus_cd':
            # Hapus cuti dinas hangus individu (total, tanpa klasifikasi periode)
            nik = request.form.get('nik', '').strip().upper()
            jumlah_raw = request.form.get('jumlah', '').strip()
            keterangan = request.form.get('keterangan', '').strip()

            if not (nik and jumlah_raw and keterangan):
                flash("⚠️ Pilih karyawan, isi jumlah hari, dan isi keterangan penghapusan cuti!", "danger")
                return redirect(url_for('hapus_cuti'))

            try:
                jumlah = float(jumlah_raw)
                if jumlah <= 0:
                    raise ValueError
            except ValueError:
                flash("⚠️ Jumlah hari harus berupa angka positif!", "danger")
                return redirect(url_for('hapus_cuti'))

            karyawan = db.session.execute(
                db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
            ).scalar_one_or_none()
            if not karyawan:
                flash("⚠️ Karyawan tidak ditemukan!", "danger")
                return redirect(url_for('hapus_cuti'))

            # Validasi: total saldo hangus cuti dinas
            dinas_info = get_cuti_dinas_balance(karyawan, system_date)
            total_hangus = dinas_info['pending_expiration_amount']

            if total_hangus <= 0:
                flash(f"⚠️ {karyawan.nama} tidak memiliki cuti dinas yang sudah hangus!", "danger")
                return redirect(url_for('hapus_cuti'))

            if jumlah > total_hangus:
                flash(f"⚠️ Jumlah melebihi total saldo cuti dinas hangus! Maksimal: {total_hangus} hari.", "danger")
                return redirect(url_for('hapus_cuti'))

            try:
                new_hangus = CutiManual(
                    nik=nik,
                    tanggal_input=tanggal_input,
                    jumlah=jumlah,
                    tipe='HANGUS_CD',
                    keterangan=keterangan
                )
                db.session.add(new_hangus)
                sdm_log('HAPUS_CUTI_DINAS_HANGUS', 'CUTI', f"Hapus cuti dinas hangus individu {karyawan.nama} ({nik}) sebanyak {jumlah} hari. Ket: {keterangan}", nik=nik, nama_karyawan=karyawan.nama)
                db.session.commit()
                flash(f"✅ Berhasil menghapus {jumlah} hari cuti dinas hangus milik {karyawan.nama}.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"⚠️ Terjadi kesalahan: {str(e)}", "danger")

            return redirect(url_for('hapus_cuti'))

        elif action_type == 'manual':
            nik = request.form.get('nik', '').strip().upper()
            tipe = request.form.get('tipe', '').strip().upper()  # 'CT', 'CD', or 'ADD_CD'
            jumlah_raw = request.form.get('jumlah', '').strip()
            keterangan = request.form.get('keterangan', '').strip()

            if not (nik and tipe and jumlah_raw and keterangan):
                flash("⚠️ Kolom Karyawan, Tipe Aksi Cuti, Jumlah, dan Keterangan wajib diisi!", "danger")
                return redirect(url_for('hapus_cuti'))

            if tipe not in ('CT', 'CD', 'ADD_CD'):
                flash("⚠️ Tipe aksi cuti tidak valid!", "danger")
                return redirect(url_for('hapus_cuti'))

            try:
                jumlah = float(jumlah_raw)
                if jumlah <= 0:
                    raise ValueError
            except ValueError:
                flash("⚠️ Jumlah hari harus berupa angka positif!", "danger")
                return redirect(url_for('hapus_cuti'))

            karyawan = db.session.execute(
                db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
            ).scalar_one_or_none()
            if not karyawan:
                flash("⚠️ Karyawan tidak ditemukan!", "danger")
                return redirect(url_for('hapus_cuti'))

            # Setup period strings
            INDONESIAN_MONTHS = [
                "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
                "Juli", "Agustus", "September", "Oktober", "November", "Desember"
            ]
            ref_period = f"{INDONESIAN_MONTHS[system_date.month]} {system_date.year}"

            if tipe in ('CT', 'CD'):
                t_info, d_info = get_adjusted_cuti_balances(karyawan, system_date)
                if tipe == 'CT':
                    ct_balance = t_info['balance']
                    if ct_balance < jumlah:
                        flash(f"⚠️ Saldo cuti tahunan tidak mencukupi! Sisa: {ct_balance} hari, input: {jumlah} hari.", "danger")
                        return redirect(url_for('hapus_cuti'))
                else:
                    usable_dinas_balance = max(0.0, d_info['balance'] - d_info['pending_expiration_amount'])
                    if usable_dinas_balance < jumlah:
                        flash(f"⚠️ Saldo cuti dinas tidak mencukupi! Sisa aktif: {usable_dinas_balance} hari, input: {jumlah} hari.", "danger")
                        return redirect(url_for('hapus_cuti'))

            try:
                new_manual = CutiManual(
                    nik=nik,
                    tanggal_input=tanggal_input,
                    jumlah=jumlah,
                    tipe=tipe,
                    keterangan=keterangan
                )
                db.session.add(new_manual)
                
                if tipe == 'ADD_CD':
                    sdm_log('TAMBAH_CUTI_DINAS', 'CUTI', f"Tambah cuti dinas {karyawan.nama} ({nik}) sebanyak {jumlah} hari. Ket: {keterangan}", nik=nik, nama_karyawan=karyawan.nama)
                elif tipe == 'CT':
                    sdm_log('POTONG_CUTI_TAHUNAN', 'CUTI', f"Potong cuti tahunan {karyawan.nama} ({nik}) sebanyak {jumlah} hari. Ket: {keterangan}", nik=nik, nama_karyawan=karyawan.nama)
                else:
                    sdm_log('POTONG_CUTI_DINAS', 'CUTI', f"Potong cuti dinas {karyawan.nama} ({nik}) sebanyak {jumlah} hari. Ket: {keterangan}", nik=nik, nama_karyawan=karyawan.nama)
                
                db.session.commit()
                
                if tipe == 'ADD_CD':
                    flash(f"✅ Berhasil mencatat penambahan jatah cuti dinas {karyawan.nama} sebanyak {jumlah} hari untuk periode {ref_period}.", "success")
                elif tipe == 'CT':
                    flash(f"✅ Berhasil memotong jatah cuti tahunan {karyawan.nama} sebanyak {jumlah} hari.", "success")
                else:
                    flash(f"✅ Berhasil memotong jatah cuti dinas {karyawan.nama} sebanyak {jumlah} hari.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"⚠️ Terjadi kesalahan: {str(e)}", "danger")

            return redirect(url_for('hapus_cuti'))

        else:
            # action_type == 'hangus'
            selected_niks = request.form.getlist('niks')

            if not selected_niks:
                flash("⚠️ Pilih minimal satu karyawan untuk dihapus jatah cuti hangusnya!", "danger")
                return redirect(url_for('hapus_cuti'))

            success_count = 0
            error_messages = []

            for nik in selected_niks:
                nik = nik.strip().upper()
                keterangan = request.form.get(f'keterangan_{nik}', '').strip()
                if not keterangan:
                    error_messages.append(f"NIK {nik}: Keterangan penghapusan cuti wajib diisi.")
                    continue

                karyawan = db.session.execute(
                    db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
                ).scalar_one_or_none()
                if not karyawan:
                    error_messages.append(f"NIK {nik}: Keterangan karyawan tidak ditemukan.")
                    continue

                deleted_any = False

                # 1. Hapus Cuti Tahunan Hangus
                jumlah_hangus_raw = request.form.get(f'jumlah_hangus_{nik}', '').strip()
                tahunan_info = get_cuti_tahunan_balance(karyawan, system_date)
                pending_hangus = tahunan_info['pending_expiration_amount']
                
                jumlah_hangus = pending_hangus
                if pending_hangus > 0 and jumlah_hangus_raw:
                    try:
                        jh = float(jumlah_hangus_raw)
                        if jh < 0:
                            raise ValueError
                        if jh > pending_hangus:
                            error_messages.append(f"NIK {nik}: Jumlah cuti tahunan hangus ({jh}) melebihi batas maksimal ({pending_hangus}).")
                            continue
                        jumlah_hangus = jh
                    except ValueError:
                        error_messages.append(f"NIK {nik}: Jumlah cuti tahunan hangus tidak valid.")
                        continue

                if jumlah_hangus > 0:
                    try:
                        ct_keterangan = keterangan or f"Penghapusan cuti hangus massal sebanyak {jumlah_hangus} hari untuk NIK {nik} pada {tanggal_input}"
                        new_hangus = CutiManual(
                            nik=nik,
                            tanggal_input=tanggal_input,
                            jumlah=jumlah_hangus,
                            tipe='HANGUS',
                            keterangan=ct_keterangan
                        )
                        db.session.add(new_hangus)
                        sdm_log('HAPUS_CUTI_HANGUS', 'CUTI', f"Hapus cuti hangus massal {karyawan.nama} ({nik}) sebanyak {jumlah_hangus} hari. Ket: {ct_keterangan}", nik=nik, nama_karyawan=karyawan.nama)
                        deleted_any = True
                    except Exception as e:
                        error_messages.append(f"NIK {nik}: Gagal menghapus cuti tahunan hangus ({str(e)}).")

                # 2. Hapus Cuti Dinas Hangus
                jumlah_dinas_raw = request.form.get(f'jumlah_dinas_{nik}', '').strip()
                dinas_info = get_cuti_dinas_balance(karyawan, system_date)
                pending_dinas = dinas_info['pending_expiration_amount']
                
                jumlah_dinas = pending_dinas
                if pending_dinas > 0 and jumlah_dinas_raw:
                    try:
                        jd = float(jumlah_dinas_raw)
                        if jd < 0:
                            raise ValueError
                        if jd > pending_dinas:
                            error_messages.append(f"NIK {nik}: Jumlah cuti dinas hangus ({jd}) melebihi batas maksimal ({pending_dinas}).")
                            continue
                        jumlah_dinas = jd
                    except ValueError:
                        error_messages.append(f"NIK {nik}: Jumlah cuti dinas hangus tidak valid.")
                        continue

                if jumlah_dinas > 0:
                    remaining_to_delete = jumlah_dinas
                    for d in dinas_info['detail']:
                        if remaining_to_delete <= 0:
                            break
                        period = d['period']
                        expired_amt = d['expired_amount']
                        if expired_amt > 0:
                            to_delete_this_period = min(expired_amt, remaining_to_delete)
                            try:
                                cd_keterangan = f"{period}|{keterangan or f'Penghapusan cuti dinas hangus massal sebanyak {to_delete_this_period} hari untuk NIK {nik} periode {period} pada {tanggal_input}'}"
                                new_cd_hangus = CutiManual(
                                    nik=nik,
                                    tanggal_input=tanggal_input,
                                    jumlah=to_delete_this_period,
                                    tipe='HANGUS_CD',
                                    keterangan=cd_keterangan
                                )
                                db.session.add(new_cd_hangus)
                                sdm_log('HAPUS_CUTI_DINAS_HANGUS', 'CUTI', f"Hapus cuti dinas hangus massal {karyawan.nama} ({nik}) sebanyak {to_delete_this_period} hari. Ket: {cd_keterangan}", nik=nik, nama_karyawan=karyawan.nama)
                                remaining_to_delete -= to_delete_this_period
                                deleted_any = True
                            except Exception as e:
                                error_messages.append(f"NIK {nik} (Periode {period}): Gagal menghapus cuti dinas hangus ({str(e)}).")

                if deleted_any:
                    success_count += 1

            try:
                if success_count > 0:
                    sdm_log('HAPUS_CUTI_HANGUS', 'CUTI', f"Hapus cuti hangus massal: {success_count} karyawan berhasil, {len(error_messages)} gagal.")
                db.session.commit()
                if success_count > 0:
                    flash(f"✅ Berhasil menghapus jatah cuti hangus untuk {success_count} karyawan.", "success")
                if error_messages:
                    flash(f"⚠️ Beberapa data gagal diproses:<br>" + "<br>".join(error_messages), "danger")
            except Exception as e:
                db.session.rollback()
                flash(f"⚠️ Terjadi kesalahan database: {str(e)}", "danger")

            return redirect(url_for('hapus_cuti'))

    # GET — ambil semua karyawan aktif
    import datetime as dt_module
    all_k = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()
    karyawan_list = []
    for k in all_k:
        if k.tanggal_resign:
            try:
                dt_resign = dt_module.datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                if dt_resign <= system_date:
                    continue
            except ValueError:
                pass
        karyawan_list.append(k)

    # Tampilkan semua karyawan aktif di tabel bulk
    expired_employees = []
    for k in karyawan_list:
        balance_info = get_cuti_tahunan_balance(k, system_date)
        pending_hangus = balance_info['pending_expiration_amount']
        
        dinas_info = get_cuti_dinas_balance(k, system_date)
        pending_dinas = int(dinas_info['pending_expiration_amount'])
        
        expired_employees.append({
            'nik': k.nik,
            'absen': k.absen,
            'nama': k.nama,
            'pending_hangus': pending_hangus,
            'pending_dinas': pending_dinas
        })

    return render_template(
        'sdm/hapus_cuti.html',
        karyawan_list=karyawan_list,
        expired_employees=expired_employees,
        system_date=tanggal_input,
        active_page='sdm-transaksi'
    )


@app.route('/hapus-cuti/delete/<int:log_id>', methods=['POST'])
def hapus_cuti_delete(log_id):
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    adjustment = db.session.get(CutiManual, log_id)
    if not adjustment or adjustment.tipe not in ('HANGUS', 'HANGUS_CD'):
        flash("⚠️ Riwayat penghapusan tidak ditemukan!", "danger")
        return redirect(url_for('hapus_cuti'))

    nama_karyawan = adjustment.nama
    jumlah = adjustment.jumlah

    try:
        db.session.delete(adjustment)
        db.session.commit()
        flash(f"✅ Berhasil membatalkan penghapusan cuti hangus {nama_karyawan} sebanyak {jumlah} hari.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Gagal membatalkan penghapusan: {str(e)}", "danger")

    return redirect(url_for('hapus_cuti'))

@app.route('/logs-cuti')
def view_cuti_audit_logs():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    page = request.args.get('page', 1, type=int)
    per_page = 30
    offset = (page - 1) * per_page
    
    q = request.args.get('q', '').strip()
    
    stmt = db.select(SdmActivityLog)
    if q:
        search_filter = f"%{q}%"
        stmt = stmt.where(
            db.or_(
                SdmActivityLog.aksi.ilike(search_filter),
                SdmActivityLog.nik.ilike(search_filter),
                SdmActivityLog.nama_karyawan.ilike(search_filter),
                SdmActivityLog.detail.ilike(search_filter),
                SdmActivityLog.dilakukan_oleh.ilike(search_filter)
            )
        )
        
    stmt = stmt.order_by(SdmActivityLog.id.desc())
    
    total_count = db.session.execute(
        db.select(db.func.count()).select_from(stmt.subquery())
    ).scalar() or 0
    
    all_logs = db.session.execute(
        stmt.limit(per_page).offset(offset)
    ).scalars().all()
    
    total_pages = (total_count + per_page - 1) // per_page

    return render_template(
        'sdm/logs_cuti.html',
        logs=all_logs,
        q=q,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        active_page='sdm-logs'
    )


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
            import datetime as dt_module
            
            dt_resign = datetime.strptime(tanggal_resign_str, "%Y-%m-%d")
            year = dt_resign.year
            month_num = dt_resign.month
            day_resign = dt_resign.day

            # Validasi: tanggal resign paling cepat 1 bulan dari hari sistem
            if 'simulation_date' in session:
                try:
                    system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
                except Exception:
                    system_date = dt_module.date.today()
            else:
                system_date = dt_module.date.today()

            if system_date.month == 12:
                next_month = 1
                next_year = system_date.year + 1
            else:
                next_month = system_date.month + 1
                next_year = system_date.year
            _, max_days = calendar.monthrange(next_year, next_month)
            target_day = min(system_date.day, max_days)
            min_date = dt_module.date(next_year, next_month, target_day)

            if dt_resign.date() < min_date:
                flash(f"⚠️ Tanggal resign paling cepat adalah 1 bulan dari hari ini ({min_date.strftime('%d-%m-%Y')})!", "danger")
                return redirect(url_for('nonaktifkan_karyawan'))

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
            
            sdm_log('RESIGN', 'KARYAWAN', f"Karyawan '{karyawan.nama}' (NIK: {nik}) dinonaktifkan per {tanggal_resign_str}.", nik=nik, nama_karyawan=karyawan.nama)
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

    # Tentukan tanggal minimum untuk date picker (1 bulan dari hari sistem / simulation date)
    import datetime as dt_module
    import calendar
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except Exception:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()

    if system_date.month == 12:
        next_month = 1
        next_year = system_date.year + 1
    else:
        next_month = system_date.month + 1
        next_year = system_date.year
    _, max_days = calendar.monthrange(next_year, next_month)
    target_day = min(system_date.day, max_days)
    min_date = dt_module.date(next_year, next_month, target_day)

    return render_template(
        'sdm/nonaktifkan_karyawan.html',
        karyawan_list=karyawan_list,
        min_date=min_date.strftime('%Y-%m-%d'),
        active_page='sdm-transaksi'
    )

@app.route('/master-cuti')
def master_cuti():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    # Resolve system/simulation date to get current period
    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()

    # Hanya tampilkan karyawan aktif (belum resign)
    all_k = db.session.execute(
        db.select(KaryawanEntry).order_by(
            KaryawanEntry.pt,
            KaryawanEntry.divisi,
            db.func.coalesce(KaryawanEntry.departemen, ''),
            KaryawanEntry.priority_level.nulls_last(),
            KaryawanEntry.absen
        )
    ).scalars().all()
    karyawan_list = []
    for k in all_k:
        if k.tanggal_resign:
            try:
                dt_resign = dt_module.datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                if dt_resign <= system_date:
                    continue
            except ValueError:
                pass
        karyawan_list.append(k)
        
    INDONESIAN_MONTHS = [
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    current_period = f"{INDONESIAN_MONTHS[system_date.month]} {system_date.year}"

    existing_cuti = db.session.execute(
        db.select(Cuti)
    ).scalars().all()
    
    cuti_map = {c.nik: c for c in existing_cuti}

    # Fetch cache
    all_kehadiran = db.session.execute(db.select(Kehadiran)).scalars().all()
    all_cuti_manual = db.session.execute(db.select(CutiManual)).scalars().all()
    bulan_list = db.session.execute(db.select(Bulan)).scalars().all()
    
    from collections import defaultdict
    kehadiran_by_nik = defaultdict(list)
    for kh in all_kehadiran:
        kehadiran_by_nik[kh.nik].append(kh)

    cuti_manual_by_nik = defaultdict(list)
    for cm in all_cuti_manual:
        cuti_manual_by_nik[cm.nik].append(cm)

    bulan_days_map = {b.nama: b.jumlah_hari for b in bulan_list}

    entries = []
    for k in karyawan_list:
        balance_info, dinas_info = get_adjusted_cuti_balances(
            k, system_date,
            kehadiran_entries=kehadiran_by_nik.get(k.nik, []),
            cuti_manual_entries=cuti_manual_by_nik.get(k.nik, []),
            bulan_days_map=bulan_days_map
        )
        tahunan_bal = balance_info['balance']
        dinas_bal = dinas_info['balance']
        
        if k.nik in cuti_map:
            c = cuti_map[k.nik]
            c.cuti_tahunan = tahunan_bal
            c.cuti_dinas = dinas_bal
        else:
            c = Cuti(
                nik=k.nik,
                cuti_tahunan=tahunan_bal,
                cuti_dinas=dinas_bal
            )
            db.session.add(c)
            
        entry_data = {
            'nik': k.nik,
            'nama': k.nama,
            'tmk': k.tmk,
            'tahunan_jatah': balance_info.get('period_accrued', balance_info['accrued']),
            'tahunan_used': balance_info.get('used_leaves', 0),
            'tahunan_potong': balance_info.get('potong_cuti', 0),
            'tahunan_sisa': tahunan_bal,
            'tahunan_offset': balance_info.get('offset', 0),
            'dinas_jatah': dinas_info['added'],
            'dinas_used': dinas_info['used'],
            'dinas_sisa': dinas_bal,
            'dinas_offset': dinas_info.get('offset', 0)
        }
        entries.append(entry_data)
        
    db.session.commit()

            
    return render_template(
        'sdm/master_cuti.html',
        entries=entries,
        system_date=system_date.strftime("%Y-%m-%d"),
        current_period=current_period,
        active_page='master-sdm'
    )

@app.route('/master-cuti/api/balance/<nik>')
def api_get_cuti_balance(nik):
    if 'logged_user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    date_str = request.args.get('date')
    try:
        ref_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        if 'simulation_date' in session:
            try:
                ref_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
            except Exception:
                ref_date = datetime.date.today()
        else:
            ref_date = datetime.date.today()
            
    karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    if not karyawan:
        return jsonify({'success': False, 'message': 'Karyawan tidak ditemukan'}), 404
        
    tahunan_info, dinas_info = get_adjusted_cuti_balances(karyawan, ref_date)
    dinas_hangus_info = get_cuti_dinas_hangus(nik, ref_date)
    
    return jsonify({
        'success': True,
        'cuti_tahunan_balance': tahunan_info['balance'],
        'cuti_dinas_balance': max(0.0, dinas_info['balance']),
        'cuti_dinas_total': dinas_info['added'],
        'cuti_dinas_used': dinas_info['used'],
        'pending_expiration_amount': tahunan_info['pending_expiration_amount'],
        'pending_dinas_hangus': dinas_hangus_info['total_hangus'],
        'dinas_hangus_detail': [
            {
                'period': d['period'],
                'expired_amount': d['expired_amount'],
                'period_end': d['period_end'].strftime('%d %b %Y')
            }
            for d in dinas_hangus_info['detail']
        ]
    })


@app.route('/master-cuti/detail/<nik>')
def detail_cuti(nik):
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()
        
    karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    if not karyawan:
        flash("⚠️ Karyawan tidak ditemukan!", "danger")
        return redirect(url_for('master_cuti'))
        
    tahunan_info, dinas_info = get_adjusted_cuti_balances(karyawan, system_date)
    
    # Process Cuti Tahunan Accruals
    tahunan_list = []
    for acc in tahunan_info.get('accruals', []):
        if acc['remaining'] > 0 and acc['expiration'] > system_date:
            tahunan_list.append({
                'date': acc['date'].strftime('%Y-%m-%d') if hasattr(acc['date'], 'strftime') else str(acc['date']),
                'expiration': acc['expiration'].strftime('%Y-%m-%d') if hasattr(acc['expiration'], 'strftime') else str(acc['expiration']),
                'amount': acc['amount'],
                'remaining': acc['remaining'],
                'keterangan': f"Akrual Cuti Tahunan"
            })
        
    # Process Cuti Dinas Allocations
    dinas_list = []
    for acc in dinas_info.get('allocations', []):
        if acc['remaining'] > 0 and acc['expiration'] > system_date:
            dinas_list.append({
                'date': acc['date'].strftime('%Y-%m-%d') if hasattr(acc['date'], 'strftime') else str(acc['date']),
                'expiration': acc['expiration'].strftime('%Y-%m-%d') if hasattr(acc['expiration'], 'strftime') else str(acc['expiration']),
                'amount': acc['amount'],
                'remaining': acc['remaining'],
                'keterangan': acc.get('keterangan') or 'Penambahan Cuti Dinas'
            })
        
    tahunan_list.sort(key=lambda x: x['date'], reverse=True)
    dinas_list.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template(
        'sdm/detail_cuti.html',
        karyawan=karyawan,
        tahunan_list=tahunan_list,
        dinas_list=dinas_list,
        tahunan_balance=tahunan_info['balance'],
        dinas_balance=max(0.0, dinas_info['balance'] - dinas_info['pending_expiration_amount']),
        active_page='master-sdm'
    )


@app.route('/tambah-cuti-dinas', methods=['GET', 'POST'])
def tambah_cuti_dinas():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    # Resolve system/simulation date
    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()
    tanggal_input = system_date.strftime("%Y-%m-%d")

    INDONESIAN_MONTHS = [
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    ref_period = f"{INDONESIAN_MONTHS[system_date.month]} {system_date.year}"

    if request.method == 'POST':
        nik = request.form.get('nik', '').strip().upper()
        jumlah_raw = request.form.get('jumlah', '').strip()
        keterangan = request.form.get('keterangan', '').strip()
        tanggal_kadaluarsa = request.form.get('tanggal_kadaluarsa', '').strip()
        
        if not (nik and jumlah_raw and tanggal_kadaluarsa and keterangan):
            flash("⚠️ Kolom Karyawan, Jumlah, Tanggal Kadaluarsa, dan Keterangan wajib diisi!", "danger")
            return redirect(url_for('tambah_cuti_dinas'))
            
        try:
            jumlah_val = float(jumlah_raw)
            if jumlah_val <= 0 or not jumlah_val.is_integer():
                raise ValueError
            jumlah = int(jumlah_val)
        except ValueError:
            flash("⚠️ Jumlah hari harus berupa angka bulat positif!", "danger")
            return redirect(url_for('tambah_cuti_dinas'))
            
        try:
            dt_kadaluarsa = dt_module.datetime.strptime(tanggal_kadaluarsa, "%Y-%m-%d").date()
            dt_input = dt_module.datetime.strptime(tanggal_input, "%Y-%m-%d").date()
            min_allowed = dt_input + dt_module.timedelta(days=30)
            if dt_kadaluarsa < min_allowed:
                flash(f"⚠️ Tanggal kadaluarsa tidak boleh kurang dari 30 hari dari tanggal input (minimal {min_allowed.strftime('%Y-%m-%d')})!", "danger")
                return redirect(url_for('tambah_cuti_dinas'))
        except ValueError:
            flash("⚠️ Format tanggal kadaluarsa tidak valid!", "danger")
            return redirect(url_for('tambah_cuti_dinas'))
            
        karyawan = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
        ).scalar_one_or_none()
        if not karyawan:
            flash("⚠️ Karyawan tidak ditemukan!", "danger")
            return redirect(url_for('tambah_cuti_dinas'))
            
        if not keterangan:
            keterangan = f"Penambahan cuti dinas sebanyak {jumlah_raw} hari untuk NIK {nik} pada {tanggal_input} (kadaluarsa {tanggal_kadaluarsa})"
            
        try:
            new_add_cd = CutiManual(
                nik=nik,
                tanggal_input=tanggal_input,
                jumlah=jumlah,
                tipe='ADD_CD',
                keterangan=keterangan,
                tanggal_kadaluarsa=tanggal_kadaluarsa
            )
            db.session.add(new_add_cd)
            sdm_log('TAMBAH_CUTI_DINAS', 'CUTI', f"Tambah cuti dinas {karyawan.nama} ({nik}) sebanyak {jumlah} hari periode {ref_period} (kadaluarsa {tanggal_kadaluarsa}). Ket: {keterangan}", nik=nik, nama_karyawan=karyawan.nama)
            db.session.commit()
            flash(f"✅ Transaksi berhasil: Jatah Cuti Dinas {karyawan.nama} ditambahkan sebanyak {jumlah} hari (berlaku s.d. {tanggal_kadaluarsa}).", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"⚠️ Terjadi kesalahan database: {str(e)}", "danger")
            
        return redirect(url_for('tambah_cuti_dinas'))
        
    import datetime as dt_module
    all_k = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()
    karyawan_list = []
    for k in all_k:
        if k.tanggal_resign:
            try:
                dt_resign = dt_module.datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                if dt_resign <= system_date:
                    continue
            except ValueError:
                pass
        karyawan_list.append(k)
    
    min_kadaluarsa = (system_date + dt_module.timedelta(days=30)).strftime("%Y-%m-%d")
    
    return render_template(
        'sdm/tambah_cuti_dinas.html',
        karyawan_list=karyawan_list,
        system_date=tanggal_input,
        min_kadaluarsa=min_kadaluarsa,
        current_period=ref_period,
        active_page='sdm-transaksi'
    )

def parse_date_dmy_or_ymd(date_str):
    if not date_str:
        return None
    import datetime as dt_module
    date_str = date_str.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d%m%Y"):
        try:
            return dt_module.datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {date_str}")

@app.route('/form-ba', methods=['GET', 'POST'])
def form_ba():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    # Resolve system/simulation date
    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()
        
    tanggal_input = system_date.strftime("%d-%m-%Y")

    if request.method == 'POST':
        entry_id_raw = request.form.get('entry_id')
        tanggal_kadaluarsa_baru = request.form.get('tanggal_kadaluarsa_baru')
        ba_nomor = request.form.get('ba_nomor', '').strip()
        ba_tanggal = request.form.get('ba_tanggal', '').strip()
        ba_keterangan = request.form.get('ba_keterangan', '').strip()
        
        if not (entry_id_raw and tanggal_kadaluarsa_baru and ba_tanggal and ba_keterangan):
            flash("⚠️ Kolom ID Transaksi, Tanggal Kadaluarsa Baru, Tanggal BA, dan Keterangan BA wajib diisi!", "danger")
            return redirect(url_for('form_ba'))
            
        try:
            entry_id = int(entry_id_raw)
        except ValueError:
            flash("⚠️ ID transaksi tidak valid!", "danger")
            return redirect(url_for('form_ba'))
            
        entry = db.session.get(CutiManual, entry_id)
        if not entry or entry.tipe != 'ADD_CD':
            flash("⚠️ Transaksi cuti dinas tidak ditemukan!", "danger")
            return redirect(url_for('form_ba'))

        try:
            dt_ba = parse_date_dmy_or_ymd(ba_tanggal)
            if dt_ba < system_date:
                flash(f"⚠️ Tanggal Berita Acara ({ba_tanggal}) tidak boleh kurang dari hari ini ({tanggal_input})!", "danger")
                return redirect(url_for('form_ba'))
        except ValueError:
            flash("⚠️ Format tanggal Berita Acara tidak valid!", "danger")
            return redirect(url_for('form_ba'))
            
        karyawan = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.nik == entry.nik)
        ).scalar_one_or_none()
        if not karyawan:
            flash("⚠️ Karyawan tidak ditemukan!", "danger")
            return redirect(url_for('form_ba'))
            
        # Parse TMK date
        raw_tmk = None
        for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
            try:
                raw_tmk = dt_module.datetime.strptime(karyawan.tmk.strip(), fmt).date()
                break
            except (ValueError, AttributeError):
                continue
                
        if not raw_tmk:
            flash("⚠️ Data TMK karyawan tidak valid untuk perhitungan batas!", "danger")
            return redirect(url_for('form_ba'))
            
        tmk_date = dt_module.date(raw_tmk.year, raw_tmk.month, 1)
        try:
            m_date = dt_module.datetime.strptime(entry.tanggal_input, "%Y-%m-%d").date()
        except Exception:
            m_date = system_date
            
        # Cari E_n (batas maksimum umur cuti tahunan periode tersebut)
        n = 1
        while True:
            max_limit = add_months(tmk_date, 28 + 12 * (n - 1))
            if max_limit >= m_date:
                break
            n += 1
            
        try:
            dt_baru = parse_date_dmy_or_ymd(tanggal_kadaluarsa_baru)
            dt_lama = parse_date_dmy_or_ymd(entry.tanggal_kadaluarsa)
            if dt_baru < dt_lama:
                flash(f"⚠️ Tanggal kadaluarsa baru ({tanggal_kadaluarsa_baru}) tidak boleh kurang dari tanggal kadaluarsa lama ({dt_lama.strftime('%d-%m-%Y')})!", "danger")
                return redirect(url_for('form_ba'))
            if dt_baru > max_limit:
                flash(f"⚠️ Tanggal kadaluarsa baru ({tanggal_kadaluarsa_baru}) tidak boleh melebihi batas masa berlaku cuti tahunan periode tersebut ({max_limit.strftime('%d-%m-%Y')})!", "danger")
                return redirect(url_for('form_ba'))
        except ValueError:
            flash("⚠️ Format tanggal kadaluarsa baru tidak valid!", "danger")
            return redirect(url_for('form_ba'))

        try:
            entry.tanggal_kadaluarsa = dt_baru.strftime("%Y-%m-%d")
            entry.ba_nomor = ba_nomor
            entry.ba_tanggal = dt_ba.strftime("%Y-%m-%d")
            entry.ba_keterangan = ba_keterangan
            db.session.commit()
            
            # Log action
            from sdm import sdm_log
            sdm_log('PERPANJANG_CUTI_DINAS', 'CUTI', f"Perpanjang cuti dinas {karyawan.nama} ({entry.nik}) s.d. {dt_baru.strftime('%d-%m-%Y')} dengan BA Tanggal {dt_ba.strftime('%d-%m-%Y')}.", nik=entry.nik, nama_karyawan=karyawan.nama)
            
            flash(f"🎉 Sukses memperpanjang cuti dinas {karyawan.nama} s.d. {dt_baru.strftime('%d-%m-%Y')} berdasarkan BA Tanggal {dt_ba.strftime('%d-%m-%Y')}!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"⚠️ Gagal menyimpan perpanjangan: {str(e)}", "danger")
            
        return redirect(url_for('form_ba'))

    # GET: Get all active employees (excluding resigned ones)
    all_k = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()
    karyawan_list = []
    for k in all_k:
        if k.tanggal_resign:
            try:
                dt_resign = dt_module.datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                if dt_resign <= system_date:
                    continue
            except ValueError:
                pass
        karyawan_list.append(k)
        
    return render_template(
        'sdm/form_ba.html',
        karyawan_list=karyawan_list,
        system_date=tanggal_input,
        system_date_ymd=system_date.strftime("%Y-%m-%d"),
        active_page='sdm-transaksi'
    )

@app.route('/form-ba/api/cuti-dinas/<nik>')
def form_ba_api_cuti_dinas(nik):
    if 'logged_user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    if not karyawan:
        return jsonify({'success': False, 'message': 'Karyawan tidak ditemukan'}), 404
        
    add_manuals = db.session.execute(
        db.select(CutiManual).where(
            CutiManual.nik == nik,
            CutiManual.tipe == 'ADD_CD'
        ).order_by(CutiManual.tanggal_input.desc())
    ).scalars().all()
    
    import datetime as dt_module
    raw_tmk = None
    for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
        try:
            raw_tmk = dt_module.datetime.strptime(karyawan.tmk.strip(), fmt).date()
            break
        except (ValueError, AttributeError):
            continue
            
    if not raw_tmk:
        return jsonify({'success': True, 'entries': []})
        
    tmk_date = dt_module.date(raw_tmk.year, raw_tmk.month, 1)
    
    entries_data = []
    for m in add_manuals:
        try:
            m_date = dt_module.datetime.strptime(m.tanggal_input, "%Y-%m-%d").date()
        except Exception:
            continue
            
        n = 1
        while True:
            max_limit = add_months(tmk_date, 28 + 12 * (n - 1))
            if max_limit >= m_date:
                break
            n += 1
            
        entries_data.append({
            'id': m.id,
            'tanggal_input': m.tanggal_input,
            'jumlah': m.jumlah,
            'keterangan': m.keterangan or '',
            'tanggal_kadaluarsa': m.tanggal_kadaluarsa or max_limit.strftime("%Y-%m-%d"),
            'max_extension_date': max_limit.strftime("%Y-%m-%d"),
            'ba_nomor': m.ba_nomor or '',
            'ba_tanggal': m.ba_tanggal or '',
            'ba_keterangan': m.ba_keterangan or ''
        })
        
    return jsonify({'success': True, 'entries': entries_data})

@app.route('/generate-laporan', methods=['GET'])
def generate_laporan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    import datetime
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass

    INDONESIAN_MONTHS = [
        'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ]
    default_bulan_nama = INDONESIAN_MONTHS[system_date.month - 1]
    default_tahun = system_date.year

    selected_bulan = request.args.get('bulan', '').strip()
    if not selected_bulan:
        selected_bulan = default_bulan_nama
        
    selected_tahun_str = request.args.get('tahun', '').strip()
    if not selected_tahun_str:
        selected_tahun = default_tahun
    else:
        try:
            selected_tahun = int(selected_tahun_str)
        except ValueError:
            selected_tahun = default_tahun

    selected_pt = request.args.get('pt', '').strip()
    selected_divisi = request.args.get('divisi', '').strip()
    selected_jabatan = request.args.get('jabatan', '').strip()

    # Get Bulan meta to calculate jumlah_hari
    bulan_meta = db.session.execute(db.select(Bulan).where(Bulan.nama == selected_bulan)).scalar_one_or_none()
    jumlah_hari = bulan_meta.jumlah_hari if bulan_meta else 31
    if selected_bulan == 'Februari':
        if (selected_tahun % 4 == 0 and selected_tahun % 100 != 0) or (selected_tahun % 400 == 0):
            jumlah_hari = 29
        else:
            jumlah_hari = 28

    # Query all active employees for this period
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    view_month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    filtered_karyawan_list = []
    for k in karyawan_list:
        if k.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                if selected_tahun > dt_resign.year:
                    continue
                if selected_tahun == dt_resign.year and view_month_num > dt_resign.month:
                    continue
            except ValueError:
                pass
        if k.tmk:
            try:
                dt_tmk = None
                for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
                    try:
                        dt_tmk = datetime.datetime.strptime(k.tmk.strip(), fmt).date()
                        break
                    except ValueError:
                        pass
                if dt_tmk:
                    if selected_tahun < dt_tmk.year:
                        continue
                    if selected_tahun == dt_tmk.year and view_month_num < dt_tmk.month:
                        continue
            except Exception:
                pass
        filtered_karyawan_list.append(k)

    # Filter tambahan: PT, Divisi, Jabatan
    if selected_pt:
        filtered_karyawan_list = [k for k in filtered_karyawan_list if (k.pt or '') == selected_pt]
    if selected_divisi:
        filtered_karyawan_list = [k for k in filtered_karyawan_list if (k.divisi or '') == selected_divisi]
    if selected_jabatan:
        filtered_karyawan_list = [k for k in filtered_karyawan_list if (k.jabatan or '') == selected_jabatan]

    # Ambil daftar unik PT / Divisi / Jabatan dari semua karyawan (untuk dropdown)
    all_karyawan_for_filter = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()
    list_pt = sorted(set(k.pt for k in all_karyawan_for_filter if k.pt))
    list_divisi = sorted(set(k.divisi for k in all_karyawan_for_filter if k.divisi))
    list_jabatan = sorted(set(k.jabatan for k in all_karyawan_for_filter if k.jabatan))

    # Ambil data kehadiran dari DB yang sudah ada untuk periode terpilih
    existing_entries = db.session.execute(
        db.select(Kehadiran)
        .where(Kehadiran.bulan == selected_bulan, Kehadiran.tahun == selected_tahun)
    ).scalars().all()
    kehadiran_map = {e.nik: e for e in existing_entries}

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
    all_holidays = db.session.execute(db.select(HariLibur)).scalars().all()
    holiday_days = {}
    for h in all_holidays:
        if h.tanggal.month == view_month_num and h.tanggal.year == selected_tahun:
            holiday_days[h.tanggal.day] = h.keterangan

    # Cek pending entries untuk karyawan terdaftar
    pending_list = []
    for k in filtered_karyawan_list:
        entry = kehadiran_map.get(k.nik)
        
        # Cari tanggal tmk
        days_before_tmk = set()
        if k.tmk:
            tmk_date = None
            for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                try:
                    tmk_date = datetime.datetime.strptime(k.tmk.strip(), fmt).date()
                    break
                except ValueError:
                    pass
            if tmk_date:
                for d in range(1, jumlah_hari + 1):
                    try:
                        cell_date = datetime.date(selected_tahun, view_month_num, d)
                        if cell_date < tmk_date:
                            days_before_tmk.add(d)
                    except ValueError:
                        pass

        # Cari hari pending
        status_dict = entry.status_hari if entry and entry.status_hari else {}
        pending_days = []
        for d in range(1, jumlah_hari + 1):
            if d in days_before_tmk:
                continue
            try:
                cell_date = datetime.date(selected_tahun, view_month_num, d)
            except ValueError:
                continue
            if cell_date < system_date:
                is_weekend = d in weekends
                is_holiday = d in holiday_days
                if not is_weekend and not is_holiday:
                    db_status = status_dict.get(str(d), '')
                    if not db_status or db_status == 'P':
                        pending_days.append(d)
                        
        if pending_days:
            pending_list.append({
                'nik': k.nik,
                'absen': k.absen,
                'nama': k.nama,
                'days': sorted(pending_days)
            })

    # Calculate last day of month and check if month has ended
    last_day_of_month = datetime.date(selected_tahun, view_month_num, jumlah_hari)
    month_ended = system_date > last_day_of_month
    next_day = last_day_of_month + datetime.timedelta(days=1)
    next_day_str = f"{next_day.day} {INDONESIAN_MONTHS[next_day.month - 1]} {next_day.year}"

    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()
    
    return render_template(
        'sdm/generate_laporan.html',
        list_bulan=list_bulan,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        has_pending=len(pending_list) > 0,
        pending_list=pending_list,
        month_ended=month_ended,
        next_day_str=next_day_str,
        list_pt=list_pt,
        list_divisi=list_divisi,
        list_jabatan=list_jabatan,
        selected_pt=selected_pt,
        selected_divisi=selected_divisi,
        selected_jabatan=selected_jabatan,
        active_page='sdm-report'
    )

@app.route('/generate-laporan/download', methods=['GET', 'POST'])
@csrf.exempt
def download_laporan():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    import datetime
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass

    selected_bulan = request.values.get('bulan', '').strip()
    selected_tahun_str = request.values.get('tahun', '').strip()
    selected_pt = request.values.get('pt', '').strip()
    selected_divisi = request.values.get('divisi', '').strip()
    selected_jabatan = request.values.get('jabatan', '').strip()
    
    if not selected_bulan or not selected_tahun_str:
        flash("⚠️ Periode laporan tidak valid!", "danger")
        return redirect(url_for('generate_laporan'))
        
    try:
        selected_tahun = int(selected_tahun_str)
    except ValueError:
        flash("⚠️ Tahun tidak valid!", "danger")
        return redirect(url_for('generate_laporan'))

    # Get Bulan meta to calculate jumlah_hari
    bulan_meta = db.session.execute(db.select(Bulan).where(Bulan.nama == selected_bulan)).scalar_one_or_none()
    jumlah_hari = bulan_meta.jumlah_hari if bulan_meta else 31
    if selected_bulan == 'Februari':
        if (selected_tahun % 4 == 0 and selected_tahun % 100 != 0) or (selected_tahun % 400 == 0):
            jumlah_hari = 29
        else:
            jumlah_hari = 28

    # Query all active employees for this period
    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(KaryawanEntry.absen)
    ).scalars().all()

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    view_month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    # Check if month has ended relative to system_date
    INDONESIAN_MONTHS = [
        'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ]
    last_day_of_month = datetime.date(selected_tahun, view_month_num, jumlah_hari)
    if system_date <= last_day_of_month:
        next_day = last_day_of_month + datetime.timedelta(days=1)
        next_day_str = f"{next_day.day} {INDONESIAN_MONTHS[next_day.month - 1]} {next_day.year}"
        flash(f"⚠️ Periode belum berakhir! Laporan {selected_bulan} {selected_tahun} hanya dapat diunduh mulai tanggal {next_day_str}.", "danger")
        return redirect(url_for('generate_laporan', bulan=selected_bulan, tahun=selected_tahun))

    filtered_karyawan_list = []
    for k in karyawan_list:
        if k.tanggal_resign:
            try:
                dt_resign = datetime.datetime.strptime(k.tanggal_resign, "%Y-%m-%d").date()
                if selected_tahun > dt_resign.year:
                    continue
                if selected_tahun == dt_resign.year and view_month_num > dt_resign.month:
                    continue
            except ValueError:
                pass
        if k.tmk:
            try:
                dt_tmk = None
                for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
                    try:
                        dt_tmk = datetime.datetime.strptime(k.tmk.strip(), fmt).date()
                        break
                    except ValueError:
                        pass
                if dt_tmk:
                    if selected_tahun < dt_tmk.year:
                        continue
                    if selected_tahun == dt_tmk.year and view_month_num < dt_tmk.month:
                        continue
            except Exception:
                pass
        filtered_karyawan_list.append(k)

    # Filter tambahan: PT, Divisi, Jabatan
    if selected_pt:
        filtered_karyawan_list = [k for k in filtered_karyawan_list if (k.pt or '') == selected_pt]
    if selected_divisi:
        filtered_karyawan_list = [k for k in filtered_karyawan_list if (k.divisi or '') == selected_divisi]
    if selected_jabatan:
        filtered_karyawan_list = [k for k in filtered_karyawan_list if (k.jabatan or '') == selected_jabatan]

    # Ambil data kehadiran dari DB yang sudah ada untuk periode terpilih
    existing_entries = db.session.execute(
        db.select(Kehadiran)
        .where(Kehadiran.bulan == selected_bulan, Kehadiran.tahun == selected_tahun)
    ).scalars().all()
    kehadiran_map = {e.nik: e for e in existing_entries}

    # Hitung hari sabtu & minggu (weekends) untuk bulan & tahun terpilih
    weekends = []
    for d in range(1, jumlah_hari + 1):
        try:
            dt = datetime.date(selected_tahun, view_month_num, d)
            if dt.weekday() in (5, 6):
                weekends.append(d)
        except ValueError:
            pass

    # Ambil hari libur untuk bulan & tahun terpilih
    all_holidays = db.session.execute(db.select(HariLibur)).scalars().all()
    holiday_days = {}
    for h in all_holidays:
        if h.tanggal.month == view_month_num and h.tanggal.year == selected_tahun:
            holiday_days[h.tanggal.day] = h.keterangan

    # Validasi jika masih ada pending
    has_pending = False
    for k in filtered_karyawan_list:
        entry = kehadiran_map.get(k.nik)
        
        # Cari tanggal tmk
        days_before_tmk = set()
        if k.tmk:
            tmk_date = None
            for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                try:
                    tmk_date = datetime.datetime.strptime(k.tmk.strip(), fmt).date()
                    break
                except ValueError:
                    pass
            if tmk_date:
                for d in range(1, jumlah_hari + 1):
                    try:
                        cell_date = datetime.date(selected_tahun, view_month_num, d)
                        if cell_date < tmk_date:
                            days_before_tmk.add(d)
                    except ValueError:
                        pass

        status_dict = entry.status_hari if entry and entry.status_hari else {}
        for d in range(1, jumlah_hari + 1):
            if d in days_before_tmk:
                continue
            try:
                cell_date = datetime.date(selected_tahun, view_month_num, d)
            except ValueError:
                continue
            if cell_date < system_date:
                is_weekend = d in weekends
                is_holiday = d in holiday_days
                if not is_weekend and not is_holiday:
                    db_status = status_dict.get(str(d), '')
                    if not db_status or db_status == 'P':
                        has_pending = True
                        break
        if has_pending:
            break

    if has_pending:
        flash("⚠️ Tidak dapat mengunduh laporan karena masih terdapat absensi pending!", "danger")
        return redirect(url_for('generate_laporan', bulan=selected_bulan, tahun=selected_tahun))

    # Caching data cuti massal untuk kalkulasi sisa cuti
    all_kehadiran = db.session.execute(db.select(Kehadiran)).scalars().all()
    all_cuti_manual = db.session.execute(db.select(CutiManual)).scalars().all()
    bulan_list = db.session.execute(db.select(Bulan)).scalars().all()
    
    from collections import defaultdict
    kehadiran_by_nik = defaultdict(list)
    for kh in all_kehadiran:
        kehadiran_by_nik[kh.nik].append(kh)

    cuti_manual_by_nik = defaultdict(list)
    for cm in all_cuti_manual:
        cuti_manual_by_nik[cm.nik].append(cm)

    bulan_days_map = {b.nama: b.jumlah_hari for b in bulan_list}

    # Generate Excel
    import pandas as pd
    import io
    from flask import send_file

    late_cells = []
    libur_cells = []
    rows_data = []
    for idx, k in enumerate(filtered_karyawan_list, 1):
        # Calculate Cuti Balance as of the end of the selected period (last_day_of_month)
        ct_info = get_cuti_tahunan_balance(
            k, last_day_of_month,
            kehadiran_entries=kehadiran_by_nik[k.nik],
            cuti_manual_entries=cuti_manual_by_nik[k.nik],
            bulan_days_map=bulan_days_map
        )
        sisa_ct = ct_info['balance']

        cd_info = get_cuti_dinas_balance(
            k, last_day_of_month,
            kehadiran_entries=kehadiran_by_nik[k.nik],
            cuti_manual_entries=cuti_manual_by_nik[k.nik]
        )
        sisa_cd = cd_info['balance']

        # Rekap Kehadiran
        entry = kehadiran_map.get(k.nik)
        status_dict = entry.status_hari if entry and entry.status_hari else {}
        scan_masuk_dict = entry.scan_masuk_hari if entry and entry.scan_masuk_hari else {}
        scan_pulang_dict = entry.scan_pulang_hari if entry and entry.scan_pulang_hari else {}
        izin_dict = entry.izin_hari if entry and entry.izin_hari else {}

        hadir = 0
        dl = 0
        sakit = 0
        ct = 0
        cn = 0
        cd = 0
        alpa = 0
        libur = 0
        terlambat = 0
        pulang_cepat = 0

        # Cari tanggal tmk
        days_before_tmk = set()
        if k.tmk:
            tmk_date = None
            for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                try:
                    tmk_date = datetime.datetime.strptime(k.tmk.strip(), fmt).date()
                    break
                except ValueError:
                    pass
            if tmk_date:
                for d in range(1, jumlah_hari + 1):
                    try:
                        cell_date = datetime.date(selected_tahun, view_month_num, d)
                        if cell_date < tmk_date:
                            days_before_tmk.add(d)
                    except ValueError:
                        pass

        row_dict = {
            'No': idx,
            'No Absen': k.absen,
            'NIK': k.nik,
            'Nama Karyawan': k.nama,
            'Perusahaan (PT)': k.pt or '-',
            'Divisi': k.divisi or '-',
            'Jabatan': k.jabatan or '-',
            'Tanggal Masuk Kerja (TMK)': k.tmk or '-'
        }

        # Track unpermitted late cells for Excel brown background highlight
        # current_excel_row: row 1 is header, so row idx is idx + 1
        current_excel_row = idx + 1

        for d in range(1, jumlah_hari + 1):
            if d in days_before_tmk:
                row_dict[str(d)] = '-'
                continue

            val = status_dict.get(str(d), '')
            if val == 'OFF':
                val = 'L'

            is_weekend = d in weekends
            is_holiday = d in holiday_days
            if not val and (is_weekend or is_holiday):
                val = 'L'

            if val == 'M':
                hadir += 1
                # Check terlambat / pulang cepat menggunakan M/I (izin_hari)
                is_izin = bool(izin_dict.get(str(d), False))
                masuk_time = scan_masuk_dict.get(str(d), '')
                pulang_time = scan_pulang_dict.get(str(d), '')
                
                if not is_izin:
                    is_late = is_late_scan(masuk_time)
                    is_early = bool(k.jam_pulang and is_early_checkout(pulang_time, k.jam_pulang))

                    if is_late:
                        terlambat += 1
                    if is_early:
                        pulang_cepat += 1

                    if is_late or is_early:
                        # Mark this cell for brown fill (8 base info columns + d)
                        col_idx = 8 + d
                        late_cells.append((current_excel_row, col_idx))
                            
            elif val == 'DL':
                dl += 1
            elif val == 'S':
                sakit += 1
            elif val in ('CT', 'C'):
                ct += 1
            elif val == 'CN':
                cn += 1
            elif val == 'CD':
                cd += 1
            elif val == 'A':
                alpa += 1
            elif val in ('L', 'OFF'):
                libur += 1
                col_idx = 8 + d
                libur_cells.append((current_excel_row, col_idx))

            row_dict[str(d)] = val or '-'

        # Rekapitulasi & Saldo Cuti
        row_dict.update({
            'Hadir (M)': hadir,
            'Dinas Luar (DL)': dl,
            'Sakit (S)': sakit,
            'Cuti Tahunan (CT)': ct,
            'Cuti Bersama/Khusus (CN)': cn,
            'Cuti Dinas (CD)': cd,
            'Alpa (A)': alpa,
            'Libur (L)': libur,
            'Terlambat': terlambat,
            'Pulang Cepat': pulang_cepat,
            'Sisa Cuti Tahunan': sisa_ct,
            'Sisa Cuti Dinas': sisa_cd
        })
        rows_data.append(row_dict)

    base_cols = [
        'No', 'No Absen', 'NIK', 'Nama Karyawan', 'Perusahaan (PT)', 'Divisi', 'Jabatan',
        'Tanggal Masuk Kerja (TMK)'
    ]
    date_cols = [str(d) for d in range(1, jumlah_hari + 1)]
    summary_cols = [
        'Hadir (M)', 'Dinas Luar (DL)', 'Sakit (S)', 'Cuti Tahunan (CT)',
        'Cuti Bersama/Khusus (CN)', 'Cuti Dinas (CD)', 'Alpa (A)',
        'Libur (L)', 'Terlambat', 'Pulang Cepat', 'Sisa Cuti Tahunan', 'Sisa Cuti Dinas'
    ]
    all_cols = base_cols + date_cols + summary_cols
    df = pd.DataFrame(rows_data, columns=all_cols)
    
    # Write to Excel in memory and apply cell styling
    from openpyxl.styles import PatternFill, Font
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Rekap Kehadiran & Cuti')
        ws = writer.sheets['Rekap Kehadiran & Cuti']
        
        # Gray background fill for holidays / days off (L)
        gray_fill = PatternFill(start_color='E2E8F0', end_color='E2E8F0', fill_type='solid')
        gray_font = Font(color='475569', bold=True)
        for r, c in libur_cells:
            cell = ws.cell(row=r, column=c)
            cell.fill = gray_fill
            cell.font = gray_font

        # Brown background fill with bold white font for unexcused late / early checkout attendance
        brown_fill = PatternFill(start_color='C49A6C', end_color='C49A6C', fill_type='solid')
        late_font = Font(color='FFFFFF', bold=True)
        for r, c in late_cells:
            cell = ws.cell(row=r, column=c)
            cell.fill = brown_fill
            cell.font = late_font
        
    output.seek(0)
    
    filename = f"Laporan_Kehadiran_Cuti_{selected_bulan}_{selected_tahun}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/master-cuti/update', methods=['POST'])
def update_cuti():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    nik = request.form.get('nik', '').strip().upper()
    jumlah_raw = request.form.get('jumlah', '').strip()
    keterangan = request.form.get('keterangan', '').strip()
    
    if not (nik and jumlah_raw):
        flash("⚠️ Kolom Karyawan dan Jumlah wajib diisi!", "danger")
        return redirect(url_for('master_cuti'))
        
    try:
        jumlah = float(jumlah_raw)
        if jumlah <= 0:
            raise ValueError
    except ValueError:
        flash("⚠️ Jumlah hari harus berupa angka positif!", "danger")
        return redirect(url_for('master_cuti'))
        
    karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    if not karyawan:
        flash("⚠️ Karyawan tidak ditemukan!", "danger")
        return redirect(url_for('master_cuti'))
        
    # Resolve system/simulation date to get period
    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()
    tanggal_input = system_date.strftime("%Y-%m-%d")

    # If keterangan is empty, create a default one
    if not keterangan:
        keterangan = f"Penambahan cuti dinas sebanyak {jumlah_raw} hari untuk NIK {nik} pada {tanggal_input}"

    try:
        new_add_cd = CutiManual(
            nik=nik,
            tanggal_input=tanggal_input,
            jumlah=jumlah,
            tipe='ADD_CD',
            keterangan=keterangan
        )
        db.session.add(new_add_cd)
        INDONESIAN_MONTHS = [
            "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
            "Juli", "Agustus", "September", "Oktober", "November", "Desember"
        ]
        ref_period = f"{INDONESIAN_MONTHS[system_date.month]} {system_date.year}"
        sdm_log('TAMBAH_CUTI_DINAS', 'CUTI', f"Tambah jatah cuti dinas {karyawan.nama} ({nik}) sebanyak {jumlah} hari untuk periode {ref_period}. Ket: {keterangan}", nik=nik, nama_karyawan=karyawan.nama)
        db.session.commit()
        flash(f"✅ Transaksi berhasil: Jatah Cuti Dinas {karyawan.nama} ditambahkan sebanyak {jumlah} hari.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Terjadi kesalahan database: {str(e)}", "danger")
        
    return redirect(url_for('master_cuti'))

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
    
    import datetime
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass

    INDONESIAN_MONTHS = [
        'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ]
    default_bulan_nama = INDONESIAN_MONTHS[system_date.month - 1]
    default_tahun = system_date.year

    selected_bulan = request.args.get('bulan', '').strip()
    if not selected_bulan:
        selected_bulan = default_bulan_nama
        
    selected_tahun_str = request.args.get('tahun', '').strip()
    if not selected_tahun_str:
        selected_tahun = default_tahun
    else:
        try:
            selected_tahun = int(selected_tahun_str)
        except ValueError:
            selected_tahun = default_tahun

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
            ent = kehadiran_map[k.nik]
            ent.karyawan = k
            final_entries.append(ent)
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

    # Resolve system/simulation date
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass

    # Hitung tanggal sebelum TMK untuk setiap karyawan, serta otomatis pending-kan hari kerja yang lampau
    db_changed = False
    for entry in final_entries:
        days_before_tmk = set()
        emp = entry.karyawan
        if emp and emp.tmk:
            tmk_date = None
            for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                try:
                    tmk_date = datetime.datetime.strptime(emp.tmk.strip(), fmt).date()
                    break
                except ValueError:
                    pass
            if tmk_date:
                for d in range(1, jumlah_hari + 1):
                    try:
                        cell_date = datetime.date(selected_tahun, month_num, d)
                        if cell_date < tmk_date:
                            days_before_tmk.add(d)
                    except ValueError:
                        pass
        entry.days_before_tmk = days_before_tmk

        # Otomatis pending-kan hari kerja yang lampau (cell_date < system_date) yang belum diisi
        status_dict = dict(entry.status_hari) if entry.status_hari else {}
        scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
        scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}
        
        entry_changed = False
        for d in range(1, jumlah_hari + 1):
            if d in days_before_tmk:
                continue
            try:
                cell_date = datetime.date(selected_tahun, month_num, d)
            except ValueError:
                continue
                
            if cell_date < system_date:
                # Cek jika hari kerja (bukan sabtu/minggu, bukan hari libur)
                is_weekend = d in weekends
                is_holiday = d in holiday_days
                if not is_weekend and not is_holiday:
                    db_status = status_dict.get(str(d), '')
                    if not db_status:
                        status_dict[str(d)] = 'P'
                        scan_masuk_dict[str(d)] = ''
                        scan_pulang_dict[str(d)] = ''
                        entry_changed = True
                        
        if entry_changed:
            entry.status_hari = status_dict
            entry.scan_masuk_hari = scan_masuk_dict
            entry.scan_pulang_hari = scan_pulang_dict
            if entry.id is None:
                db.session.add(entry)
            db_changed = True
            
    if db_changed:
        db.session.commit()

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
        
    import datetime as dt_module
    if 'simulation_date' in session:
        try:
            system_date = dt_module.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            system_date = dt_module.date.today()
    else:
        system_date = dt_module.date.today()
        
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
    
    if not keterangan:
        return jsonify({'success': False, 'message': '⚠️ Keterangan wajib diisi!'}), 400
    
    if status not in ['M', 'S', 'DL', 'A', 'CT', 'CN', 'CD', 'L', 'P', 'C']:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    # Cek jika tanggal sebelum TMK karyawan
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    m_num = MONTH_NUMBERS.get(bulan)
    if not m_num:
        return jsonify({'success': False, 'message': 'Nama bulan tidak valid'}), 400

    try:
        cell_date = datetime.date(int(tahun), m_num, int(day))
    except ValueError:
        return jsonify({'success': False, 'message': 'Tanggal tidak valid'}), 400

    tanggal_selesai_str = data.get('tanggal_selesai')
    if tanggal_selesai_str:
        try:
            end_date = datetime.datetime.strptime(tanggal_selesai_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Tanggal selesai tidak valid'}), 400
            
        if end_date < cell_date:
            return jsonify({'success': False, 'message': 'Tanggal selesai harus setelah tanggal mulai'}), 400
            
        karyawan = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
        ).scalar_one_or_none()
        if not karyawan:
            return jsonify({'success': False, 'message': 'Data karyawan tidak ditemukan'}), 404
            
        tmk_date = None
        if karyawan.tmk:
            for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
                try:
                    tmk_date = datetime.datetime.strptime(karyawan.tmk.strip(), fmt).date()
                    break
                except ValueError:
                    pass
                    
        resign_date = None
        if karyawan.tanggal_resign:
            try:
                resign_date = datetime.datetime.strptime(karyawan.tanggal_resign, "%Y-%m-%d").date()
            except ValueError:
                pass

        import datetime as dt_module
        curr_d = cell_date
        dates_to_update = []
        while curr_d <= end_date:
            if tmk_date and curr_d < tmk_date:
                curr_d += dt_module.timedelta(days=1)
                continue
            if resign_date and curr_d >= resign_date:
                curr_d += dt_module.timedelta(days=1)
                continue
            dates_to_update.append(curr_d)
            curr_d += dt_module.timedelta(days=1)

        INDONESIAN_MONTHS = [
            "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
            "Juli", "Agustus", "September", "Oktober", "November", "Desember"
        ]

        kehadiran_cache = {}
        
        # Pre-check: Ensure all dates in the range are currently Pending
        for curr_date in dates_to_update:
            curr_bulan = INDONESIAN_MONTHS[curr_date.month]
            curr_tahun = curr_date.year
            curr_day_str = str(curr_date.day)
            
            cache_key = (curr_bulan, curr_tahun)
            if cache_key in kehadiran_cache:
                entry = kehadiran_cache[cache_key]
            else:
                entry = db.session.execute(
                    db.select(Kehadiran).where(
                        Kehadiran.nik == nik,
                        Kehadiran.bulan == curr_bulan,
                        Kehadiran.tahun == curr_tahun
                    )
                ).scalar_one_or_none()
                if entry:
                    kehadiran_cache[cache_key] = entry
                    
            if entry:
                curr_status = entry.status_hari.get(curr_day_str, 'P') or 'P'
                if curr_status != 'P':
                    return jsonify({
                        'success': False,
                        'message': f'⚠️ Batch edit hanya bisa dilakukan jika seluruh hari dalam rentang statusnya Pending. Tanggal {curr_date.strftime("%d-%m-%Y")} memiliki status "{curr_status}" (bukan Pending)!'
                    }), 400

        warning_msg = None
        for curr_date in dates_to_update:
            curr_bulan = INDONESIAN_MONTHS[curr_date.month]
            curr_tahun = curr_date.year
            curr_day_str = str(curr_date.day)
            
            cache_key = (curr_bulan, curr_tahun)
            if cache_key in kehadiran_cache:
                entry = kehadiran_cache[cache_key]
            else:
                entry = db.session.execute(
                    db.select(Kehadiran).where(
                        Kehadiran.nik == nik,
                        Kehadiran.bulan == curr_bulan,
                        Kehadiran.tahun == curr_tahun
                    )
                ).scalar_one_or_none()
                
                if not entry:
                    entry = Kehadiran(
                        nik=nik,
                        bulan=curr_bulan,
                        tahun=curr_tahun,
                        status_hari={},
                        scan_masuk_hari={},
                        scan_pulang_hari={},
                        keterangan_hari={},
                        izin_hari={}
                    )
                    db.session.add(entry)
                kehadiran_cache[cache_key] = entry
                
            if status in ('CT', 'CD'):
                old_status = entry.status_hari.get(curr_day_str)
                if old_status != status:
                    t_info, d_info = get_adjusted_cuti_balances(karyawan, curr_date if status == 'CT' else system_date)
                    if status == 'CT':
                        if t_info['balance'] <= 0:
                            warning_msg = f"⚠️ Peringatan: Saldo cuti tahunan tidak mencukupi (sisa: {t_info['balance']} hari). Pengisian tetap disimpan dan saldo menjadi minus."
                    else:
                        usable_dinas_balance = max(0.0, d_info['balance'])
                        if usable_dinas_balance <= 0:
                            return jsonify({'success': False, 'message': f'⚠️ Jatah cuti dinas tidak mencukupi pada tanggal {curr_date.strftime("%d-%m-%Y")}.'}), 400

            status_dict = dict(entry.status_hari)
            status_dict[curr_day_str] = status
            entry.status_hari = status_dict
            
            scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
            scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}
            keterangan_dict = dict(entry.keterangan_hari) if entry.keterangan_hari else {}
            izin_dict = dict(entry.izin_hari) if entry.izin_hari else {}
            
            scan_masuk_dict[curr_day_str] = ''
            scan_pulang_dict[curr_day_str] = ''
            keterangan_dict[curr_day_str] = keterangan
            izin_dict[curr_day_str] = False
            
            entry.scan_masuk_hari = scan_masuk_dict
            entry.scan_pulang_hari = scan_pulang_dict
            entry.keterangan_hari = keterangan_dict
            entry.izin_hari = izin_dict

        db.session.commit()
        return jsonify({'success': True, 'warning': warning_msg})

    karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    if karyawan and karyawan.tmk:
        tmk_date = None
        for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
            try:
                tmk_date = datetime.datetime.strptime(karyawan.tmk.strip(), fmt).date()
                break
            except ValueError:
                pass
        if tmk_date and cell_date < tmk_date:
            return jsonify({'success': False, 'message': '⚠️ Tidak dapat mengisi kehadiran sebelum Tanggal Mulai Kerja (TMK)!'}), 400

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

    # Check leave balance if transitioning to CT (Cuti Tahunan) or CD (Cuti Dinas)
    warning_msg = None
    if status in ('CT', 'CD'):
        karyawan = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.nik == entry.nik)
        ).scalar_one_or_none()
        if not karyawan:
            return jsonify({'success': False, 'message': 'Data karyawan tidak ditemukan'}), 404
            
        old_status = entry.status_hari.get(day)
        if old_status != status:
            if status == 'CT':
                MONTH_NUMBERS = {
                    'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
                    'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
                    'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
                }
                m_num = MONTH_NUMBERS.get(entry.bulan)
                if not m_num:
                    return jsonify({'success': False, 'message': 'Nama bulan tidak valid'}), 400
                try:
                    leave_date = datetime.date(entry.tahun, m_num, int(day))
                except ValueError:
                    return jsonify({'success': False, 'message': 'Tanggal tidak valid'}), 400
                    
                t_info, d_info = get_adjusted_cuti_balances(karyawan, leave_date)
                if t_info['balance'] <= 0:
                    warning_msg = f"⚠️ Peringatan: Saldo cuti tahunan tidak mencukupi (sisa: {t_info['balance']} hari). Pengisian tetap disimpan dan saldo menjadi minus."
            else:
                t_info, d_info = get_adjusted_cuti_balances(karyawan, system_date)
                usable_dinas_balance = max(0.0, d_info['balance'])
                if usable_dinas_balance <= 0:
                    entry_period = f"{entry.bulan} {entry.tahun}"
                    return jsonify({'success': False, 'message': f'⚠️ Jatah cuti dinas untuk periode {entry_period} habis/tidak mencukupi untuk karyawan ini.'}), 400

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
    return jsonify({'success': True, 'warning': warning_msg})

@app.route('/cek-cuti')
def cek_cuti():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    # Ambil NIK dari akun user yang login
    user_id = session.get('result_id')
    user_entry = db.session.get(UserEntry, user_id)
    user_nik = user_entry.nik if user_entry else None

    karyawan = None
    cuti_tahunan_balance = 0
    cuti_tahunan_used = 0
    cuti_tahunan_expired = 0
    cuti_tahunan_next_hangus_date = None
    cuti_tahunan_next_hangus_amount = 0
    cuti_tahunan_pending_hangus = 0

    cuti_dinas_balance = 0
    cuti_dinas_next_hangus_date = None
    cuti_dinas_next_hangus_amount = 0
    cuti_dinas_pending_hangus = 0
    riwayat = []

    if user_nik:
        karyawan = db.session.execute(
            db.select(KaryawanEntry).where(KaryawanEntry.nik == user_nik)
        ).scalar_one_or_none()

    if karyawan:
        system_date = datetime.date.today()
        if 'simulation_date' in session:
            try:
                system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
            except Exception:
                pass

        tahunan_info = get_cuti_tahunan_balance(karyawan, system_date)
        cuti_tahunan_balance = tahunan_info.get('balance', 0)
        cuti_tahunan_used    = tahunan_info.get('used', 0)
        cuti_tahunan_expired = tahunan_info.get('expired', 0)
        cuti_tahunan_next_hangus_date = tahunan_info.get('next_expiration_date')
        cuti_tahunan_next_hangus_amount = tahunan_info.get('next_expiration_amount', 0)
        cuti_tahunan_pending_hangus = tahunan_info.get('pending_expiration_amount', 0)

        dinas_info = get_cuti_dinas_balance(karyawan, system_date)
        cuti_dinas_balance = max(0.0, dinas_info.get('balance', 0))
        cuti_dinas_next_hangus_date = dinas_info.get('next_expiration_date')
        cuti_dinas_next_hangus_amount = dinas_info.get('next_expiration_amount', 0)
        cuti_dinas_pending_hangus = dinas_info.get('pending_expiration_amount', 0)

        riwayat = db.session.execute(
            db.select(CutiManual)
            .where(CutiManual.nik == user_nik)
            .order_by(CutiManual.tanggal_input.desc())
        ).scalars().all()

    return render_template(
        'cek_cuti.html',
        karyawan=karyawan,
        user_nik=user_nik,
        cuti_tahunan_balance=cuti_tahunan_balance,
        cuti_tahunan_used=cuti_tahunan_used,
        cuti_tahunan_expired=cuti_tahunan_expired,
        cuti_tahunan_next_hangus_date=cuti_tahunan_next_hangus_date,
        cuti_tahunan_next_hangus_amount=cuti_tahunan_next_hangus_amount,
        cuti_tahunan_pending_hangus=cuti_tahunan_pending_hangus,
        cuti_dinas_balance=cuti_dinas_balance,
        cuti_dinas_next_hangus_date=cuti_dinas_next_hangus_date,
        cuti_dinas_next_hangus_amount=cuti_dinas_next_hangus_amount,
        cuti_dinas_pending_hangus=cuti_dinas_pending_hangus,
        riwayat=riwayat,
    )

@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if 'logged_user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    form = UserForm()
    
    if form.validate_on_submit():
        nik_clean = form.nik.data.strip().upper()
        if not nik_clean.isalnum():
            flash("⚠️ NIK hanya boleh berisi huruf dan angka (tanpa spasi atau simbol)!", "danger")
            return redirect(url_for('manage_users'))
            
        username_clean = form.username.data.strip()
        existing_user = db.session.execute(db.select(UserEntry).where(UserEntry.username == username_clean)).scalar_one_or_none()
        
        if existing_user:
            flash(f"⚠️ Gagal! Username '{username_clean}' sudah digunakan oleh orang lain.", "danger")
        else:
            if not form.password.data:
                flash("⚠️ Password wajib diisi untuk pengguna baru!", "danger")
            else:
                hashed_pw = generate_password_hash(form.password.data)
                new_user = UserEntry(nik=nik_clean, username=username_clean, password=hashed_pw, role=form.role.data)
                db.session.add(new_user)
                db.session.commit()
                flash(f"Pengguna '{username_clean}' (NIK: {nik_clean}) berhasil didaftarkan.", "success")
                return redirect(url_for('manage_users'))
    elif request.method == 'POST':
        for field_name, errors in form.errors.items():
            for error in errors:
                flash(f"⚠️ {error}", "danger")

    all_users = db.session.execute(db.select(UserEntry).order_by(UserEntry.id)).scalars().all()
    return render_template('sdm/users.html', form=form, users=all_users, active_page='users', edit_user=None)

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    if 'logged_user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    user_to_edit = db.session.get(UserEntry, user_id)
    if not user_to_edit:
        flash("⚠️ Pengguna yang ingin diedit tidak ditemukan.", "danger")
        return redirect(url_for('manage_users'))

    if request.method == 'GET':
        form = UserForm(obj=user_to_edit)
        form.password.data = ''
    else:
        form = UserForm()

    if form.validate_on_submit():
        nik_clean = form.nik.data.strip().upper()
        username_clean = form.username.data.strip()

        if not nik_clean.isalnum():
            flash("⚠️ NIK hanya boleh berisi huruf dan angka (tanpa spasi atau simbol)!", "danger")
        else:
            existing_user = db.session.execute(
                db.select(UserEntry).where(
                    UserEntry.username == username_clean,
                    UserEntry.id != user_to_edit.id
                )
            ).scalar_one_or_none()

            if existing_user:
                flash(f"⚠️ Gagal! Username '{username_clean}' sudah digunakan oleh orang lain.", "danger")
            else:
                old_username = user_to_edit.username
                user_to_edit.nik = nik_clean
                user_to_edit.username = username_clean
                user_to_edit.role = form.role.data
                if form.password.data:
                    user_to_edit.password = generate_password_hash(form.password.data)
                db.session.commit()

                if session.get('logged_user') == old_username:
                    session['logged_user'] = username_clean
                    session['role'] = user_to_edit.role

                flash(f"Pengguna '{username_clean}' berhasil diperbarui.", "success")
                return redirect(url_for('manage_users'))
    elif request.method == 'POST':
        for field_name, errors in form.errors.items():
            for error in errors:
                flash(f"⚠️ {error}", "danger")

    all_users = db.session.execute(db.select(UserEntry).order_by(UserEntry.id)).scalars().all()
    return render_template(
        'sdm/users.html',
        form=form,
        users=all_users,
        active_page='users',
        edit_user=user_to_edit
    )

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
        action_type = request.form.get('action_type', 'tambah').strip()
        nik = request.form.get('nik', '').strip().upper()
        nama = request.form.get('nama', '').strip()
        pt = request.form.get('pt', '').strip()
        jabatan = request.form.get('jabatan', '').strip()
        staff = request.form.get('staff', '').strip()
        divisi = request.form.get('divisi', '').strip()
        departemen = request.form.get('departemen', '').strip()
        priority_level = request.form.get('priority_level', '').strip()
        tmk = request.form.get('tmk', '').strip()
        jam_masuk_raw = request.form.get('jam_masuk', '').strip()
        jam_pulang_raw = request.form.get('jam_pulang', '').strip()
        
        # Validasi umum (departemen divalidasi kondisional terhadap priority_level)
        if not (nik and nama and pt and jabatan and staff and divisi and priority_level and tmk and jam_masuk_raw and jam_pulang_raw):
            flash("⚠️ Semua kolom wajib diisi!", "danger")
            return redirect(url_for('tambah_karyawan'))
            
        # Validasi Departemen: hanya izinkan kosong jika priority level 1 (kepala divisi)
        if str(priority_level) != '1' and not departemen:
            flash("⚠️ Departemen wajib diisi jika Priority Level bukan 1 (Kepala Divisi)!", "danger")
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

        if action_type == 'edit':
            # Logika Edit Karyawan
            karyawan = db.session.execute(
                db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
            ).scalar_one_or_none()
            if not karyawan:
                flash(f"⚠️ Karyawan dengan NIK '{nik}' tidak ditemukan.", "danger")
                return redirect(url_for('tambah_karyawan'))
                
            try:
                # Track perubahan setiap field
                changes = []
                field_labels = [
                    ('nama', 'Nama', nama),
                    ('pt', 'PT', pt),
                    ('jabatan', 'Jabatan', jabatan),
                    ('staff', 'Tipe Staff', staff),
                    ('divisi', 'Divisi', divisi if divisi else None),
                    ('departemen', 'Departemen', departemen if departemen else None),
                    ('priority_level', 'Priority Level', int(priority_level) if priority_level else None),
                    ('tmk', 'TMK', tmk),
                    ('jam_masuk', 'Jam Masuk', jam_masuk),
                    ('jam_pulang', 'Jam Pulang', jam_pulang)
                ]

                for attr, label, new_val in field_labels:
                    old_val = getattr(karyawan, attr)
                    if attr in ('jam_masuk', 'jam_pulang'):
                        old_val_str = old_val.strftime("%H:%M") if old_val is not None else ""
                        new_val_str = new_val.strftime("%H:%M") if new_val is not None else ""
                    else:
                        old_val_str = str(old_val).strip() if old_val is not None else ""
                        new_val_str = str(new_val).strip() if new_val is not None else ""
                        
                    if old_val_str != new_val_str:
                        old_display = old_val_str if old_val_str else "(Kosong)"
                        new_display = new_val_str if new_val_str else "(Kosong)"
                        changes.append(f"{label}: {old_display} ➔ {new_display}")

                karyawan.nama = nama
                karyawan.pt = pt
                karyawan.jabatan = jabatan
                karyawan.staff = staff
                karyawan.divisi = divisi if divisi else None
                karyawan.departemen = departemen if departemen else None
                karyawan.priority_level = priority_level if priority_level else None
                karyawan.tmk = tmk
                karyawan.jam_masuk = jam_masuk
                karyawan.jam_pulang = jam_pulang
                karyawan.dilakukan_oleh = session.get('logged_user', 'system')
                karyawan.tanggal_aksi = datetime.now()
                
                if changes:
                    detail_log = " | ".join(changes)
                else:
                    detail_log = "Data disimpan ulang tanpa perubahan nilai."

                sdm_log('EDIT_KARYAWAN', 'KARYAWAN', detail_log, nik=nik, nama_karyawan=nama)
                db.session.commit()
                flash(f"✅ Data karyawan '{nama}' (NIK: {nik}) berhasil diperbarui!", "success")
                return redirect(url_for('master_karyawan'))
            except Exception as e:
                db.session.rollback()
                flash(f"⚠️ Terjadi kesalahan saat menyimpan data: {str(e)}", "danger")
                return redirect(url_for('tambah_karyawan'))
        else:
            # Logika Tambah Karyawan (tambah)
            # Hitung nomor absen otomatis: angka terbesar + 1
            max_absen = db.session.execute(db.select(db.func.max(KaryawanEntry.absen))).scalar()
            absen = (max_absen or 0) + 1
                
            # Cek duplikat NIK
            existing_nik = db.session.execute(
                db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
            ).scalar_one_or_none()
            if existing_nik:
                flash(f"⚠️ Gagal! NIK '{nik}' sudah digunakan.", "danger")
                return redirect(url_for('tambah_karyawan'))
                
            try:
                new_karyawan = KaryawanEntry(
                    nik=nik,
                    absen=absen,
                    nama=nama,
                    pt=pt,
                    jabatan=jabatan,
                    staff=staff,
                    divisi=divisi if divisi else None,
                    departemen=departemen if departemen else None,
                    priority_level=priority_level if priority_level else None,
                    tmk=tmk,
                    jam_masuk=jam_masuk,
                    jam_pulang=jam_pulang,
                    dilakukan_oleh=session.get('logged_user', 'system')
                )
                new_cuti = Cuti(
                    nik=nik,
                    cuti_tahunan=0,
                    cuti_dinas=0
                )
                db.session.add(new_karyawan)
                db.session.add(new_cuti)
                sdm_log('TAMBAH_KARYAWAN', 'KARYAWAN', f"Tambah karyawan baru: '{nama}' (NIK: {nik}, PT: {pt}, Jabatan: {jabatan}, Tipe Staff: {staff}, TMK: {tmk}).", nik=nik, nama_karyawan=nama)
                db.session.commit()
                flash(f"✅ Karyawan '{nama}' (NIK: {nik}) berhasil ditambahkan!", "success")
                return redirect(url_for('master_karyawan'))
            except Exception as e:
                db.session.rollback()
                flash(f"⚠️ Terjadi kesalahan saat menyimpan data: {str(e)}", "danger")
                return redirect(url_for('tambah_karyawan'))
                
    # Hitung nomor absen otomatis untuk ditampilkan di formulir
    max_absen = db.session.execute(db.select(db.func.max(KaryawanEntry.absen))).scalar()
    next_absen = (max_absen or 0) + 1
    list_jabatan = db.session.execute(db.select(Jabatan).order_by(Jabatan.nama)).scalars().all()
    list_pt = db.session.execute(db.select(SdmPT).order_by(SdmPT.nama)).scalars().all()
    list_divisi = db.session.execute(db.select(SdmDivisi).order_by(SdmDivisi.nama)).scalars().all()
    list_departemen = db.session.execute(db.select(SdmDepartemen).order_by(SdmDepartemen.nama)).scalars().all()
    karyawan_list = db.session.execute(db.select(KaryawanEntry).order_by(KaryawanEntry.absen)).scalars().all()
    
    return render_template(
        'sdm/tambah_karyawan.html',
        next_absen=next_absen,
        list_jabatan=list_jabatan,
        list_pt=list_pt,
        list_divisi=list_divisi,
        list_departemen=list_departemen,
        karyawan_list=karyawan_list,
        active_page='sdm-transaksi'
    )

@app.route('/tambah-karyawan/api/detail/<nik>', methods=['GET'])
def karyawan_detail_api(nik):
    if 'logged_user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    k = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    
    if not k:
        return jsonify({'success': False, 'message': 'Karyawan tidak ditemukan'}), 404
        
    return jsonify({
        'success': True,
        'nik': k.nik,
        'absen': k.absen,
        'nama': k.nama,
        'pt': k.pt or '',
        'jabatan': k.jabatan or '',
        'staff': k.staff or '',
        'divisi': k.divisi or '',
        'departemen': k.departemen or '',
        'priority_level': k.priority_level or '',
        'tmk': k.tmk,
        'jam_masuk': k.jam_masuk.strftime('%H:%M') if k.jam_masuk else '08:00',
        'jam_pulang': k.jam_pulang.strftime('%H:%M') if k.jam_pulang else '17:00'
    })

@app.route('/upload-kehadiran', methods=['GET', 'POST'])
def upload_kehadiran():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    from datetime import date, datetime, timedelta

    if request.method == 'POST':
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
                
            # Validasi bahwa semua baris log kehadiran memiliki tanggal yang sama
            unique_dates = set()
            for index, row in df.iterrows():
                if row.isnull().all():
                    continue
                if pd.isna(row[col_nik]) or pd.isna(row[col_tanggal]):
                    continue
                nik = str(row[col_nik]).strip().upper()
                if nik in ('', 'NAT', 'NAN', 'NONE', '-'):
                    continue
                    
                raw_tanggal = row[col_tanggal]
                if str(raw_tanggal).strip() in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                    continue
                    
                if isinstance(raw_tanggal, (datetime, pd.Timestamp)):
                    try:
                        ts = pd.Timestamp(year=raw_tanggal.year, month=raw_tanggal.day, day=raw_tanggal.month)
                    except ValueError:
                        ts = pd.to_datetime(raw_tanggal, errors='coerce')
                else:
                    ts = pd.to_datetime(raw_tanggal, format='%m/%d/%Y', errors='coerce')
                    if pd.isna(ts):
                        ts = pd.to_datetime(raw_tanggal, errors='coerce')
                if pd.isna(ts):
                    continue
                    
                unique_dates.add(ts.strftime("%Y-%m-%d"))
                
            if not unique_dates:
                flash("⚠️ Gagal! Berkas Excel tidak berisi data log kehadiran yang valid.", "danger")
                return redirect(url_for('upload_kehadiran'))
                
            if len(unique_dates) > 1:
                flash("⚠️ Gagal! Berkas Excel berisi data log kehadiran untuk beberapa tanggal berbeda. Harap unggah per satu tanggal saja.", "danger")
                return redirect(url_for('upload_kehadiran'))
                
            target_date_str = list(unique_dates)[0]
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            
            MONTH_MAPPING = {
                1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
                5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
                9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
            }
            
            target_day = str(target_date.day)
            target_bulan_num = target_date.month
            target_tahun = target_date.year
            target_bulan = MONTH_MAPPING[target_bulan_num]

            bulan_list = db.session.execute(db.select(Bulan)).scalars().all()
            bulan_days_map = {b.nama: b.jumlah_hari for b in bulan_list}
            all_holidays = db.session.execute(db.select(HariLibur)).scalars().all()
                
            # Validasi ketat: Pastikan tidak ada data kehadiran berstatus Pending pada tanggal sebelum target_date (< target_date)
            # Misalnya upload untuk 19 Agustus 2026 -> tanggal 18 Agustus 2026 dan hari-hari sebelumnya harus bersih dari pending
            pending_found = False
            pending_sample_date = None
            pending_sample_name = None

            all_emp_entries = db.session.execute(db.select(KaryawanEntry)).scalars().all()
            kehadiran_records = db.session.execute(db.select(Kehadiran)).scalars().all()
            kh_lookup = {(k.nik, k.bulan, k.tahun): k for k in kehadiran_records}

            INV_MONTH_NAMES = MONTH_MAPPING

            for emp in all_emp_entries:
                emp_tmk = None
                if emp.tmk:
                    for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
                        try:
                            emp_tmk = datetime.strptime(emp.tmk.strip(), fmt).date()
                            break
                        except ValueError:
                            pass
                
                emp_resign = None
                if emp.tanggal_resign:
                    try:
                        emp_resign = datetime.strptime(emp.tanggal_resign.strip(), "%Y-%m-%d").date()
                    except ValueError:
                        pass

                # Lewati jika karyawan mulai bekerja pada atau setelah target_date
                if emp_tmk and emp_tmk >= target_date:
                    continue

                # Tentukan start year & month untuk pengecekan
                start_y = emp_tmk.year if emp_tmk else target_date.year
                start_m = emp_tmk.month if emp_tmk else target_date.month

                # Batasi pengecekan agar mulai dari 1 Agustus 2026 (abaikan Juli 2026 dan sebelumnya)
                if start_y < 2026 or (start_y == 2026 and start_m < 8):
                    start_y = 2026
                    start_m = 8

                curr_y, curr_m = start_y, start_m
                while (curr_y < target_date.year) or (curr_y == target_date.year and curr_m <= target_date.month):
                    b_name = INV_MONTH_NAMES[curr_m]
                    j_hari = bulan_days_map.get(b_name, 31)
                    if curr_m == 2:
                        if (curr_y % 4 == 0 and curr_y % 100 != 0) or (curr_y % 400 == 0):
                            j_hari = 29
                        else:
                            j_hari = 28

                    kh_obj = kh_lookup.get((emp.nik, b_name, curr_y))
                    st_hari = kh_obj.status_hari if kh_obj and kh_obj.status_hari else {}

                    for d in range(1, j_hari + 1):
                        try:
                            c_date = date(curr_y, curr_m, d)
                        except ValueError:
                            continue

                        # Abaikan tanggal sebelum 1 Agustus 2026
                        if c_date < date(2026, 8, 1):
                            continue

                        # Hanya periksa tanggal SEBELUM target_date (< target_date)
                        if c_date >= target_date:
                            continue

                        if emp_tmk and c_date < emp_tmk:
                            continue

                        if emp_resign and c_date >= emp_resign:
                            continue

                        # Cek weekend (Sabtu/Minggu)
                        if c_date.weekday() in (5, 6):
                            continue

                        # Cek hari libur nasional
                        if any(h.tanggal == c_date for h in all_holidays):
                            continue

                        status_val = st_hari.get(str(d), '')
                        if status_val == 'P' or status_val == '':
                            pending_found = True
                            pending_sample_date = c_date.strftime("%d/%m/%Y")
                            pending_sample_name = f"{emp.nama} ({emp.nik})"
                            break

                    if pending_found:
                        break

                    curr_m += 1
                    if curr_m > 12:
                        curr_m = 1
                        curr_y += 1

                if pending_found:
                    break

            if pending_found:
                flash(
                    f"⚠️ Gagal! Tidak dapat mengunggah kehadiran tanggal {target_date.strftime('%d/%m/%Y')} karena masih terdapat data kehadiran berstatus Pending pada tanggal sebelumnya (misal tanggal {pending_sample_date} untuk {pending_sample_name}). Harap selesaikan seluruh data pending sebelum tanggal {target_date.strftime('%d/%m/%Y')} terlebih dahulu di Dashboard / Edit Kehadiran!",
                    "danger"
                )
                return redirect(url_for('upload_kehadiran'))

            # Ambil semua karyawan aktif pada tanggal target
            all_employees = all_emp_entries
            active_niks = []
            for emp in all_employees:
                # Cek jika tanggal target sebelum TMK karyawan
                if emp.tmk:
                    tmk_date = None
                    for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
                        try:
                            tmk_date = datetime.strptime(emp.tmk.strip(), fmt).date()
                            break
                        except ValueError:
                            pass
                    if tmk_date and target_date < tmk_date:
                        continue

                # Cek jika karyawan sudah resign sebelum tanggal target
                if emp.tanggal_resign:
                    try:
                        dt_resign = datetime.strptime(emp.tanggal_resign, "%Y-%m-%d").date()
                        if target_date >= dt_resign:
                            continue
                    except ValueError:
                        pass
                active_niks.append(emp.nik)
                
            # Pre-pass untuk menghitung kemunculan NIK dalam berkas
            nik_counts = {}
            for index, row in df.iterrows():
                if row.isnull().all():
                    continue
                if pd.isna(row[col_nik]):
                    continue
                nik = str(row[col_nik]).strip().upper()
                if nik in ('', 'NAT', 'NAN', 'NONE', '-'):
                    continue
                nik_counts[nik] = nik_counts.get(nik, 0) + 1
                
            duplicate_niks = {nik for nik, count in nik_counts.items() if count > 1}
            
            success_count = 0
            skipped_nik_count = 0
            skipped_incomplete_count = 0
            skipped_duplicate_count = 0
            skipped_missing_count = 0
            unique_employees = set()
            processed_niks_in_file = set()
            
            # Iterasi setiap baris log harian
            for index, row in df.iterrows():
                # Jika baris benar-benar kosong, lewati secara senyap
                if row.isnull().all():
                    continue
                    
                # Validasi NIK dan Tanggal tidak boleh kosong/NaN
                if pd.isna(row[col_nik]) or pd.isna(row[col_tanggal]):
                    skipped_incomplete_count += 1
                    continue
                nik = str(row[col_nik]).strip().upper()
                if nik in ('', 'NAT', 'NAN', 'NONE', '-'):
                    skipped_incomplete_count += 1
                    continue
                
                # Cegah duplikasi data NIK yang sama dalam satu berkas (lewati baris berikutnya secara senyap)
                if nik in processed_niks_in_file:
                    continue
                
                # Validasi NIK terdaftar
                karyawan = db.session.execute(
                    db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
                ).scalar_one_or_none()
                if not karyawan:
                    skipped_nik_count += 1
                    continue
                    
                # Parsing tanggal
                raw_tanggal = row[col_tanggal]
                if str(raw_tanggal).strip() in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                    skipped_incomplete_count += 1
                    continue
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
                    skipped_incomplete_count += 1
                    continue

                # Cek jika tanggal baris Excel sebelum TMK karyawan
                if karyawan.tmk:
                    tmk_date = None
                    for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
                        try:
                            tmk_date = datetime.strptime(karyawan.tmk.strip(), fmt).date()
                            break
                        except ValueError:
                            pass
                    if tmk_date and ts.date() < tmk_date:
                        # Lewati secara senyap karena belum mulai bekerja pada tanggal ini
                        continue
                    
                day = str(ts.day)
                bulan_num = ts.month
                tahun = ts.year
                
                if bulan_num not in MONTH_MAPPING:
                    skipped_incomplete_count += 1
                    continue
                bulan = MONTH_MAPPING[bulan_num]
                
                # Tentukan status dan scan times berdasarkan kelengkapan data & duplikasi
                is_duplicate = (nik in duplicate_niks)
                is_incomplete = False
                val_masuk = ''
                val_pulang = ''
                
                # Check scan masuk
                if not col_masuk or pd.isna(row[col_masuk]):
                    is_incomplete = True
                else:
                    val_masuk = str(row[col_masuk]).strip()
                    if val_masuk in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                        is_incomplete = True
                        val_masuk = ''
                
                # Check scan pulang
                if not col_pulang or pd.isna(row[col_pulang]):
                    is_incomplete = True
                else:
                    val_pulang = str(row[col_pulang]).strip()
                    if val_pulang in ('', 'NaT', 'nan', 'NaN', 'None', '-'):
                        is_incomplete = True
                        val_pulang = ''
                
                # Jika duplikat atau incomplete, ubah menjadi Pending ('P') dan kosongkan scan times
                if is_duplicate:
                    status = 'P'
                    val_masuk = ''
                    val_pulang = ''
                    skipped_duplicate_count += 1
                elif is_incomplete:
                    status = 'P'
                    val_masuk = ''
                    val_pulang = ''
                    skipped_incomplete_count += 1
                else:
                    status = 'M'
                
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
                
                # Aturan bisnis: Jika status di DB saat ini adalah R (Resign), maka status absolut dan tidak boleh ditimpa.
                # Jika status di DB saat ini adalah izin resmi (S, C, CT, CN, CD, DL, L)
                # dan status baru adalah 'A' (Alpa) atau 'P' (Pending), jangan overwrite izin resmi tersebut!
                current_status = status_dict.get(day, '')
                if current_status == 'R':
                    pass
                elif current_status in ('S', 'C', 'CT', 'CN', 'CD', 'DL', 'L') and status in ('A', 'P'):
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
                processed_niks_in_file.add(nik)
                
            # Cari karyawan aktif yang tidak ada di berkas Excel
            missing_niks = [nik for nik in active_niks if nik not in processed_niks_in_file]
            for m_nik in missing_niks:
                entry = db.session.execute(
                    db.select(Kehadiran).where(Kehadiran.nik == m_nik, Kehadiran.bulan == target_bulan, Kehadiran.tahun == target_tahun)
                ).scalar_one_or_none()
                
                if not entry:
                    entry = Kehadiran(
                        nik=m_nik,
                        bulan=target_bulan,
                        tahun=target_tahun,
                        status_hari={},
                        scan_masuk_hari={},
                        scan_pulang_hari={}
                    )
                    db.session.add(entry)
                    
                status_dict = dict(entry.status_hari)
                scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
                scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}
                
                # Jangan overwrite jika status di DB sudah 'R' (Resign)
                current_status = status_dict.get(target_day, '')
                if current_status == 'R':
                    continue
                    
                status_dict[target_day] = 'P'
                scan_masuk_dict[target_day] = ''
                scan_pulang_dict[target_day] = ''
                
                entry.status_hari = status_dict
                entry.scan_masuk_hari = scan_masuk_dict
                entry.scan_pulang_hari = scan_pulang_dict
                
                unique_employees.add(m_nik)
                skipped_missing_count += 1
                
            sdm_log('UPLOAD_KEHADIRAN', 'KEHADIRAN', f"Upload Excel kehadiran: {success_count} baris diproses untuk {len(unique_employees)} karyawan.")
            db.session.commit()
            
            # Flash success message
            msg = f"✅ Berhasil memproses {success_count} baris log kehadiran harian untuk {len(unique_employees)} karyawan."
            warnings = []
            if skipped_duplicate_count > 0:
                warnings.append(f"{skipped_duplicate_count} karyawan dipendingkan karena duplikasi NIK")
            if skipped_incomplete_count > 0:
                warnings.append(f"{skipped_incomplete_count} karyawan dipendingkan karena data tidak lengkap / kosong")
            if skipped_missing_count > 0:
                warnings.append(f"{skipped_missing_count} karyawan dipendingkan karena tidak terdaftar di berkas Excel")
            if skipped_nik_count > 0:
                warnings.append(f"{skipped_nik_count} baris dilewati karena NIK tidak terdaftar")
            
            if warnings:
                msg += f" (⚠️ {', '.join(warnings)})."
            flash(msg, "success" if success_count > 0 else "warning")
            return redirect(url_for('master_kehadiran'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"⚠️ Terjadi kesalahan saat membaca berkas Excel: {str(e)}", "danger")
            return redirect(url_for('upload_kehadiran'))
            
    return render_template('sdm/upload_kehadiran.html', active_page='sdm-transaksi')

@app.route('/atur-libur')
def atur_libur():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    import datetime
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass

    INDONESIAN_MONTHS = [
        'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ]
    default_bulan_nama = INDONESIAN_MONTHS[system_date.month - 1]
    default_tahun = system_date.year

    selected_bulan = request.args.get('bulan', '').strip()
    if not selected_bulan:
        selected_bulan = default_bulan_nama
        
    selected_tahun_str = request.args.get('tahun', '').strip()
    if not selected_tahun_str:
        selected_tahun = default_tahun
    else:
        try:
            selected_tahun = int(selected_tahun_str)
        except ValueError:
            selected_tahun = default_tahun
        
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    month_num = MONTH_NUMBERS.get(selected_bulan, system_date.month)
    
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
        sdm_log('TAMBAH_LIBUR', 'LIBUR', f"Tambah hari libur: '{keterangan}' pada tanggal {tanggal_dt}.")
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
        ket_libur = libur.keterangan
        tgl_libur = str(libur.tanggal)
        db.session.delete(libur)
        sdm_log('HAPUS_LIBUR', 'LIBUR', f"Hapus hari libur: '{ket_libur}' pada tanggal {tgl_libur}.")
        db.session.commit()
        flash("✅ Hari libur berhasil dihapus.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Gagal menghapus hari libur: {str(e)}", "danger")
        
    return redirect(url_for('atur_libur', bulan=bulan_redirect, tahun=tahun_redirect))



@app.route('/edit-kehadiran', methods=['GET'])
def edit_kehadiran():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    
    import datetime
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass

    INDONESIAN_MONTHS = [
        'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ]
    default_bulan_nama = INDONESIAN_MONTHS[system_date.month - 1]
    default_tahun = system_date.year

    selected_bulan = request.args.get('bulan', '').strip()
    if not selected_bulan:
        selected_bulan = default_bulan_nama
        
    selected_tahun_str = request.args.get('tahun', '').strip()
    if not selected_tahun_str:
        selected_tahun = default_tahun
    else:
        try:
            selected_tahun = int(selected_tahun_str)
        except ValueError:
            selected_tahun = default_tahun

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
            ent = kehadiran_map[k.nik]
            ent.karyawan = k
            final_entries.append(ent)
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

    # Resolve system/simulation date
    from datetime import date
    system_date = date.today()
    if 'simulation_date' in session:
        try:
            system_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except ValueError:
            pass

    # Hitung tanggal sebelum TMK untuk setiap karyawan, serta otomatis pending-kan hari kerja yang lampau
    db_changed = False
    for entry in final_entries:
        days_before_tmk = set()
        emp = entry.karyawan
        if emp and emp.tmk:
            tmk_date = None
            for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                try:
                    tmk_date = datetime.datetime.strptime(emp.tmk.strip(), fmt).date()
                    break
                except ValueError:
                    pass
            if tmk_date:
                for d in range(1, jumlah_hari + 1):
                    try:
                        cell_date = datetime.date(selected_tahun, month_num, d)
                        if cell_date < tmk_date:
                            days_before_tmk.add(d)
                    except ValueError:
                        pass
        entry.days_before_tmk = days_before_tmk

        # Otomatis pending-kan hari kerja yang lampau (cell_date < system_date) yang belum diisi
        status_dict = dict(entry.status_hari) if entry.status_hari else {}
        scan_masuk_dict = dict(entry.scan_masuk_hari) if entry.scan_masuk_hari else {}
        scan_pulang_dict = dict(entry.scan_pulang_hari) if entry.scan_pulang_hari else {}
        
        entry_changed = False
        for d in range(1, jumlah_hari + 1):
            if d in days_before_tmk:
                continue
            try:
                cell_date = datetime.date(selected_tahun, month_num, d)
            except ValueError:
                continue
                
            if cell_date < system_date:
                # Cek jika hari kerja (bukan sabtu/minggu, bukan hari libur)
                is_weekend = d in weekends
                is_holiday = d in holiday_days
                if not is_weekend and not is_holiday:
                    db_status = status_dict.get(str(d), '')
                    if not db_status:
                        status_dict[str(d)] = 'P'
                        scan_masuk_dict[str(d)] = ''
                        scan_pulang_dict[str(d)] = ''
                        entry_changed = True
                        
        if entry_changed:
            entry.status_hari = status_dict
            entry.scan_masuk_hari = scan_masuk_dict
            entry.scan_pulang_hari = scan_pulang_dict
            if entry.id is None:
                db.session.add(entry)
            db_changed = True
            
    if db_changed:
        db.session.commit()

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

def parse_time_str_to_minutes(time_str):
    if not time_str:
        return 0
    time_str = str(time_str).strip()
    try:
        parts = time_str.split(':')
        if len(parts) >= 2:
            h = int(parts[0])
            m = int(parts[1])
            return h * 60 + m
    except Exception:
        pass
    return 0

def time_to_minutes(t_obj):
    if not t_obj:
        return 0
    return t_obj.hour * 60 + t_obj.minute

def get_karyawan_jam_kerja_history(karyawan, kehadiran_entries=None, bulan_days_map=None, target_year=None, target_month=None):
    if kehadiran_entries is None:
        presences = db.session.execute(
            db.select(Kehadiran).where(Kehadiran.nik == karyawan.nik)
        ).scalars().all()
    else:
        presences = kehadiran_entries

    if bulan_days_map is None:
        bulans = db.session.execute(db.select(Bulan)).scalars().all()
        bulan_days_map = {b.nama: b.jumlah_hari for b in bulans}
    
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    NUMBER_TO_MONTH = {v: k for k, v in MONTH_NUMBERS.items()}
    
    presences = list(presences)
    
    # Get start year and month based on TMK
    start_year = None
    start_month = None
    if karyawan.tmk:
        for fmt in ("%Y-%m-%d", "%Y-%d-%m", "%d-%m-%Y"):
            try:
                raw_tmk = datetime.datetime.strptime(karyawan.tmk.strip(), fmt).date()
                start_year = raw_tmk.year
                start_month = raw_tmk.month
                break
            except (ValueError, AttributeError):
                continue

    # Fallback to earliest presence record if TMK is not parsed
    if presences and (start_year is None or start_month is None):
        earliest_p = min(presences, key=lambda p: (p.tahun, MONTH_NUMBERS.get(p.bulan, 1)))
        start_year = earliest_p.tahun
        start_month = MONTH_NUMBERS.get(earliest_p.bulan, 1)

    # Fallback to current date
    if start_year is None or start_month is None:
        today = datetime.date.today()
        start_year = today.year
        start_month = today.month

    # Get target year and month (selected month in UI or ref_date)
    target_y = None
    target_m = None
    if target_year and target_month:
        target_y = int(target_year)
        target_m = MONTH_NUMBERS.get(target_month) if isinstance(target_month, str) else int(target_month)
        
    latest_p_y = None
    latest_p_m = None
    if presences:
        latest_p = max(presences, key=lambda p: (p.tahun, MONTH_NUMBERS.get(p.bulan, 1)))
        latest_p_y = latest_p.tahun
        latest_p_m = MONTH_NUMBERS.get(latest_p.bulan, 1)
        
    from flask import session, has_request_context
    sim_date = None
    if has_request_context() and 'simulation_date' in session:
        try:
            sim_date = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
        except Exception:
            pass
    if not sim_date:
        sim_date = datetime.date.today()
        
    end_year = sim_date.year
    end_month = sim_date.month
    
    def to_months_val(y, m):
        return y * 12 + m if (y is not None and m is not None) else 0
        
    max_val = to_months_val(end_year, end_month)
    if target_y and target_m:
        max_val = max(max_val, to_months_val(target_y, target_m))
    if latest_p_y and latest_p_m:
        max_val = max(max_val, to_months_val(latest_p_y, latest_p_m))
        
    end_year = max_val // 12
    end_month = max_val % 12
    if end_month == 0:
        end_year -= 1
        end_month = 12

    # Generate sequential months to ensure carry-over flows correctly through gaps
    all_months = []
    curr_y, curr_m = start_year, start_month
    while (curr_y * 12 + curr_m) <= (end_year * 12 + end_month):
        all_months.append((curr_y, NUMBER_TO_MONTH[curr_m]))
        curr_m += 1
        if curr_m > 12:
            curr_m = 1
            curr_y += 1
            
    presence_map = {(p.tahun, p.bulan): p for p in presences}
    
    carry_over_penalty = 0
    history = {}
    
    s_start = time_to_minutes(karyawan.jam_masuk)
    s_end = time_to_minutes(karyawan.jam_pulang)
    s_dur = max(0, s_end - s_start - 60) if s_end > s_start else 0

    for (thn, bln) in all_months:
        p = presence_map.get((thn, bln))
        
        jumlah_hari = bulan_days_map.get(bln, 30)
            
        if bln == 'Februari':
            is_leap = (thn % 4 == 0 and (thn % 100 != 0 or thn % 400 == 0))
            jumlah_hari = 29 if is_leap else 28

        total_kekurangan_menit = 0
        total_penalti_menit = 0
        
        if p and p.status_hari:
            for d in range(1, jumlah_hari + 1):
                status = p.status_hari.get(str(d))
                if status == 'M':
                    scan_in = p.scan_masuk_hari.get(str(d))
                    scan_out = p.scan_pulang_hari.get(str(d))
                    
                    in_mins = parse_time_str_to_minutes(scan_in)
                    out_mins = parse_time_str_to_minutes(scan_out)
                    
                    if in_mins and in_mins > s_start + 30:
                        is_izin = bool(p.izin_hari.get(str(d))) if p.izin_hari else False
                        if not is_izin:
                            total_penalti_menit += (in_mins - s_start)
                    
                    if in_mins and out_mins:
                        if in_mins < s_start:
                            in_mins = s_start
                            
                    if in_mins and out_mins and out_mins > in_mins:
                        if in_mins < 13 * 60:
                            a_dur = max(0, (out_mins - in_mins) - 60)
                        else:
                            a_dur = max(0, out_mins - in_mins)
                        if a_dur < s_dur:
                            total_kekurangan_menit += (s_dur - a_dur)
                    else:
                        total_kekurangan_menit += s_dur
                        
        net_deficit = total_kekurangan_menit + total_penalti_menit
        total_combined = net_deficit + carry_over_penalty
        
        deduction = 0.5 * (total_combined // 240)
        
        if deduction > 0:
            next_carry_over = 0
        else:
            next_carry_over = total_combined
            
        history[(thn, bln)] = {
            'penalti_sebelumnya': carry_over_penalty,
            'kekurangan': total_kekurangan_menit,
            'penalti_terlambat': total_penalti_menit,
            'total': total_combined,
            'potong_cuti': deduction,
            'next_carry_over': next_carry_over
        }
        
        carry_over_penalty = next_carry_over
        
    return history

def calculate_jam_kerja_entries(selected_bulan, selected_tahun):
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()
    bulan_days_map = {b.nama: b.jumlah_hari for b in list_bulan}
    jumlah_hari = bulan_days_map.get(selected_bulan, 30)
    
    if selected_bulan == 'Februari':
        is_leap = (selected_tahun % 4 == 0 and (selected_tahun % 100 != 0 or selected_tahun % 400 == 0))
        jumlah_hari = 29 if is_leap else 28

    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(
            KaryawanEntry.pt,
            KaryawanEntry.divisi,
            db.func.coalesce(KaryawanEntry.departemen, ''),
            KaryawanEntry.priority_level.nulls_last(),
            KaryawanEntry.absen
        )
    ).scalars().all()

    active_karyawan = []
    for k in karyawan_list:
        if k.tanggal_resign:
            try:
                dt_resign = None
                for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                    try:
                        dt_resign = datetime.datetime.strptime(k.tanggal_resign, fmt).date()
                        break
                    except ValueError:
                        continue
                if dt_resign:
                    resign_month_start = datetime.date(dt_resign.year, dt_resign.month, 1)
                    selected_month_start = datetime.date(selected_tahun, month_num, 1)
                    if resign_month_start < selected_month_start:
                        continue
            except Exception:
                pass
        active_karyawan.append(k)

    presences = db.session.execute(
        db.select(Kehadiran).where(
            Kehadiran.bulan == selected_bulan,
            Kehadiran.tahun == selected_tahun
        )
    ).scalars().all()
    presence_map = {p.nik: p for p in presences}

    all_kehadiran = db.session.execute(db.select(Kehadiran)).scalars().all()
    kehadiran_by_nik = {}
    for p in all_kehadiran:
        if p.nik not in kehadiran_by_nik:
            kehadiran_by_nik[p.nik] = []
        kehadiran_by_nik[p.nik].append(p)
        
    all_cuti_manual = db.session.execute(db.select(CutiManual)).scalars().all()
    cuti_manual_by_nik = {}
    for c in all_cuti_manual:
        if c.nik not in cuti_manual_by_nik:
            cuti_manual_by_nik[c.nik] = []
        cuti_manual_by_nik[c.nik].append(c)

    weekends = [d for d in range(1, jumlah_hari + 1) if datetime.date(selected_tahun, month_num, d).weekday() in (5, 6)]
    all_holidays = db.session.execute(db.select(HariLibur)).scalars().all()
    holiday_days = {h.tanggal.day: h.keterangan for h in all_holidays if h.tanggal.month == month_num and h.tanggal.year == selected_tahun}

    entries = []
    for k in active_karyawan:
        total_masuk = 0
        total_alpa = 0
        total_wajib_menit = 0
        total_aktual_menit = 0
        total_kelebihan_menit = 0
        total_kekurangan_menit = 0
        total_penalti_menit = 0
        presence = presence_map.get(k.nik)

        if presence and presence.status_hari:
            s_start = time_to_minutes(k.jam_masuk)
            s_end = time_to_minutes(k.jam_pulang)
            s_dur = max(0, s_end - s_start - 60) if s_end > s_start else 0

            for d in range(1, jumlah_hari + 1):
                raw_status = presence.status_hari.get(str(d))
                is_weekend = d in weekends
                is_holiday = d in holiday_days
                is_libur = is_weekend or is_holiday

                if raw_status in ('OFF', 'L'):
                    if is_libur:
                        status = 'L'
                    else:
                        status = 'A'
                elif not raw_status and is_libur:
                    status = 'L'
                else:
                    status = raw_status

                if status == 'M':
                    total_masuk += 1
                    total_wajib_menit += s_dur
                    
                    scan_in = presence.scan_masuk_hari.get(str(d))
                    scan_out = presence.scan_pulang_hari.get(str(d))
                    
                    in_mins = parse_time_str_to_minutes(scan_in)
                    out_mins = parse_time_str_to_minutes(scan_out)
                    
                    if in_mins and in_mins > s_start + 30:
                        is_izin = bool(presence.izin_hari.get(str(d))) if (presence and presence.izin_hari) else False
                        if not is_izin:
                            total_penalti_menit += (in_mins - s_start)
                    
                    if in_mins and out_mins:
                        if in_mins < s_start:
                            in_mins = s_start
                            
                    if in_mins and out_mins and out_mins > in_mins:
                        if in_mins < 13 * 60:
                            a_dur = max(0, (out_mins - in_mins) - 60)
                        else:
                            a_dur = max(0, out_mins - in_mins)
                        total_aktual_menit += a_dur
                        
                        if a_dur > s_dur:
                            total_kelebihan_menit += (a_dur - s_dur)
                        elif a_dur < s_dur:
                            total_kekurangan_menit += (s_dur - a_dur)
                    else:
                        total_kekurangan_menit += s_dur
                elif status == 'A':
                    total_alpa += 1

        def format_mins(total_mins):
            h = total_mins // 60
            m = total_mins % 60
            if h == 0 and m == 0:
                return "0m"
            elif h == 0:
                return f"{m}m"
            elif m == 0:
                return f"{h}j"
            else:
                return f"{h}j {m}m"

        k_kehadiran = kehadiran_by_nik.get(k.nik, [])
        k_cuti_manual = cuti_manual_by_nik.get(k.nik, [])

        history = get_karyawan_jam_kerja_history(
            k, 
            kehadiran_entries=k_kehadiran,
            target_year=selected_tahun, 
            target_month=selected_bulan,
            bulan_days_map=bulan_days_map
        )
        info = history.get((selected_tahun, selected_bulan), {})
        penalti_sebelumnya_menit = info.get('penalti_sebelumnya', 0)
        total_gabungan_menit = info.get('total', total_kekurangan_menit + total_penalti_menit)
        potong_cuti = info.get('potong_cuti', 0.0)

        end_of_month = datetime.date(selected_tahun, month_num, jumlah_hari)
        cuti_info = get_cuti_tahunan_balance(
            k, 
            ref_date=end_of_month, 
            kehadiran_entries=k_kehadiran, 
            cuti_manual_entries=k_cuti_manual,
            bulan_days_map=bulan_days_map
        )
        saldo_awal = cuti_info['balance']
        saldo_akhir = max(0.0, saldo_awal - potong_cuti)

        entries.append({
            'nik': k.nik,
            'nama': k.nama,
            'pt': k.pt or '',
            'divisi': k.divisi or '',
            'jabatan': k.jabatan or '',
            'total_masuk': total_masuk,
            'total_alpa': total_alpa,
            'wajib': format_mins(total_wajib_menit),
            'aktual': format_mins(total_aktual_menit),
            'kelebihan': format_mins(total_kelebihan_menit),
            'kekurangan': format_mins(total_kekurangan_menit),
            'penalti': format_mins(total_penalti_menit),
            'penalti_sebelumnya': format_mins(penalti_sebelumnya_menit),
            'total': format_mins(total_gabungan_menit),
            'potong_cuti': f"{potong_cuti} hari" if potong_cuti > 0 else "-",
            'saldo_awal': f"{saldo_awal} hari" if saldo_awal > 0 else "0 hari",
            'saldo_akhir': f"{saldo_akhir} hari" if saldo_akhir > 0 else "0 hari"
        })
    return entries

@app.route('/master-jam-kerja')
def master_jam_kerja():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    INDONESIAN_MONTHS = {
        1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
        5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
        9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
    }

    default_bulan = None
    default_tahun = None
    if 'simulation_date' in session:
        try:
            sim_dt = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
            default_bulan = INDONESIAN_MONTHS.get(sim_dt.month)
            default_tahun = sim_dt.year
        except Exception:
            pass

    if not default_bulan:
        today = datetime.date.today()
        default_bulan = INDONESIAN_MONTHS.get(today.month)
        default_tahun = today.year

    selected_bulan = request.args.get('bulan', default_bulan)
    try:
        selected_tahun = int(request.args.get('tahun', default_tahun))
    except ValueError:
        selected_tahun = default_tahun

    entries = calculate_jam_kerja_entries(selected_bulan, selected_tahun)
    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()
    current_year = datetime.datetime.now().year
    list_tahun = list(range(current_year - 5, current_year + 6))

    return render_template(
        'sdm/master_jam_kerja.html',
        entries=entries,
        list_bulan=list_bulan,
        list_tahun=list_tahun,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        active_page='master-sdm'
    )

@app.route('/laporan-jam-kerja')
def laporan_jam_kerja():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    INDONESIAN_MONTHS = {
        1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
        5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
        9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
    }

    default_bulan = None
    default_tahun = None
    if 'simulation_date' in session:
        try:
            sim_dt = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
            default_bulan = INDONESIAN_MONTHS.get(sim_dt.month)
            default_tahun = sim_dt.year
        except Exception:
            pass

    if not default_bulan:
        today = datetime.date.today()
        default_bulan = INDONESIAN_MONTHS.get(today.month)
        default_tahun = today.year

    selected_bulan = request.args.get('bulan', default_bulan)
    try:
        selected_tahun = int(request.args.get('tahun', default_tahun))
    except ValueError:
        selected_tahun = default_tahun

    entries = calculate_jam_kerja_entries(selected_bulan, selected_tahun)
    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()
    current_year = datetime.datetime.now().year
    list_tahun = list(range(current_year - 5, current_year + 6))

    return render_template(
        'sdm/laporan_jam_kerja.html',
        entries=entries,
        list_bulan=list_bulan,
        list_tahun=list_tahun,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        active_page='sdm-report'
    )

@app.route('/laporan-jam-kerja/download', methods=['GET', 'POST'])
@csrf.exempt
def download_laporan_jam_kerja():
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    selected_bulan = request.values.get('bulan', '').strip()
    selected_tahun_str = request.values.get('tahun', '').strip()
    
    if not selected_bulan or not selected_tahun_str:
        flash("⚠️ Laporan tidak valid!", "danger")
        return redirect(url_for('laporan_jam_kerja'))
        
    try:
        selected_tahun = int(selected_tahun_str)
    except ValueError:
        flash("⚠️ Tahun tidak valid!", "danger")
        return redirect(url_for('laporan_jam_kerja'))

    import datetime
    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    list_bulan = db.session.execute(db.select(Bulan)).scalars().all()
    bulan_days_map = {b.nama: b.jumlah_hari for b in list_bulan}
    jumlah_hari = bulan_days_map.get(selected_bulan, 30)
    
    if selected_bulan == 'Februari':
        is_leap = (selected_tahun % 4 == 0 and (selected_tahun % 100 != 0 or selected_tahun % 400 == 0))
        jumlah_hari = 29 if is_leap else 28

    karyawan_list = db.session.execute(
        db.select(KaryawanEntry).order_by(
            KaryawanEntry.pt,
            KaryawanEntry.divisi,
            db.func.coalesce(KaryawanEntry.departemen, ''),
            KaryawanEntry.priority_level.nulls_last(),
            KaryawanEntry.absen
        )
    ).scalars().all()

    active_karyawan = []
    for k in karyawan_list:
        if k.tanggal_resign:
            try:
                dt_resign = None
                for fmt in ("%Y-%m-%d", "%Y-%d-%m"):
                    try:
                        dt_resign = datetime.datetime.strptime(k.tanggal_resign, fmt).date()
                        break
                    except ValueError:
                        continue
                if dt_resign:
                    resign_month_start = datetime.date(dt_resign.year, dt_resign.month, 1)
                    selected_month_start = datetime.date(selected_tahun, month_num, 1)
                    if resign_month_start < selected_month_start:
                        continue
            except Exception:
                pass
        active_karyawan.append(k)

    presences = db.session.execute(
        db.select(Kehadiran).where(
            Kehadiran.bulan == selected_bulan,
            Kehadiran.tahun == selected_tahun
        )
    ).scalars().all()
    presence_map = {p.nik: p for p in presences}

    kelebihan_rows = []
    kekurangan_rows = []

    for idx, k in enumerate(active_karyawan, 1):
        presence = presence_map.get(k.nik)
        s_start = time_to_minutes(k.jam_masuk)
        s_end = time_to_minutes(k.jam_pulang)
        s_dur = max(0, s_end - s_start - 60) if s_end > s_start else 0

        k_row_kelebihan = {'No': idx, 'NIK': k.nik, 'Nama Karyawan': k.nama}
        k_row_kekurangan = {'No': idx, 'NIK': k.nik, 'Nama Karyawan': k.nama}

        total_kelebihan = 0
        total_kekurangan = 0

        for d in range(1, jumlah_hari + 1):
            status = presence.status_hari.get(str(d)) if (presence and presence.status_hari) else None
            scan_in = presence.scan_masuk_hari.get(str(d)) if (presence and presence.scan_masuk_hari) else None
            scan_out = presence.scan_pulang_hari.get(str(d)) if (presence and presence.scan_pulang_hari) else None
            
            kelebihan_str = "-"
            kekurangan_str = "-"
            
            if status == 'M':
                in_mins = parse_time_str_to_minutes(scan_in)
                out_mins = parse_time_str_to_minutes(scan_out)
                
                if in_mins and out_mins:
                    if in_mins < s_start:
                        in_mins = s_start
                
                if in_mins and out_mins and out_mins > in_mins:
                    if in_mins < 13 * 60:
                        a_dur = max(0, (out_mins - in_mins) - 60)
                    else:
                        a_dur = max(0, out_mins - in_mins)
                    
                    if a_dur > s_dur:
                        diff = a_dur - s_dur
                        total_kelebihan += diff
                        kelebihan_str = f"{diff // 60}j {diff % 60}m"
                    elif a_dur < s_dur:
                        diff_kekurangan = s_dur - a_dur
                        total_kekurangan += diff_kekurangan
                        kekurangan_str = f"{diff_kekurangan // 60}j {diff_kekurangan % 60}m"
                else:
                    total_kekurangan += s_dur
                    kekurangan_str = f"{s_dur // 60}j {s_dur % 60}m"
            elif status == 'A':
                total_kekurangan += s_dur
                kekurangan_str = f"{s_dur // 60}j {s_dur % 60}m"

            k_row_kelebihan[str(d)] = kelebihan_str
            k_row_kekurangan[str(d)] = kekurangan_str

        def format_mins_local(total_mins):
            h = total_mins // 60
            m = total_mins % 60
            if h == 0 and m == 0:
                return "0m"
            elif h == 0:
                return f"{m}m"
            elif m == 0:
                return f"{h}j"
            else:
                return f"{h}j {m}m"

        k_row_kelebihan['Total'] = format_mins_local(total_kelebihan)
        k_row_kekurangan['Total'] = format_mins_local(total_kekurangan)

        kelebihan_rows.append(k_row_kelebihan)
        kekurangan_rows.append(k_row_kekurangan)

    import pandas as pd
    import io
    from flask import send_file

    df_kelebihan = pd.DataFrame(kelebihan_rows)
    df_kekurangan = pd.DataFrame(kekurangan_rows)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_kelebihan.to_excel(writer, sheet_name='Kelebihan', index=False)
        df_kekurangan.to_excel(writer, sheet_name='Kekurangan', index=False)
    output.seek(0)

    filename = f"Laporan_Jam_Kerja_Harian_{selected_bulan}_{selected_tahun}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route('/master-jam-kerja/detail/<nik>')
def master_jam_kerja_detail(nik):
    if 'logged_user' not in session:
        return redirect(url_for('login'))

    INDONESIAN_MONTHS = {
        1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
        5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
        9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
    }
    
    DAY_NAMES = {
        0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis',
        4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'
    }

    default_bulan = None
    default_tahun = None
    if 'simulation_date' in session:
        try:
            sim_dt = datetime.datetime.strptime(session['simulation_date'], "%Y-%m-%d").date()
            default_bulan = INDONESIAN_MONTHS.get(sim_dt.month)
            default_tahun = sim_dt.year
        except Exception:
            pass

    if not default_bulan:
        today = datetime.date.today()
        default_bulan = INDONESIAN_MONTHS.get(today.month)
        default_tahun = today.year

    selected_bulan = request.args.get('bulan', default_bulan)
    try:
        selected_tahun = int(request.args.get('tahun', default_tahun))
    except ValueError:
        selected_tahun = default_tahun

    MONTH_NUMBERS = {
        'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4,
        'Mei': 5, 'Juni': 6, 'Juli': 7, 'Agustus': 8,
        'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
    }
    month_num = MONTH_NUMBERS.get(selected_bulan, 1)

    karyawan = db.session.execute(
        db.select(KaryawanEntry).where(KaryawanEntry.nik == nik)
    ).scalar_one_or_none()
    if not karyawan:
        return "Karyawan tidak ditemukan", 404

    bulans = db.session.execute(db.select(Bulan)).scalars().all()
    bulan_days_map = {b.nama: b.jumlah_hari for b in bulans}
    jumlah_hari = bulan_days_map.get(selected_bulan, 30)
    
    if selected_bulan == 'Februari':
        is_leap = (selected_tahun % 4 == 0 and (selected_tahun % 100 != 0 or selected_tahun % 400 == 0))
        jumlah_hari = 29 if is_leap else 28

    presence = db.session.execute(
        db.select(Kehadiran).where(
            Kehadiran.nik == nik,
            Kehadiran.bulan == selected_bulan,
            Kehadiran.tahun == selected_tahun
        )
    ).scalar_one_or_none()

    s_start = time_to_minutes(karyawan.jam_masuk)
    s_end = time_to_minutes(karyawan.jam_pulang)
    s_dur = max(0, s_end - s_start - 60) if s_end > s_start else 0

    weekends = [d for d in range(1, jumlah_hari + 1) if datetime.date(selected_tahun, month_num, d).weekday() in (5, 6)]
    all_holidays = db.session.execute(db.select(HariLibur)).scalars().all()
    holiday_days = {h.tanggal.day: h.keterangan for h in all_holidays if h.tanggal.month == month_num and h.tanggal.year == selected_tahun}

    daily_details = []
    
    total_masuk = 0
    total_alpa = 0
    total_wajib_menit = 0
    total_aktual_menit = 0
    total_kelebihan_menit = 0
    total_kekurangan_menit = 0
    total_penalti_menit = 0

    for d in range(1, jumlah_hari + 1):
        try:
            dt = datetime.date(selected_tahun, month_num, d)
            day_name = DAY_NAMES.get(dt.weekday(), '')
        except ValueError:
            day_name = ''

        raw_status = presence.status_hari.get(str(d)) if (presence and presence.status_hari) else None
        scan_in = presence.scan_masuk_hari.get(str(d)) if (presence and presence.scan_masuk_hari) else None
        scan_out = presence.scan_pulang_hari.get(str(d)) if (presence and presence.scan_pulang_hari) else None
        keterangan = presence.keterangan_hari.get(str(d)) if (presence and presence.keterangan_hari) else None
        
        is_weekend = d in weekends
        is_holiday = d in holiday_days
        is_libur = is_weekend or is_holiday

        if raw_status in ('OFF', 'L'):
            if is_libur:
                status = 'L'
            else:
                status = 'A'
        elif not raw_status and is_libur:
            status = 'L'
        else:
            status = raw_status

        wajib_str = "-"
        aktual_str = "-"
        kelebihan_str = "-"
        kekurangan_str = "-"
        penalti_str = "-"
        diff_kekurangan = 0
        diff_penalti = 0
        
        if status == 'M':
            total_masuk += 1
            total_wajib_menit += s_dur
            wajib_str = f"{s_dur // 60}j {s_dur % 60}m"
            
            in_mins = parse_time_str_to_minutes(scan_in)
            out_mins = parse_time_str_to_minutes(scan_out)
            
            # Hitung penalti jam terlambat yang belum izin
            if in_mins and in_mins > s_start + 30:
                is_izin = bool(presence.izin_hari.get(str(d))) if (presence and presence.izin_hari) else False
                if not is_izin:
                    diff_penalti = in_mins - s_start
                    total_penalti_menit += diff_penalti
                    penalti_str = f"{diff_penalti // 60}j {diff_penalti % 60}m" if diff_penalti >= 60 else f"{diff_penalti}m"
            
            if in_mins and out_mins:
                if in_mins < s_start:
                    in_mins = s_start
            
            if in_mins and out_mins and out_mins > in_mins:
                if in_mins < 13 * 60:
                    a_dur = max(0, (out_mins - in_mins) - 60)
                else:
                    a_dur = max(0, out_mins - in_mins)
                total_aktual_menit += a_dur
                aktual_str = f"{a_dur // 60}j {a_dur % 60}m"
                
                if a_dur > s_dur:
                    diff = a_dur - s_dur
                    total_kelebihan_menit += diff
                    kelebihan_str = f"{diff // 60}j {diff % 60}m"
                elif a_dur < s_dur:
                    diff_kekurangan = s_dur - a_dur
                    total_kekurangan_menit += diff_kekurangan
                    kekurangan_str = f"{diff_kekurangan // 60}j {diff_kekurangan % 60}m"
            else:
                diff_kekurangan = s_dur
                total_kekurangan_menit += diff_kekurangan
                kekurangan_str = f"{s_dur // 60}j {s_dur % 60}m"
        elif status == 'A':
            total_alpa += 1

        daily_total_menit = diff_kekurangan + diff_penalti
        if daily_total_menit > 0:
            daily_total_str = f"{daily_total_menit // 60}j {daily_total_menit % 60}m" if daily_total_menit >= 60 else f"{daily_total_menit}m"
        else:
            daily_total_str = "-"

        daily_details.append({
            'tanggal': d,
            'hari': day_name,
            'status': status or '-',
            'scan_masuk': scan_in or '-',
            'scan_pulang': scan_out or '-',
            'wajib': wajib_str,
            'aktual': aktual_str,
            'kelebihan': kelebihan_str,
            'kekurangan': kekurangan_str,
            'penalti': penalti_str,
            'total': daily_total_str,
            'keterangan': keterangan or '-'
        })

    def format_mins(total_mins):
        h = total_mins // 60
        m = total_mins % 60
        if h == 0 and m == 0:
            return "0m"
        elif h == 0:
            return f"{m}m"
        elif m == 0:
            return f"{h}j"
        else:
            return f"{h}j {m}m"

    history = get_karyawan_jam_kerja_history(karyawan, target_year=selected_tahun, target_month=selected_bulan, bulan_days_map=bulan_days_map)
    info = history.get((selected_tahun, selected_bulan), {})
    penalti_sebelumnya = info.get('penalti_sebelumnya', 0)
    total_gabungan_menit = info.get('total', total_kekurangan_menit + total_penalti_menit)
    potong_cuti = info.get('potong_cuti', 0.0)

    # Get leave balance
    end_of_month = datetime.date(selected_tahun, month_num, jumlah_hari)
    cuti_info = get_cuti_tahunan_balance(karyawan, ref_date=end_of_month, bulan_days_map=bulan_days_map)
    saldo_awal = cuti_info['balance']
    saldo_akhir = max(0.0, saldo_awal - potong_cuti)

    summary = {
        'total_masuk': total_masuk,
        'total_alpa': total_alpa,
        'wajib': format_mins(total_wajib_menit),
        'aktual': format_mins(total_aktual_menit),
        'kelebihan': format_mins(total_kelebihan_menit),
        'kekurangan': format_mins(total_kekurangan_menit),
        'penalti': format_mins(total_penalti_menit),
        'penalti_sebelumnya': format_mins(penalti_sebelumnya),
        'total': format_mins(total_gabungan_menit),
        'potong_cuti': f"{potong_cuti} hari" if potong_cuti > 0 else "0",
        'saldo_awal': f"{saldo_awal} hari" if saldo_awal > 0 else "0 hari",
        'saldo_akhir': f"{saldo_akhir} hari" if saldo_akhir > 0 else "0 hari"
    }

    current_year = datetime.datetime.now().year
    list_tahun = list(range(current_year - 5, current_year + 6))

    return render_template(
        'sdm/master_jam_kerja_detail.html',
        karyawan=karyawan,
        daily_details=daily_details,
        summary=summary,
        selected_bulan=selected_bulan,
        selected_tahun=selected_tahun,
        list_bulan=bulans,
        list_tahun=list_tahun,
        active_page='sdm-report'
    )



