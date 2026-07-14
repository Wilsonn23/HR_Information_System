# ===============================================================================================================
# IMPORT AND SETUP
# ===============================================================================================================

from flask import Flask, render_template, request, redirect, url_for, Response, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Integer, Sequence, text, select, or_
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.exc import IntegrityError
from psycopg2.errors import UniqueViolation
from dotenv import load_dotenv
from flask import jsonify
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, EmailField, SubmitField, FloatField, SelectField, DateField
from wtforms.validators import DataRequired, Optional, NumberRange, Email, Length
from datetime import datetime, timedelta
from collections import defaultdict
from werkzeug.security import check_password_hash, generate_password_hash
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

import csv
import io
import os
import urllib
import click
import pandas as pd

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'StringAcakYangSangatPanjangDanRahasia')

app.config['SESSION_COOKIE_HTTPONLY'] = True

app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

csrf = CSRFProtect(app)

# ===============================================================================================================
# VARIABLES AND CONFIGURATION
# ===============================================================================================================

class Base(DeclarativeBase):
    pass

RAW_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "insurance_app")

if RAW_PASSWORD:
    DB_PASSWORD = urllib.parse.quote_plus(RAW_PASSWORD)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"postgresql://postgres:{DB_PASSWORD}@localhost:5432/{DB_NAME}"

@app.before_request
def batasi_akses_global():
    if request.path == '/login' or request.path == '/':
        return None 
        
    if 'logged_in' not in session:
        flash("Silakan login terlebih dahulu untuk mengakses halaman tersebut.", "warning")
        return redirect(url_for('login'))

# ===============================================================================================================
# DATABASE INITIALIZATION
# ===============================================================================================================

db = SQLAlchemy(model_class=Base)
db.init_app(app)

with app.app_context():
    db.create_all()

# ===============================================================================================================
# CLASS DEFINITIONS
# ===============================================================================================================

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    pkey: Mapped[str] = mapped_column(db.String(150), nullable=False) 
    aksi: Mapped[str] = mapped_column(db.String(20), nullable=False) 
    kolom_diubah: Mapped[str] = mapped_column(db.Text, nullable=True) 
    nilai_lama: Mapped[str] = mapped_column(db.Text, nullable=True) 
    nilai_baru: Mapped[str] = mapped_column(db.Text, nullable=True) 
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class UnitImage(db.Model):
    __tablename__ = 'unit_images'
    
    id = db.mapped_column(db.Integer, primary_key=True, autoincrement=True)
    pkey = db.mapped_column(db.String(150), db.ForeignKey('data_entries.pkey'), nullable=False) # Hubungkan dengan CN Utama
    filename = db.mapped_column(db.String(255), nullable=False)     # Menyimpan nama asli file (misal: depan.jpg)
    file_data = db.mapped_column(db.LargeBinary, nullable=False)    # Menyimpan data biner gambar asli (BLOB/BYTEA)

class DataEntry(db.Model):
    __tablename__ = "data_entries"
    
    #Primary
    id: Mapped[int] = mapped_column(Integer, Sequence("id"), unique=True, nullable=False)
    pulau: Mapped[str] = mapped_column(nullable=False)
    kota: Mapped[str] = mapped_column(nullable=False)
    pt: Mapped[str] = mapped_column(nullable=False)
    unit: Mapped[str] = mapped_column(nullable=False)
    kode_unit: Mapped[str] = mapped_column(nullable=False)
    pkey: Mapped[str] = mapped_column(primary_key=True, nullable=False)
    lokasi_kerja: Mapped[str] = mapped_column(nullable=False)

    #Details
    nama_asuransi: Mapped[str] = mapped_column(nullable=False)
    no_polis: Mapped[str] = mapped_column(nullable=False)
    no_polisi: Mapped[str] = mapped_column(nullable=True)
    merk: Mapped[str] = mapped_column(nullable=False)
    kategori: Mapped[str] = mapped_column(nullable=False)
    eqp_model: Mapped[str] = mapped_column(nullable=False)
    sn_equipment: Mapped[str] = mapped_column(nullable=False)
    sn_engine: Mapped[str] = mapped_column(nullable=False)
    status_stnk: Mapped[str] = mapped_column(nullable=False)
    status_asuransi: Mapped[str] = mapped_column(nullable=False)
    tanggal_berakhir_stnk: Mapped[str] = mapped_column(nullable=True)
    tanggal_berakhir_asuransi: Mapped[str] = mapped_column(nullable=True)
    year: Mapped[int] = mapped_column(nullable=False)

    #Payment
    biaya_perpanjang_stnk: Mapped[float] = mapped_column(default=0.0)
    biaya_administrasi_stnk: Mapped[float] = mapped_column(default=0.0)
    biaya_perpanjang_asuransi: Mapped[float] = mapped_column(default=0.0)
    biaya_administrasi_asuransi: Mapped[float] = mapped_column(default=0.0)
    pembulatan_stnk: Mapped[float] = mapped_column(default=0.0)
    pembulatan_asuransi: Mapped[float] = mapped_column(default=0.0)
    total_stnk: Mapped[float] = mapped_column(default=0.0)
    total_asuransi: Mapped[float] = mapped_column(default=0.0)
    harus_dibayar_stnk: Mapped[float] = mapped_column(default=0.0)
    harus_dibayar_asuransi: Mapped[float] = mapped_column(default=0.0)
    
    #Other
    notes: Mapped[str] = mapped_column(nullable=True)
    tanggal_input: Mapped[str] = mapped_column(nullable=True)
    diinput_oleh: Mapped[str] = mapped_column(nullable=True)

class ReportEntry(db.Model):
    __tablename__ = "report_entries"

    jenis: Mapped[str] = mapped_column(nullable=False)
    id: Mapped[int] = mapped_column(Integer, Sequence("id"), unique=True, primary_key=True, nullable=False)
    pkey: Mapped[str] = mapped_column(nullable=False)
    status_pembayaran: Mapped[str] = mapped_column(nullable=True)
    tanggal_berakhir_baru: Mapped[str] = mapped_column(nullable=True)
    jumlah_dibayar:Mapped[float] = mapped_column(nullable=False) 
    sisa_tagihan:Mapped[float] = mapped_column(nullable=False)
    tanggal_bayar: Mapped[str] = mapped_column(nullable=False)
    tanggal_input: Mapped[str] = mapped_column(nullable=False)
    diinput_oleh: Mapped[str] = mapped_column(nullable=False)

class UserEntry(db.Model):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(db.String(255), nullable=False)
    role: Mapped[str] = mapped_column(db.String(20), default='user')

class UserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=50)])
    password = StringField('Password (Isi jika ingin diubah)', validators=[Optional(), Length(min=6)])
    role = SelectField('Role', choices=[('user', 'Staff Operasional'), ('admin', 'Administrator')], validators=[DataRequired()])
    submit = SubmitField('Simpan Pengguna')

PULAU_KOTA_MAPPING = {
    'SUMATRA': [
        ('PALEMBANG', 'Palembang'),
        ('JAMBI', 'Jambi'),
        ('BANGKA', 'Bangka')
    ],
    'NUSA TENGGARA BARAT': [
        ('LOMBOK', 'Lombok'),
    ],
    'JAWA': [
        ('JAKARTA', 'Jakarta')
    ],
    'PAPUA': [
        ('MERAUKE', 'Merauke')
    ]
}

def get_kota_choices(selected_pulau=None):
    mapping = {k: list(v) for k, v in PULAU_KOTA_MAPPING.items()}
    try:
        db_entries = db.session.execute(
            db.select(DataEntry.pulau, DataEntry.kota).distinct()
        ).all()
        for p, k in db_entries:
            if p and k:
                p_upper = p.upper().strip()
                k_upper = k.upper().strip()
                if p_upper not in mapping:
                    mapping[p_upper] = []
                existing_keys = [item[0] for item in mapping[p_upper]]
                if k_upper not in existing_keys:
                    mapping[p_upper].append((k_upper, k_upper.title()))
    except Exception:
        pass

    if selected_pulau:
        p_upper = selected_pulau.upper().strip()
        choices = mapping.get(p_upper, [])
        return sorted(choices, key=lambda x: x[1])
    
    all_choices = []
    seen = set()
    for p, choices in mapping.items():
        for val, label in choices:
            if val not in seen:
                all_choices.append((val, label))
                seen.add(val)
    return sorted(all_choices, key=lambda x: x[1])

def get_pt_choices(selected_kota=None):
    if not selected_kota:
        return []
    try:
        kota_upper = selected_kota.upper().strip()
        db_entries = db.session.execute(
            db.select(DataEntry.pt).where(db.func.upper(DataEntry.kota) == kota_upper).distinct()
        ).scalars().all()
        
        choices = []
        seen = set()
        for pt_val in db_entries:
            if pt_val:
                pt_upper = pt_val.upper().strip()
                if pt_upper not in seen:
                    choices.append((pt_upper, pt_upper))
                    seen.add(pt_upper)
        return sorted(choices, key=lambda x: x[1])
    except Exception as e:
        print(f"Error in get_pt_choices: {e}")
        return []

def get_unit_choices(selected_pt=None):
    if not selected_pt:
        return []
    try:
        pt_upper = selected_pt.upper().strip()
        db_entries = db.session.execute(
            db.select(DataEntry.unit).where(db.func.upper(DataEntry.pt) == pt_upper).distinct()
        ).scalars().all()
        
        choices = []
        seen = set()
        for unit_val in db_entries:
            if unit_val:
                unit_upper = unit_val.upper().strip()
                if unit_upper not in seen:
                    choices.append((unit_upper, unit_upper))
                    seen.add(unit_upper)
        return sorted(choices, key=lambda x: x[1])
    except Exception as e:
        print(f"Error in get_unit_choices: {e}")
        return []

def get_cn_choices(selected_unit=None):
    if not selected_unit:
        return []
    try:
        unit_upper = selected_unit.upper().strip()
        db_entries = db.session.execute(
            db.select(DataEntry.pkey, DataEntry.kode_unit).where(db.func.upper(DataEntry.unit) == unit_upper).distinct()
        ).all()
        
        choices = []
        seen = set()
        for pkey_val, cn_val in db_entries:
            if pkey_val and cn_val:
                pkey_clean = pkey_val.strip()
                cn_clean = cn_val.strip()
                if pkey_clean not in seen:
                    choices.append((pkey_clean, cn_clean))
                    seen.add(pkey_clean)
        return sorted(choices, key=lambda x: x[1])
    except Exception as e:
        print(f"Error in get_cn_choices: {e}")
        return []

class DataForm(FlaskForm):
    #Primary
    pulau = SelectField('Pulau', choices=[
        ('', '-- Pilih Pulau --'),
        ('SUMATRA', 'Sumatra'),
        ('NUSA TENGGARA BARAT', 'Nusa Tenggara Barat'),
        ('JAWA', 'Jawa'),
        ('PAPUA', 'Papua')
    ], validators=[DataRequired(message="Pulau wajib diisi!")])
    kota = SelectField('Kota', choices=[], validators=[DataRequired(message="Kota wajib diisi!")])
    pt = StringField('Nama PT', validators=[DataRequired(message="Nama PT wajib diisi!"), Length(max=100)])
    unit = StringField('Unit PT', validators=[DataRequired(message="Nama Unit PT wajib diisi!"), Length(max=100)])
    kode_unit = StringField('Kode Unit', validators=[DataRequired(message="Kode Unit wajib diisi!"), Length(max=100)])
    pkey = StringField('PKEY', validators=[Optional()])
    lokasi_kerja = StringField('Lokasi Kerja', validators=[DataRequired(message="Lokasi Kerja wajib diisi!"), Length(max=100)])

    #Details
    nama_asuransi = StringField('Nama Asuransi', validators=[DataRequired(message="Nama Asuransi wajib diisi!")])
    no_polis = StringField('No Polis', validators=[DataRequired(message="No. Polis wajib diisi!"), Length(max=20)])
    no_polisi = StringField('No Polisi', validators=[DataRequired(message="No. Polisi wajib diisi!"), Length(max=20)])
    merk = StringField('Merk', validators=[DataRequired(message="Merk wajib diisi!"), Length(max=20)])
    kategori = StringField('Kategori', validators=[DataRequired(message="Kategori wajib diisi!"), Length(max=20)])
    eqp_model = StringField('Equipment Model', validators=[DataRequired(message="Model Alat wajib diisi!"), Length(max=20)])
    sn_equipment = StringField('S/N Equipment', validators=[DataRequired(message="No. Rangka wajib diisi!"), Length(max=20)])
    sn_engine = StringField('S/N Engine', validators=[DataRequired(message="No. Mesin wajib diisi!"), Length(max=20)])
    
    status_stnk = SelectField('Status STNK', choices=[('OFF', 'OFF'), ('ON', 'ON')], validators=[DataRequired()])
    status_asuransi = SelectField('Status Asuransi', choices=[('OFF', 'OFF'), ('ON', 'ON')], validators=[DataRequired()])
    tanggal_berakhir_stnk = DateField('Tanggal Berakhir STNK', validators=[Optional()])
    tanggal_berakhir_asuransi = DateField('Tanggal Berakhir Asuransi', validators=[Optional()])
    
    year = StringField('Tahun Pembuatan', validators=[DataRequired(message="Tahun harus diisi!"), Length(min=4, max=4, message="Tahun harus 4 digit!")])
    
    biaya_perpanjang_stnk = StringField('Biaya Perpanjang STNK', validators=[Optional()])
    biaya_administrasi_stnk = StringField('Biaya Admin STNK', validators=[Optional()])
    biaya_perpanjang_asuransi = StringField('Biaya Perpanjang Asuransi', validators=[Optional()])
    biaya_administrasi_asuransi = StringField('Biaya Admin Asuransi', validators=[Optional()])

    notes = StringField('Notes', validators=[Optional()])

class ExtendForm(FlaskForm):
    jenis = SelectField(
        'Jenis', 
        choices=[('STNK', 'STNK'), ('Asuransi', 'Asuransi')]
    )
    cn = StringField('CN', validators=[
        DataRequired(message="CN tidak boleh kosong.")])
    pulau = SelectField('Pulau', choices=[
        ('', '-- Pilih Pulau --'),
        ('SUMATRA', 'Sumatra'),
        ('NUSA TENGGARA BARAT', 'Nusa Tenggara Barat'),
        ('JAWA', 'Jawa'),
        ('PAPUA', 'Papua')
    ], validators=[DataRequired(message="Pulau wajib diisi!")])
    kota = SelectField('Kota', choices=[], validators=[DataRequired(message="Kota wajib diisi!")])
    pt = SelectField('Nama PT', choices=[], validators=[
        DataRequired(message="Nama PT tidak boleh kosong.")])
    unit = SelectField('Nama Unit', choices=[], validators=[
        DataRequired(message="Nama Unit tidak boleh kosong.")])
    tanggal_berakhir_baru = DateField('Tanggal Berakhir', format='%Y-%m-%d', validators=[Optional()])
    jumlah_dibayar = StringField('Biaya Administrasi', validators=[
        DataRequired(message="Jumlah dibayar tidak boleh kosong.") 
    ])
    tanggal_bayar = DateField('Tanggal Berakhir', format='%Y-%m-%d', validators=[DataRequired(message="Tanggal tidak boleh kosong.")])

# ===============================================================================================================
# ROUTING
# ===============================================================================================================

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/users', methods=['GET', 'POST'])
def manage_users():
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
                return redirect(url_for('manage_users'))

    all_users = db.session.execute(db.select(UserEntry).order_by(UserEntry.id)).scalars().all()
    return render_template('users.html', form=form, users=all_users, active_page='users')

@app.route('/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'logged_user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    user_to_delete = db.session.get(UserEntry, user_id)
    
    if user_to_delete and user_to_delete.username == session['logged_user']:
        flash("⚠️ Anda tidak bisa menghapus akun Anda sendiri yang sedang aktif digunakan!", "danger")
    elif user_to_delete:
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"Akun pengguna berhasil dihapus dari sistem.", "success")
    
    return redirect(url_for('manage_users'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        query = text("SELECT id, username, password, role FROM users WHERE username = :username")
        result = db.session.execute(query, {"username": username}).fetchone()
        
        if result and check_password_hash(result.password, password):
            # Regenerasi session ID baru untuk mencegah Session Fixation Attack
            session.clear()
            
            # Set cookie session aman
            session['logged_in'] = True
            session['result_id'] = result.id
            session['logged_user'] = result.username
            session['role'] = result.role
            
            return redirect(url_for('dashboard'))
        else:
            flash("Username atau Password salah!", "danger")
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/logs')
def view_audit_logs():
    # 1. Pastikan user sudah login
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    
    # 2. Batasi akses: Hanya user dengan role 'admin' yang boleh masuk
    if session.get('role') != 'admin':
        flash("⚠️ Anda tidak memiliki izin (Akses Ditolak) untuk membuka halaman Jejak Audit.", "danger")
        return redirect(url_for('dashboard'))
    
    # 3. Ambil semua data logs, urutkan dari yang paling baru (teranyar)
    all_logs = db.session.execute(
        db.select(AuditLog).order_by(AuditLog.tanggal_aksi.desc())
    ).scalars().all()
    
    # 4. Tampilkan ke template baru dengan mengirim parameter active_page='logs'
    return render_template('logs.html', logs=all_logs, active_page='logs')

@app.route('/master', methods=['GET'])
def master():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(DataEntry)
    ).scalars().all()
    return render_template('master.html', entries=all_entries, active_page='master')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    check_and_update_expired_units()
    query = text("SELECT COUNT(*) FROM data_entries")
    total_peralatan=db.session.execute(query).scalar()

    today = datetime.now().date()
    
    query = text("SELECT COUNT(*) FROM data_entries WHERE :today <= tanggal_berakhir_stnk::date")
    jumlah_stnk_aktif=db.session.execute(query, {"today": today}).scalar()

    query = text("SELECT COUNT(*) FROM data_entries WHERE :today <= tanggal_berakhir_asuransi::date")
    jumlah_asuransi_aktif=db.session.execute(query, {"today": today}).scalar()

    hari_ini = today.strftime('%Y-%m-%d')
    satu_bulan_lagi = (today + timedelta(days=30)).strftime('%Y-%m-%d')
    tiga_bulan_lagi = (today + timedelta(days=90)).strftime('%Y-%m-%d')

    stnk_expired = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk < hari_ini).all()
    stnk_notice = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk >= satu_bulan_lagi, DataEntry.tanggal_berakhir_stnk <= tiga_bulan_lagi).all()
    stnk_warning = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk >= hari_ini, DataEntry.tanggal_berakhir_stnk <= satu_bulan_lagi).all()
    stnk_none = DataEntry.query.filter((DataEntry.tanggal_berakhir_stnk == None)).all()
    
    asuransi_expired = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi < hari_ini).all()
    asuransi_notice = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi >= satu_bulan_lagi, DataEntry.tanggal_berakhir_asuransi <= tiga_bulan_lagi).all()
    asuransi_warning = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi >= hari_ini, DataEntry.tanggal_berakhir_asuransi <= satu_bulan_lagi).all()
    asuransi_none = DataEntry.query.filter((DataEntry.tanggal_berakhir_asuransi == None)).all()

    return render_template(
        'dashboard.html', 
        active_page='dashboard', 
        total_peralatan=total_peralatan, 
        jumlah_stnk_aktif=jumlah_stnk_aktif, 
        jumlah_asuransi_aktif=jumlah_asuransi_aktif,
        stnk_expired=stnk_expired,
        stnk_notice=stnk_notice,
        stnk_warning=stnk_warning,
        stnk_none=stnk_none,
        asuransi_expired=asuransi_expired,
        asuransi_notice=asuransi_notice,
        asuransi_warning=asuransi_warning,
        asuransi_none=asuransi_none           
    )

@app.route('/transaksi')
def transaksi():
    return render_template('transaksi.html', active_page='transaksi')

@app.route('/entry')
def database():
    form = DataForm()
    form.kota.choices = [('', '-- Pilih Kota --')]
    return render_template('form.html', form=form, active_page='entry')

@app.route('/perpanjang')
def perpanjang():
    form = ExtendForm()
    form.kota.choices = [('', '-- Pilih Kota --')]
    form.pt.choices = [('', '-- Pilih PT --')]
    form.unit.choices = [('', '-- Pilih Unit --')]
    return render_template('perpanjang.html', form=form, active_page='perpanjang')

@app.route('/report')
def report():
    group_by = request.args.get('groupby', 'ALL')
    
    query = (
        db.select(DataEntry, ReportEntry)
        .join(ReportEntry, DataEntry.pkey == ReportEntry.pkey)
        .order_by(DataEntry.id.desc())
    )
    
    results = db.session.execute(query).all()
    
    grouped_data = {}
    
    if group_by == 'ALL':
        grouped_data = {'ALL': results}
        
    else:
        grouped_dict = defaultdict(list)
        for entry, report_entry in results:
            if group_by == 'tahun_bayar':
                if report_entry and report_entry.tanggal_bayar:
                    tgl = report_entry.tanggal_bayar
                    if isinstance(tgl, str):
                        # Mengambil 4 karakter pertama (Contoh: "2026-07-08" -> "2026")
                        key_name = tgl[:4]
                    else:
                        # Jika tipe datanya sudah berupa objek Date/Datetime asli
                        key_name = str(tgl.year)
                else:
                    key_name = "Tidak Ada Data Tanggal"
            else:
                val = getattr(entry, group_by, None) or getattr(report_entry, group_by, None)
                key_name = val if val else "Tidak Ada Data"
            grouped_dict[key_name].append((entry, report_entry))
        grouped_data = dict(grouped_dict)

    return render_template(
        'report.html', 
        grouped_data=grouped_data, 
        active_filter=group_by,
        active_page='report'
    )

@app.route('/details')
@app.route('/details/<pkey>')
def details(pkey=None):
    all_cn_list = db.session.execute(db.select(DataEntry.kode_unit).order_by(DataEntry.kode_unit)).scalars().all()
    
    if not pkey:        
        return render_template('details.html', entry=None, all_cn_list=all_cn_list, active_page='details')
    
    entry = db.session.execute(
        db.select(DataEntry).where(DataEntry.pkey == pkey)
    ).scalar_one_or_none()
    
    if not entry:
        flash("Data unit tidak ditemukan!", "danger")
        return redirect(url_for('details'))
        
    key = entry.pkey

    db_images = db.session.execute(
        db.select(UnitImage.id).where(UnitImage.pkey == key).order_by(UnitImage.id)
    ).scalars().all()
        
    return render_template('details.html', all_cn_list=all_cn_list, entry=entry, db_images=db_images, active_page='details')

@app.route('/submit_extend', methods=['POST'])
def submit_extend():
    form = ExtendForm()

    form.kota.choices = get_kota_choices(form.pulau.data)
    form.pt.choices = get_pt_choices(form.kota.data)
    form.unit.choices = get_unit_choices(form.pt.data)

    if form.validate_on_submit():
        def clean_numeric_input(val):
            if not val:
                return 0.0
            val_str = str(val).strip()
            val_str = val_str.replace('.', '').replace(',', '.')
            try:
                return round(float(val_str), 2)
            except ValueError:
                return 0.0

        jumlah_dibayar = clean_numeric_input(form.jumlah_dibayar.data)
        cn = form.cn.data
        jenis = form.jenis.data

        entry = db.session.execute(
            db.select(DataEntry).where(
                db.func.upper(DataEntry.kode_unit) == cn.upper().strip(),
                db.func.upper(DataEntry.pulau) == form.pulau.data.upper().strip(),
                db.func.upper(DataEntry.kota) == form.kota.data.upper().strip(),
                db.func.upper(DataEntry.pt) == form.pt.data.upper().strip(),
                db.func.upper(DataEntry.unit) == form.unit.data.upper().strip()
            )
        ).scalar_one_or_none()

        if not entry:
            flash("Data unit tidak ditemukan!", "danger")
            return render_template('perpanjang.html', form=form)

        pkey = entry.pkey

        try:
            if jenis == "STNK":
                old_tagihan = entry.harus_dibayar_stnk
                old_status = entry.status_stnk
                old_tanggal = entry.tanggal_berakhir_stnk
                
                sisa = old_tagihan - jumlah_dibayar
                if sisa <= 0:
                    sisa = 0.0
                    status_pembayaran = "Lunas"
                    entry.status_stnk = "ON"
                    if form.tanggal_berakhir_baru.data:
                        entry.tanggal_berakhir_stnk = form.tanggal_berakhir_baru.data
                else:
                    status_pembayaran = "Belum Lunas"
                
                entry.harus_dibayar_stnk = sisa
                
                old_val_str = f"Status: {old_status}, Masa Berlaku: {old_tanggal or '-'}, Tagihan: Rp {old_tagihan:,.2f}"
                new_val_str = f"Masa Berlaku Baru: {entry.tanggal_berakhir_stnk or '-'}, Sisa Tagihan: Rp {sisa:,.2f}"
                
            else: # Asuransi
                old_tagihan = entry.harus_dibayar_asuransi
                old_status = entry.status_asuransi
                old_tanggal = entry.tanggal_berakhir_asuransi
                
                sisa = old_tagihan - jumlah_dibayar
                if sisa <= 0:
                    sisa = 0.0
                    status_pembayaran = "Lunas"
                    entry.status_asuransi = "ON"
                    if form.tanggal_berakhir_baru.data:
                        entry.tanggal_berakhir_asuransi = form.tanggal_berakhir_baru.data
                else:
                    status_pembayaran = "Belum Lunas"
                
                entry.harus_dibayar_asuransi = sisa
                
                old_val_str = f"Status: {old_status}, Masa Berlaku: {old_tanggal or '-'}, Tagihan: Rp {old_tagihan:,.2f}"
                new_val_str = f"Masa Berlaku Baru: {entry.tanggal_berakhir_asuransi or '-'}, Sisa Tagihan: Rp {sisa:,.2f}"

            old_val_str = old_val_str.replace(',', 'X').replace('.', ',').replace('X', '.')
            new_val_str = new_val_str.replace(',', 'X').replace('.', ',').replace('X', '.')
            bayar_formatted = f"{jumlah_dibayar:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

            if status_pembayaran == "Lunas":
                query_update_reports = text(
                    "UPDATE report_entries SET status_pembayaran = :status_pembayaran WHERE pkey = :pkey and jenis = :jenis"
                )
                db.session.execute(query_update_reports, {"status_pembayaran": status_pembayaran, "pkey": pkey, "jenis": jenis})

            new_record = ReportEntry(
                jenis=jenis,
                pkey=pkey,
                status_pembayaran=status_pembayaran,
                tanggal_berakhir_baru=form.tanggal_berakhir_baru.data if form.tanggal_berakhir_baru.data else None,
                jumlah_dibayar=jumlah_dibayar,
                sisa_tagihan=sisa,
                tanggal_bayar=form.tanggal_bayar.data,
                tanggal_input=datetime.today().date(),
                diinput_oleh=session.get('logged_user', 'System')
            )
            db.session.add(new_record)

            # Tambahkan Audit Log
            log_extend = AuditLog(
                pkey=pkey,
                aksi="EDIT",
                kolom_diubah=f"Perpanjang {jenis}",
                nilai_lama=old_val_str,
                nilai_baru=f"Bayar: Rp {bayar_formatted} ({status_pembayaran}). {new_val_str}",
                dilakukan_oleh=session.get('logged_user', 'System')
            )
            db.session.add(log_extend)

            db.session.commit()
            return redirect(url_for('dashboard'))
                
        except Exception as e:
            db.session.rollback()
            flash(f"Unexpected database error: {e}", "danger")
    
    if form.errors:
        print(form.errors)

    return render_template('perpanjang.html', form=form)

@app.route('/submit_data', methods=['POST'])
def submit_data():
    form = DataForm()
    form.kota.choices = get_kota_choices(form.pulau.data)

    if form.validate_on_submit():
        def clean_numeric_input(val):
            if not val:
                return 0.0
            val_str = str(val).strip()
            val_str = val_str.replace('.', '').replace(',', '.')
            try:
                return round(float(val_str), 2)
            except ValueError:
                return 0.0

        biaya_perpanjang_stnk = clean_numeric_input(form.biaya_perpanjang_stnk.data)
        biaya_admin_stnk = clean_numeric_input(form.biaya_administrasi_stnk.data)

        total_stnk = biaya_perpanjang_stnk + biaya_admin_stnk
        
        total_terpembulat_stnk = float(round(total_stnk, 0))
        
        pembulatan_otomatis_stnk = round(total_terpembulat_stnk - total_stnk, 2)

        biaya_perpanjang_asuransi = clean_numeric_input(form.biaya_perpanjang_asuransi.data)
        biaya_admin_asuransi = clean_numeric_input(form.biaya_administrasi_asuransi.data)

        total_asuransi = biaya_perpanjang_asuransi + biaya_admin_asuransi
        
        total_terpembulat_asuransi = float(round(total_asuransi, 0))
        
        pembulatan_otomatis_asuransi = round(total_terpembulat_asuransi - total_asuransi, 2)

        if (biaya_perpanjang_stnk <= 0 or biaya_admin_stnk <= 0 or 
            biaya_perpanjang_asuransi <= 0 or biaya_admin_asuransi <= 0):
            flash("⚠️ Semua rincian biaya (STNK & Asuransi) wajib diisi dan tidak boleh bernilai 0!", "danger")

            return render_template('form.html', form=form)

        new_record = DataEntry(
            pulau=form.pulau.data,
            kota=form.kota.data,
            pt=form.pt.data.upper().strip(),
            unit=form.pt.data.upper().strip()+"-"+form.unit.data.upper().strip(),
            kode_unit=form.kode_unit.data.upper().replace(" ", ""),
            pkey=form.pulau.data+"-"+form.kota.data+"-"+form.pt.data.upper().strip()+"-"+form.unit.data.upper().strip()+"-"+form.kode_unit.data.upper().replace(" ", ""),
            lokasi_kerja=form.lokasi_kerja.data.upper().strip() if form.lokasi_kerja.data else None,

            nama_asuransi=form.nama_asuransi.data.upper().strip(),
            no_polis=form.no_polis.data.upper().strip() if form.no_polis.data else None,
            no_polisi=form.no_polisi.data.upper().replace(" ", "") if form.no_polisi.data else None,
            merk=form.merk.data.upper().strip() if form.merk.data else None,
            kategori=form.kategori.data.upper() if form.kategori.data else None,
            eqp_model=form.eqp_model.data.upper().strip() if form.eqp_model.data else None,
            sn_equipment=form.sn_equipment.data,
            sn_engine=form.sn_engine.data,
            status_stnk=form.status_stnk.data,
            status_asuransi=form.status_asuransi.data,
            tanggal_berakhir_stnk=form.tanggal_berakhir_stnk.data if form.tanggal_berakhir_stnk.data else None,
            tanggal_berakhir_asuransi=form.tanggal_berakhir_asuransi.data if form.tanggal_berakhir_asuransi.data else None,
            year=form.year.data,
            biaya_perpanjang_stnk=biaya_perpanjang_stnk,
            biaya_administrasi_stnk=biaya_admin_stnk,
            biaya_perpanjang_asuransi=biaya_perpanjang_asuransi,
            biaya_administrasi_asuransi=biaya_admin_asuransi,
            pembulatan_stnk=pembulatan_otomatis_stnk,
            pembulatan_asuransi=pembulatan_otomatis_asuransi,
            total_stnk=total_terpembulat_stnk,
            harus_dibayar_stnk=total_terpembulat_stnk,
            total_asuransi=total_terpembulat_asuransi,
            harus_dibayar_asuransi=total_terpembulat_asuransi,
            notes=form.notes.data,
            tanggal_input=datetime.today().date(),
            diinput_oleh=session['logged_user']
        )

        uploaded_photos = request.files.getlist('unit_photos')

        if len(uploaded_photos) > 10:
            flash("⚠️ Gagal! Maksimal foto yang dapat diunggah adalah 10 foto per unit.", "danger")
            return render_template('form.html', form=form)

        print(form.errors)

        try:
            db.session.add(new_record)

            log_tambah = AuditLog(
                pkey=new_record.pkey,
                aksi="TAMBAH",
                kolom_diubah="Semua Kolom (Unit Baru)",
                nilai_lama="-",
                nilai_baru="Unit berhasil didaftarkan ke sistem",
                dilakukan_oleh=session['logged_user']
            )
            db.session.add(log_tambah)

            uploaded_files = request.files.getlist('unit_photos')
            for file in uploaded_files:
                if file and file.filename != '':
                    binary_data = file.read()
                    new_image = UnitImage(
                        pkey=new_record.pkey,
                        filename=file.filename,
                        file_data=binary_data
                    )
                    db.session.add(new_image)

            db.session.commit()
            return redirect(url_for('dashboard'))
        
        except IntegrityError as e:
            db.session.rollback()
            
            # Catch the duplicate key violation
            if isinstance(e.orig, UniqueViolation) or "duplicate key value" in str(e.orig):
                flash("This Unit is already in Database", "warning")
            else:
                flash(f"Database integrity error: {e.orig}", "danger")
                
        except Exception as e:
            db.session.rollback()
            flash(f"Unexpected database error: {e}", "danger")
        
    if form.errors:
        print("WTF Validasi Error detail:", form.errors)

    return render_template('form.html', form=form)

@app.route('/edit/<pkey>')
def edit(pkey):
    entry = db.session.execute(
        db.select(DataEntry).where(DataEntry.pkey == pkey)
    ).scalar_one_or_none()

    photo = db.session.execute(
        db.select(UnitImage).where(UnitImage.pkey == pkey)
    ).scalars().all()
    
    if not entry:
        flash("Data unit tidak ditemukan.", "danger")
        return redirect(url_for('details'))
        
    form = DataForm(obj=entry)
    form.kota.choices = get_kota_choices(entry.pulau)

    if entry.tanggal_berakhir_stnk:
        try:
            form.tanggal_berakhir_stnk.data = datetime.strptime(str(entry.tanggal_berakhir_stnk), '%Y-%m-%d').date()
        except ValueError:
            pass
    if entry.tanggal_berakhir_asuransi:
        try:
            form.tanggal_berakhir_asuransi.data = datetime.strptime(str(entry.tanggal_berakhir_asuransi), '%Y-%m-%d').date()
        except ValueError:
            pass

    form.biaya_perpanjang_stnk.data = f"{entry.biaya_perpanjang_stnk:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.').replace(chr(160), '').replace(' ', '')
    form.biaya_administrasi_stnk.data = f"{entry.biaya_administrasi_stnk:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    form.biaya_perpanjang_asuransi.data = f"{entry.biaya_perpanjang_asuransi:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    form.biaya_administrasi_asuransi.data = f"{entry.biaya_administrasi_asuransi:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    return render_template('edit.html', form=form, entry=entry, photo=photo)

@app.route('/delete/<pkey>', methods=['GET'])
def delete(pkey):
    entry = db.session.execute(
        db.select(DataEntry).where(DataEntry.pkey == pkey)
    ).scalar_one_or_none()
    
    if not entry:
        flash("Data unit dengan PKEY tersebut tidak ditemukan.", "danger")
        return redirect(url_for('details'))
    
    try:
        related_images = db.session.execute(
            db.select(UnitImage).where(UnitImage.pkey == pkey)
        ).scalars().all()
        
        for img in related_images:
            db.session.delete(img)

        log_hapus = AuditLog(
            pkey=pkey,
            aksi="HAPUS",
            kolom_diubah="Semua Data Unit",
            nilai_lama=f"PT: {entry.pt}, Plat: {entry.no_polisi}",
            nilai_baru="Data unit permanen dihapus dari sistem",
            dilakukan_oleh=session['logged_user']
        )
        db.session.add(log_hapus)

        db.session.delete(entry)
        db.session.commit()
                
    except Exception as e:
        db.session.rollback()
        flash(f"Gagal menghapus data unit dari database: {e}", "danger")
        
    return redirect(url_for('details'))

@app.route('/update_data/<pkey>', methods=['POST'])
def update_data(pkey):
    entry = db.session.execute(
        db.select(DataEntry).where(DataEntry.pkey == pkey)
    ).scalar_one_or_none()

    photo = db.session.execute(
        db.select(UnitImage).where(UnitImage.pkey == pkey)
    ).scalars().all()
    
    if not entry:
        return redirect(url_for('details'))
        
    form = DataForm()
    form.pulau.data = entry.pulau
    form.kota.choices = get_kota_choices(entry.pulau)
    form.kota.data = entry.kota
    form.pt.data = entry.pt
    form.unit.data = entry.unit
    form.pkey.data = pkey
    form.status_stnk.data=entry.status_stnk
    form.status_asuransi.data=entry.status_asuransi
    form.tanggal_berakhir_stnk.data=entry.tanggal_berakhir_stnk
    form.tanggal_berakhir_asuransi.data=entry.tanggal_berakhir_asuransi

    if form.validate_on_submit():
        def clean_numeric_input(val):
            if not val: return 0.0
            val_str = str(val).strip().replace('.', '').replace(',', '.')
            try: return round(float(val_str), 2)
            except ValueError: return 0.0

        # Kalkulasi hitung ulang biaya baru
        biaya_perpanjang_stnk = clean_numeric_input(form.biaya_perpanjang_stnk.data)
        biaya_admin_stnk = clean_numeric_input(form.biaya_administrasi_stnk.data)
        total_stnk = biaya_perpanjang_stnk + biaya_admin_stnk
        total_terpembulat_stnk = float(round(total_stnk, 0))
        pembulatan_otomatis_stnk = round(total_terpembulat_stnk - total_stnk, 2)

        biaya_perpanjang_asuransi = clean_numeric_input(form.biaya_perpanjang_asuransi.data)
        biaya_admin_asuransi = clean_numeric_input(form.biaya_administrasi_asuransi.data)
        total_asuransi = biaya_perpanjang_asuransi + biaya_admin_asuransi
        total_terpembulat_asuransi = float(round(total_asuransi, 0))
        pembulatan_otomatis_asuransi = round(total_terpembulat_asuransi - total_asuransi, 2)

        if (biaya_perpanjang_stnk <= 0 or biaya_admin_stnk <= 0 or 
            biaya_perpanjang_asuransi <= 0 or biaya_admin_asuransi <= 0):
            flash("⚠️ Semua rincian biaya (STNK & Asuransi) wajib diisi dan tidak boleh bernilai 0!", "danger")
               
            return render_template('edit.html', form=form, entry=entry, photo=photo)

        fields_to_check = [
            ('pt', 'Nama PT', form.pt.data.upper().strip() if form.pt.data else None),
            ('nama_asuransi', 'Nama Asuransi', form.nama_asuransi.data.upper().strip() if form.nama_asuransi.data else None),
            ('pulau', 'Pulau', form.pulau.data.upper().strip() if form.pulau.data else None),
            ('kota', 'Site (Kota)', form.kota.data.upper().strip() if form.kota.data else None),
            ('no_polis', 'No. Polis', form.no_polis.data.upper().strip() if form.no_polis.data else None),
            ('no_polisi', 'No. Polisi', form.no_polisi.data.upper().strip() if form.no_polisi.data else None),
            ('merk', 'Merk', form.merk.data.upper().strip() if form.merk.data else None),
            ('kategori', 'Kategori', form.kategori.data.upper().strip() if form.kategori.data else None),
            ('eqp_model', 'Equipment Model', form.eqp_model.data.upper().strip() if form.eqp_model.data else None),
            ('sn_equipment', 'SN Equipment', form.sn_equipment.data if form.sn_equipment.data else None),
            ('sn_engine', 'SN Engine', form.sn_engine.data if form.sn_engine.data else None),
            ('year', 'Year', form.year.data if form.year.data else None),
            ('status_stnk', 'Status STNK', form.status_stnk.data),
            ('status_asuransi', 'Status Asuransi', form.status_asuransi.data),
            ('tanggal_berakhir_stnk', 'Masa Berlaku STNK', form.tanggal_berakhir_stnk.data),
            ('tanggal_berakhir_asuransi', 'Masa Berlaku Asuransi', form.tanggal_berakhir_asuransi.data),
            ('biaya_perpanjang_stnk', 'Biaya STNK', biaya_perpanjang_stnk),
            ('biaya_administrasi_stnk', 'Biaya Admin STNK', biaya_admin_stnk),
            ('biaya_perpanjang_asuransi', 'Biaya Asuransi', biaya_perpanjang_asuransi),
            ('biaya_administrasi_asuransi', 'Biaya Admin Asuransi', biaya_admin_asuransi),
            ('notes', 'Notes', form.notes.data)
        ]

        for attr, label, new_val in fields_to_check:
            old_val = getattr(entry, attr)
            # Normalisasi jika tipe data tanggal atau objek kosong
            if str(old_val) != str(new_val):
                log_edit = AuditLog(
                    pkey=pkey,
                    aksi="EDIT",
                    kolom_diubah=label,
                    nilai_lama=str(old_val) if old_val is not None else "Kosong",
                    nilai_baru=str(new_val) if new_val is not None else "Kosong",
                    dilakukan_oleh=session['logged_user']
                )
                db.session.add(log_edit)

        # Update properti objek database lama dengan data kiriman dari form edit
        entry.pt = form.pt.data.upper().strip()
        entry.nama_asuransi = form.nama_asuransi.data.upper().strip()
        entry.pulau = form.pulau.data.upper().strip()
        entry.kota = form.kota.data.upper().strip()
        entry.no_polis = form.no_polis.data.upper().strip() if form.no_polis.data else None
        entry.no_polisi = form.no_polisi.data.upper().replace(" ", "") if form.no_polisi.data else None
        entry.merk = form.merk.data.upper().strip() if form.merk.data else None
        entry.kategori = form.kategori.data.upper().strip() if form.kategori.data else None
        entry.eqp_model = form.eqp_model.data.upper().strip() if form.eqp_model.data else None
        entry.sn_equipment = form.sn_equipment.data
        entry.sn_engine = form.sn_engine.data
        entry.year = form.year.data
        
        entry.biaya_perpanjang_stnk = biaya_perpanjang_stnk
        entry.biaya_administrasi_stnk = biaya_admin_stnk
        entry.pembulatan_stnk = pembulatan_otomatis_stnk
        entry.total_stnk = total_terpembulat_stnk
        entry.harus_dibayar_stnk = total_terpembulat_stnk
        
        entry.biaya_perpanjang_asuransi = biaya_perpanjang_asuransi
        entry.biaya_administrasi_asuransi = biaya_admin_asuransi
        entry.pembulatan_asuransi = pembulatan_otomatis_asuransi
        entry.total_asuransi = total_terpembulat_asuransi
        entry.harus_dibayar_asuransi = total_terpembulat_asuransi
        
        entry.diinput_oleh = session.get('logged_user', 'System')

        # Validasi di fungsi update_data
        uploaded_photos = request.files.getlist('unit_photos')
        existing_photos_count = db.session.execute(
            db.select(db.func.count(UnitImage.id)).where(UnitImage.pkey == pkey)
        ).scalar()

        # Memastikan file yang diunggah benar-benar ada/tidak kosong
        valid_uploaded_count = sum(1 for photo in uploaded_photos if photo.filename != '')

        if (existing_photos_count + valid_uploaded_count) > 10:
            flash(f"⚠️ Gagal! Jumlah total foto melebihi batas. Saat ini sudah ada {existing_photos_count} foto, Anda hanya bisa menambah maksimal {10 - existing_photos_count} foto lagi.", "danger")
            return render_template('edit.html', form=form, entry=entry, photo=photo)

        try:
            uploaded_files = request.files.getlist('unit_photos')
            for file in uploaded_files:
                if file and file.filename != '':
                    binary_data = file.read()
                    new_image = UnitImage(
                        pkey=pkey, # Tetap arahkan ke parameter PKEY unit ini
                        filename=file.filename,
                        file_data=binary_data
                    )
                    db.session.add(new_image)

                    log_upload = AuditLog(
                        pkey=pkey,
                        aksi="EDIT",
                        kolom_diubah="Foto Unit",
                        nilai_lama="-",
                        nilai_baru=f"Menambahkan foto: {file.filename}",
                        dilakukan_oleh=session.get('logged_user', 'System')
                    )
                    db.session.add(log_upload)

            db.session.commit()
            return redirect(url_for('details'))
        except Exception as e:
            db.session.rollback()
            flash(f"Gagal memperbarui database: {e}", "danger")
            
    return render_template('edit.html', form=form, entry=entry, photo=photo)

@app.route('/api/get-tagihan/<jenis>/<pkey>')
def get_tagihan(jenis, pkey):
    pulau = request.args.get('pulau', '').strip()
    kota = request.args.get('kota', '').strip()
    pt = request.args.get('pt', '').strip()
    unit = request.args.get('unit', '').strip()

    stmt = db.select(DataEntry).where(db.func.upper(DataEntry.kode_unit) == pkey.upper())
    if pulau:
        stmt = stmt.where(db.func.upper(DataEntry.pulau) == pulau.upper())
    if kota:
        stmt = stmt.where(db.func.upper(DataEntry.kota) == kota.upper())
    if pt:
        stmt = stmt.where(db.func.upper(DataEntry.pt) == pt.upper())
    if unit:
        stmt = stmt.where(db.func.upper(DataEntry.unit) == unit.upper())

    entry = db.session.execute(stmt).scalar_one_or_none()
    
    if entry:
        # Tentukan kolom mana yang diambil berdasarkan input 'Jenis'
        if jenis.upper() == "STNK":
            nilai_tagihan = float(entry.harus_dibayar_stnk) if entry.harus_dibayar_stnk else 0.0
        elif jenis.upper() == "ASURANSI":
            nilai_tagihan = float(entry.harus_dibayar_asuransi) if entry.harus_dibayar_asuransi else 0.0
        else:
            nilai_tagihan = 0.0
            
        return jsonify({
            'success': True,
            'total_tagihan': nilai_tagihan
        })
    
    return jsonify({'success': False, 'message': 'PKEY tidak ditemukan'}), 404

@app.route('/api/get-kota/<pulau>')
def get_kota_api(pulau):
    choices = get_kota_choices(pulau)
    return jsonify([{'value': val, 'label': label} for val, label in choices])

@app.route('/api/get-pt/<kota>')
def get_pt_api(kota):
    choices = get_pt_choices(kota)
    return jsonify([{'value': val, 'label': label} for val, label in choices])

@app.route('/api/get-unit/<pt>')
def get_unit_api(pt):
    choices = get_unit_choices(pt)
    return jsonify([{'value': val, 'label': label} for val, label in choices])

@app.route('/api/get-cn/<unit>')
def get_cn_api(unit):
    choices = get_cn_choices(unit)
    return jsonify([{'value': val, 'label': label} for val, label in choices])

@app.route('/get_image/<int:image_id>')
def get_image(image_id):
    img_record = db.session.execute(
        db.select(UnitImage).where(UnitImage.id == image_id)
    ).scalar_one_or_none()
    
    if img_record:
        ext = img_record.filename.split('.')[-1].lower()
        mimetype = f'image/{ext}' if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'image/jpeg'
        
        return Response(img_record.file_data, mimetype=mimetype)
        
    return "Gambar tidak ditemukan", 404

@app.route('/delete_image/<int:image_id>', methods=['POST'])
def delete_image(image_id):
    img_record = db.session.execute(
        db.select(UnitImage).where(UnitImage.id == image_id)
    ).scalar_one_or_none()
    
    if img_record:
        pkey = img_record.pkey
        filename = img_record.filename
        try:
            log_delete = AuditLog(
                pkey=pkey,
                aksi="EDIT",
                kolom_diubah="Foto Unit",
                nilai_lama=f"Menghapus foto: {filename}",
                nilai_baru="Foto dihapus",
                dilakukan_oleh=session.get('logged_user', 'System')
            )
            db.session.add(log_delete)
            db.session.delete(img_record)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500
            
    return jsonify({'success': False, 'message': 'Gambar tidak ditemukan'}), 404

@app.route('/export/excel')
def export_excel():
    try:
        # 1. Ambil semua data dari database
        all_entries = db.session.execute(
            db.select(DataEntry).order_by(DataEntry.id)
        ).scalars().all()
        
        # 2. Inisialisasi Workbook openpyxl
        wb = Workbook()
        ws = wb.active
        ws.title = "Master Database"
        
        # Otomatis aktifkan grid lines agar tabel terlihat rapi
        ws.views.sheetView[0].showGridLines = True
        
        # 3. Definisi Judul Kolom (Headers)
        headers = [
            'No', 'Nama PT', 'Nama Asuransi', 'Pulau', 'Site (Provinsi)', 'CN Unit', 
            'No. Polis', 'No. Polisi', 'Merk', 'Kategori', 'Equipment Model', 
            'SN Equipment', 'SN Engine', 'Status STNK', 'Masa Berlaku STNK', 
            'Status Asuransi', 'Masa Berlaku Asuransi', 'Year', 'Remarks', 
            'Biaya STNK', 'Admin STNK', 'Pembulatan STNK', 'Total STNK',
            'Biaya Asuransi', 'Admin Asuransi', 'Pembulatan Asuransi', 'Total Asuransi',
            'Diinput Oleh', 'Tanggal Input'
        ]
        ws.append(headers)
        
        header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style='thin', color='CCCCCC'),
            right=Side(style='thin', color='CCCCCC'),
            top=Side(style='thin', color='CCCCCC'),
            bottom=Side(style='thin', color='CCCCCC')
        )
        
        # Terapkan style ke baris header (Baris 1)
        ws.row_dimensions[1].height = 28
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        # 5. Iterasi dan Masukkan Data dari Database
        for idx, entry in enumerate(all_entries, start=1):
            row_data = [
                idx, entry.pt, entry.nama_asuransi, entry.pulau, entry.provinsi, entry.pkey,
                entry.no_polis, entry.no_polisi, entry.merk, entry.kategori, entry.eqp_model,
                entry.sn_equipment, entry.sn_engine, entry.status_stnk, 
                entry.tanggal_berakhir_stnk.strftime('%Y-%m-%d') if entry.tanggal_berakhir_stnk else '-',
                entry.status_asuransi,
                entry.tanggal_berakhir_asuransi.strftime('%Y-%m-%d') if entry.tanggal_berakhir_asuransi else '-',
                entry.year,
                entry.biaya_perpanjang_stnk, entry.biaya_administrasi_stnk, entry.pembulatan_stnk, entry.total_stnk,
                entry.biaya_perpanjang_asuransi, entry.biaya_administrasi_asuransi, entry.pembulatan_asuransi, entry.total_asuransi,
                entry.diinput_oleh, entry.tanggal_input.strftime('%Y-%m-%d %H:%M') if entry.tanggal_input else '-'
            ]
            ws.append(row_data)
            
            # Format Angka Keuangan & Border untuk Baris Data yang Baru Ditambahkan
            current_row = ws.max_row
            ws.row_dimensions[current_row].height = 20
            
            # Indeks kolom keuangan (kolom T sampai AA di Excel, berbasis 1-index berarti kolom 20-27)
            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=current_row, column=col_num)
                cell.border = thin_border
                cell.font = Font(name="Arial", size=10)
                
                # Sisi perataan data
                if col_num in [1, 14, 15, 16, 17, 18]: # No, Status, Tanggal, Tahun
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif 20 <= col_num <= 27: # Biaya & Total
                    cell.number_format = '"Rp "#,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        # 6. Otomatis Menyesuaikan Lebar Kolom Berdasarkan Karakter Terpanjang
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        # 7. Kirim file ke browser sebagai file download langsung
        out_buffer = io.BytesIO()
        wb.save(out_buffer)
        out_buffer.seek(0)
        
        filename = f"Database_Master_Export_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return Response(
            out_buffer.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        return f"Terjadi kesalahan saat mengekspor ke Excel: {str(e)}", 500

@app.route('/export/report/excel')
def export_report_excel():
    if 'logged_user' not in session:
        return redirect(url_for('login'))
        
    group_by = request.args.get('groupby', 'ALL')
    
    try:
        all_entries = db.session.execute(
            db.select(DataEntry).order_by(DataEntry.id)
        ).scalars().all()
        
        grouped_data = defaultdict(list)
        if group_by == 'pt':
            for entry in all_entries: grouped_data[entry.pt or "Tanpa PT"].append(entry)
        elif group_by == 'nama_asuransi':
            for entry in all_entries: grouped_data[entry.nama_asuransi or "Tanpa Asuransi"].append(entry)
        elif group_by == 'pulau':
            for entry in all_entries: grouped_data[entry.pulau or "Tanpa Pulau"].append(entry)
        elif group_by == 'kota':
            for entry in all_entries: grouped_data[entry.kota or "Tanpa Site"].append(entry)
        else:
            grouped_data['Semua Data'] = all_entries
   
        wb = Workbook()
        default_sheet = wb.active
        wb.remove(default_sheet)
        
        header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid") # Navy gelap
        group_title_font = Font(name="Arial", size=14, bold=True, color="1F4E78")
        thin_border = Border(
            left=Side(style='thin', color='CCCCCC'), right=Side(style='thin', color='CCCCCC'),
            top=Side(style='thin', color='CCCCCC'), bottom=Side(style='thin', color='CCCCCC')
        )

        headers = [
            'No', 'CN Unit', 'Nama PT', 'Nama Asuransi', 'Pulau', 'Site (Kota)', 
            'No. Polisi', 'Status STNK', 'Masa Berlaku STNK', 'Status Asuransi', 
            'Masa Berlaku Asuransi', 'Total STNK', 'Total Asuransi', 'Diinput Oleh'
        ]

        for group_name, entries in grouped_data.items():
            clean_sheet_title = str(group_name).replace('/', '-').replace('\\', '-')[0:30]
            ws = wb.create_sheet(title=clean_sheet_title)
            ws.views.sheetView[0].showGridLines = True
            
            ws.append([f"LAPORAN DATA BERDASARKAN: {str(group_name).upper()}"])
            ws.cell(row=1, column=1).font = group_title_font
            ws.row_dimensions[1].height = 25
            ws.append([]) # Baris kosong pembatas
            
            ws.append(headers)
            header_row = 3
            ws.row_dimensions[header_row].height = 26
            for cell in ws[header_row]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = thin_border
            
            for idx, entry in enumerate(entries, start=1):
                row_values = [
                    idx, entry.pkey, entry.pt, entry.nama_asuransi, entry.pulau, entry.kota,
                    entry.no_polisi, entry.status_stnk,
                    entry.tanggal_berakhir_stnk.strftime('%Y-%m-%d') if entry.tanggal_berakhir_stnk else '-',
                    entry.status_asuransi,
                    entry.tanggal_berakhir_asuransi.strftime('%Y-%m-%d') if entry.tanggal_berakhir_asuransi else '-',
                    entry.total_stnk, entry.total_asuransi, entry.diinput_oleh
                ]
                ws.append(row_values)
                
                current_row = ws.max_row
                ws.row_dimensions[current_row].height = 20
                
                for col_num in range(1, len(headers) + 1):
                    cell = ws.cell(row=current_row, column=col_num)
                    cell.border = thin_border
                    cell.font = Font(name="Arial", size=10)
                    
                    if col_num in [1, 2, 8, 9, 10, 11]: 
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    elif col_num in [12, 13]: 
                        cell.number_format = '"Rp "#,##0.00'
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center")
            
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(max_len + 3, 11)
                
        out_buffer = io.BytesIO()
        wb.save(out_buffer)
        out_buffer.seek(0)
        
        filename = f"Laporan_Terkelompok_{group_by}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return Response(
            out_buffer.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        return f"Gagal mengekspor laporan: {str(e)}", 500

def check_and_update_expired_units():
    hari_ini_str = datetime.today().date().strftime('%Y-%m-%d')
    
    all_entries = db.session.execute(db.select(DataEntry)).scalars().all()
    
    updated = False
    for entry in all_entries:
        # Check STNK status
        if entry.tanggal_berakhir_stnk:
            if entry.tanggal_berakhir_stnk > hari_ini_str:
                if entry.status_stnk != 'ON':
                    entry.status_stnk = 'ON'
                    updated = True
            else:
                if entry.status_stnk != 'OFF':
                    entry.status_stnk = 'OFF'
                    updated = True
        else:
            if entry.status_stnk != 'OFF':
                entry.status_stnk = 'OFF'
                updated = True
                
        # Check Asuransi status
        if entry.tanggal_berakhir_asuransi:
            if entry.tanggal_berakhir_asuransi > hari_ini_str:
                if entry.status_asuransi != 'ON':
                    entry.status_asuransi = 'ON'
                    updated = True
            else:
                if entry.status_asuransi != 'OFF':
                    entry.status_asuransi = 'OFF'
                    updated = True
        else:
            if entry.status_asuransi != 'OFF':
                entry.status_asuransi = 'OFF'
                updated = True
                
    if updated:
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)