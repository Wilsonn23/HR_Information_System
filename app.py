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
from wtforms import StringField, EmailField, SubmitField, FloatField, SelectField, DateField
from wtforms.validators import DataRequired, Optional, NumberRange, Email, Length
from datetime import datetime, timedelta
from collections import defaultdict
from werkzeug.security import check_password_hash, generate_password_hash

import csv
import io
import os
import urllib
import click

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'StringAcakYangSangatPanjangDanRahasia')

app.config['SESSION_COOKIE_HTTPONLY'] = True

app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

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

@app.cli.command("create-user")
@click.argument("username")
@click.argument("password")
@click.argument("role")
def create_user(username, password, role):
    """Menambahkan user baru secara aman via terminal."""
    # Enkripsi password mentah menjadi hash aman
    hashed_password = generate_password_hash(password)
    
    try:
        query = text("INSERT INTO users (username, password_hash, role) VALUES (:username, :password, :role)")
        db.session.execute(query, {"username": username.strip(), "password": hashed_password, "role":role})
        db.session.commit()
        click.echo(f"Sukses: User '{username}' berhasil dibuat!")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Gagal: {e}")

@app.before_request
def batasi_akses_global():
    halaman_bebas = ['login', 'static']
    
    if 'logged_in' not in session and request.endpoint not in halaman_bebas:
        if request.endpoint:
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

class DataEntry(db.Model):
    __tablename__ = "data_entries"
    
    id: Mapped[int] = mapped_column(Integer, Sequence("id"), unique=True, nullable=False)
    pt: Mapped[str] = mapped_column(nullable=False)
    nama_asuransi: Mapped[str] = mapped_column(nullable=False)
    pulau: Mapped[str] = mapped_column(nullable=False)
    provinsi: Mapped[str] = mapped_column(nullable=False)
    cn: Mapped[str] = mapped_column(primary_key=True, nullable=False)
    no_polis: Mapped[str] = mapped_column(nullable=False)
    no_polisi: Mapped[str] = mapped_column(nullable=True)
    varian: Mapped[str] = mapped_column(nullable=False)
    kategori: Mapped[str] = mapped_column(nullable=False)
    eqp_model: Mapped[str] = mapped_column(nullable=False)
    sn_equipment: Mapped[str] = mapped_column(nullable=False)
    sn_engine: Mapped[str] = mapped_column(nullable=False)
    status_stnk: Mapped[str] = mapped_column(nullable=False)
    status_asuransi: Mapped[str] = mapped_column(nullable=False)
    tanggal_berakhir_stnk: Mapped[str] = mapped_column(nullable=True)
    tanggal_berakhir_asuransi: Mapped[str] = mapped_column(nullable=True)
    year: Mapped[int] = mapped_column(nullable=False)
    remaks: Mapped[str] = mapped_column(nullable=True)
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
    tanggal_input: Mapped[str] = mapped_column(nullable=True)
    diinput_oleh: Mapped[str] = mapped_column(nullable=True)

class ReportEntry(db.Model):
    __tablename__ = "report_entries"

    jenis: Mapped[str] = mapped_column(nullable=False)
    id: Mapped[int] = mapped_column(Integer, Sequence("id"), unique=True, primary_key=True, nullable=False)
    cn: Mapped[str] = mapped_column(nullable=False)
    status_pembayaran: Mapped[str] = mapped_column(nullable=True)
    tanggal_berakhir_baru: Mapped[str] = mapped_column(nullable=True)
    jumlah_dibayar:Mapped[float] = mapped_column(nullable=False) 
    sisa_tagihan:Mapped[float] = mapped_column(nullable=False)
    tanggal_bayar: Mapped[str] = mapped_column(nullable=False)
    tanggal_input: Mapped[str] = mapped_column(nullable=False)
    diinput_oleh: Mapped[str] = mapped_column(nullable=False)

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(message="Username tidak boleh kosong.")])
    password = StringField('Password', validators=[DataRequired(message="Password tidak boleh kosong.")])

class DataForm(FlaskForm):
    pt = StringField('Nama PT', validators=[
        DataRequired(message="Nama PT tidak boleh kosong."), 
        Length(min=1, max=100, message="Nama PT harus antara 1 dan 100 karakter.")
    ])
    nama_asuransi = StringField('Nama Asuransi', validators=[
        DataRequired(message="Nama Asuransi tidak boleh kosong."), 
        Length(min=1, max=100, message="Nama Asuransi harus antara 1 dan 100 karakter.")
    ])
    pulau = StringField('Pulau', validators=[
        DataRequired(message="Pulau tidak boleh kosong."), 
        Length(min=1, max=100, message="Pulau harus antara 1 dan 100 karakter.")
    ])
    provinsi = StringField('Province', validators=[
        DataRequired(message="Site (Provinsi) tidak boleh kosong."), 
        Length(min=1, max=100, message="Site (Provinsi) harus antara 1 dan 100 karakter.")
    ])
    cn = StringField('CN', validators=[
        DataRequired(message="CN tidak boleh kosong."), 
        Length(min=1, max=100, message="CN harus antara 1 dan 100 karakter.")
    ])
    no_polis = StringField('No. Polis', validators=[
        DataRequired(message="No. Polis tidak boleh kosong."), 
        Length(min=1, max=100, message="No. Polis harus antara 1 dan 100 karakter.")
    ])
    no_polisi = StringField('No. Polisi', validators=[
        DataRequired(message="No. Polisi tidak boleh kosong."), 
        Length(min=1, max=100, message="No. Polisi harus antara 1 dan 100 karakter.")
    ])
    varian = StringField('Varian', validators=[
        DataRequired(message="Varian Asuransi tidak boleh kosong."), 
        Length(min=1, max=100, message="Varian Asuransi harus antara 1 dan 100 karakter.")
    ])
    kategori = StringField('Kategori', validators=[
        DataRequired(message="Kategori tidak boleh kosong."), 
        Length(min=1, max=100, message="Kategori harus antara 1 dan 100 karakter.")
    ])
    eqp_model = StringField('Equipment Model', validators=[
        DataRequired(message="Equipment Model tidak boleh kosong."), 
        Length(min=1, max=100, message="Equipment Model harus antara 1 dan 100 karakter.")
    ])   
    sn_equipment = StringField('SN Equipment', validators=[
        DataRequired(message="SN Equipment tidak boleh kosong."), 
        Length(min=1, max=100, message="SN Equipment harus antara 1 dan 100 karakter.")
    ])
    sn_engine = StringField('SN Engine', validators=[
        DataRequired(message="SN Engine tidak boleh kosong."), 
        Length(min=1, max=100, message="SN Engine harus antara 1 dan 100 karakter.")
    ])
    status_stnk = SelectField(
        'Status STNK', 
        choices=[('OFF', 'OFF'), ('ON', 'ON')]
    )
    status_asuransi = SelectField(
        'Status STNK', 
        choices=[('OFF', 'OFF'), ('ON', 'ON')]
    )
    tanggal_berakhir_stnk = DateField('Tanggal Berakhir STNK', format='%Y-%m-%d', validators=[Optional()])
    tanggal_berakhir_asuransi = DateField('Tanggal Berakhir Asuransi', format='%Y-%m-%d', validators=[Optional()])

    current_year = datetime.now().year
    
    year_choices = [(str(y), str(y)) for y in range(current_year, 1999, -1)]
    
    year_choices.insert(0, ('', 'Select'))

    year = SelectField('Year', choices=year_choices, default='Select', coerce=str)
    
    remaks = StringField('Remaks', validators=[Optional()])

    biaya_perpanjang_stnk = StringField('Biaya Perpanjang STNK', validators=[
        DataRequired(message="Biaya Perpanjang tidak boleh kosong."), 
    ])
    biaya_administrasi_stnk = StringField('Biaya Administrasi STNK', validators=[
        DataRequired(message="Biaya Administrasi tidak boleh kosong."), 
    ])
    biaya_perpanjang_asuransi = StringField('Biaya Perpanjang Asuransi', validators=[
        DataRequired(message="Biaya Perpanjang tidak boleh kosong."), 
    ])
    biaya_administrasi_asuransi = StringField('Biaya Administrasi Asuransi', validators=[
        DataRequired(message="Biaya Administrasi tidak boleh kosong."), 
    ])

class ExtendForm(FlaskForm):
    jenis = SelectField(
        'Jenis', 
        choices=[('STNK', 'STNK'), ('Asuransi', 'Asuransi')]
    )
    cn = StringField('CN', validators=[
        DataRequired(message="CN tidak boleh kosong."), 
        Length(min=1, max=100, message="CN harus antara 1 dan 100 karakter.")
    ])
    tanggal_berakhir_baru = DateField('Tanggal Berakhir', format='%Y-%m-%d', validators=[Optional()])
    jumlah_dibayar = StringField('Biaya Administrasi', validators=[
        DataRequired(message="Jumlah dibayar tidak boleh kosong."), 
    ])
    tanggal_bayar = DateField('Tanggal Berakhir', format='%Y-%m-%d', validators=[DataRequired(message="Tanggal tidak boleh kosong.")])

    
# ===============================================================================================================
# ROUTING
# ===============================================================================================================

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        
        query = text("SELECT id, username, password_hash, role FROM users WHERE username = :username")
        user = db.session.execute(query, {"username": username}).fetchone()
        
        # Verifikasi keberadaan user dan kecocokan hash password-nya
        if user and check_password_hash(user.password_hash, password):
            # Regenerasi session ID baru untuk mencegah Session Fixation Attack
            session.clear()
            
            # Set cookie session aman
            session['user_id'] = user.id
            session['logged_user'] = user.username
            session['role'] = user.role
            
            return redirect(url_for('dashboard'))
        else:
            flash("Username atau Password salah!", "danger")
            
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    session.clear()
    flash("Anda telah berhasil logout.", "success")
    return redirect(url_for('login'))

@app.route('/master', methods=['GET'])
def master():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(DataEntry)
    ).scalars().all()
    return render_template('master.html', entries=all_entries)

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    query = text("SELECT COUNT(*) FROM data_entries")
    total_peralatan=db.session.execute(query).scalar()

    today = datetime.now().date()
    
    query = text("SELECT COUNT(*) FROM data_entries WHERE :today <= tanggal_berakhir_stnk::date")
    jumlah_stnk_aktif=db.session.execute(query, {"today": today}).scalar()

    query = text("SELECT COUNT(*) FROM data_entries WHERE :today <= tanggal_berakhir_asuransi::date")
    jumlah_asuransi_aktif=db.session.execute(query, {"today": today}).scalar()

    hari_ini = datetime.now().date().strftime('%Y-%m-%d')
    satu_bulan_lagi = (datetime.now().date() + timedelta(days=30)).strftime('%Y-%m-%d')
    tiga_bulan_lagi = (datetime.now().date() + timedelta(days=90)).strftime('%Y-%m-%d')

    stnk_expired = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk < hari_ini).all()
    stnk_notice = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk >= satu_bulan_lagi, DataEntry.tanggal_berakhir_stnk <= tiga_bulan_lagi).all()
    stnk_warning = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk >= hari_ini, DataEntry.tanggal_berakhir_stnk <= satu_bulan_lagi).all()
    stnk_none = DataEntry.query.filter((DataEntry.tanggal_berakhir_stnk == None)).all()
    
    asuransi_expired = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi < hari_ini).all()
    asuransi_notice = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi >= satu_bulan_lagi, DataEntry.tanggal_berakhir_asuransi <= satu_bulan_lagi).all()
    asuransi_warning = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi >= hari_ini, DataEntry.tanggal_berakhir_asuransi <= tiga_bulan_lagi).all()
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

@app.route('/perpanjang')
def perpanjang():
    form = ExtendForm()
    return render_template('perpanjang.html', form=form, active_page='perpanjang')

@app.route('/report')
def report():
    group_by = request.args.get('groupby', 'ALL')
    
    query = (
        db.select(DataEntry, ReportEntry)
        .join(ReportEntry, DataEntry.cn == ReportEntry.cn)
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
        active_filter=group_by
    )

@app.route('/entry')
def database():
    form = DataForm()
    return render_template('form.html', form=form, active_page='entry')

@app.route('/submit_extend', methods=['POST'])
def submit_extend():
    form = ExtendForm()
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
        if(jenis=="STNK"):
            query = text("SELECT harus_dibayar_stnk FROM data_entries WHERE cn = :cn")
        elif(jenis=="Asuransi"):
            query = text("SELECT harus_dibayar_asuransi FROM data_entries WHERE cn = :cn")

        sisa = db.session.execute(query, {"cn": cn}).scalar()
        sisa = float(sisa)
        sisa -= jumlah_dibayar
        
        if(sisa <= 0):
            sisa = 0.0 
            status_pembayaran = "Lunas"
        else:
            status_pembayaran = "Belum Lunas"

        new_record = ReportEntry(
            jenis=jenis,
            cn=form.cn.data,
            status_pembayaran=status_pembayaran,
            tanggal_berakhir_baru=form.tanggal_berakhir_baru.data if form.tanggal_berakhir_baru.data else None,
            jumlah_dibayar=jumlah_dibayar,
            sisa_tagihan=sisa,
            tanggal_bayar=form.tanggal_bayar.data,
            tanggal_input=datetime.today().date(),
            diinput_oleh=session['logged_user']
        )

        try:
            if(jenis=="STNK"):
                query = text("UPDATE data_entries SET harus_dibayar_stnk = :sisa WHERE cn = :cn")
            elif(jenis=="Asuransi"):
                query = text("UPDATE data_entries SET harus_dibayar_asuransi = :sisa WHERE cn = :cn")
            db.session.execute(query, {"sisa":sisa, "cn":cn})
            if(status_pembayaran=="Lunas"):
                if(form.jenis.data=="STNK"):
                    query = text("UPDATE data_entries SET status_stnk = 'ON', tanggal_berakhir_stnk = :stnk WHERE cn = :cn")
                    db.session.execute(query, {"stnk": form.tanggal_berakhir_baru.data, "cn":cn})
                    query = text("UPDATE report_entries SET status_pembayaran = :status_pembayaran WHERE cn = :cn and jenis = :jenis")
                    db.session.execute(query, {"status_pembayaran": status_pembayaran, "cn":cn, "jenis":jenis})
                elif(form.jenis.data=="Asuransi"):
                    query = text("UPDATE data_entries SET status_asuransi = 'ON', tanggal_berakhir_asuransi = :asuransi WHERE cn = :cn")
                    db.session.execute(query, {"asuransi": form.tanggal_berakhir_baru.data, "cn":cn})
                    query = text("UPDATE report_entries SET status_pembayaran = :status_pembayaran WHERE cn = :cn and jenis = :jenis")
                    db.session.execute(query, {"status_pembayaran": status_pembayaran, "cn":cn, "jenis":jenis})
            db.session.add(new_record)
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

        new_record = DataEntry(
            pt=form.pt.data,
            nama_asuransi=form.nama_asuransi.data,
            pulau=form.pulau.data,
            provinsi=form.provinsi.data,
            cn=form.cn.data,
            no_polis=form.no_polis.data,
            no_polisi=form.no_polisi.data,
            varian=form.varian.data,
            kategori=form.kategori.data,
            eqp_model=form.eqp_model.data,
            sn_equipment=form.sn_equipment.data,
            sn_engine=form.sn_engine.data,
            status_stnk=form.status_stnk.data,
            status_asuransi=form.status_asuransi.data,
            tanggal_berakhir_stnk=form.tanggal_berakhir_stnk.data if form.tanggal_berakhir_stnk.data else None,
            tanggal_berakhir_asuransi=form.tanggal_berakhir_asuransi.data if form.tanggal_berakhir_asuransi.data else None,
            year=form.year.data,
            remaks=form.remaks.data if form.remaks.data else None,
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
            tanggal_input=datetime.today().date(),
            diinput_oleh=session['logged_user']
        )

        print(form.errors)

        try:
            db.session.add(new_record)
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
        
    return render_template('form.html', form=form)

@app.route('/api/get-tagihan/<jenis>/<cn>')
def get_tagihan(jenis, cn):
    entry = db.session.execute(
        db.select(DataEntry).where(DataEntry.cn == cn)
    ).scalar_one_or_none()
    
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
    
    return jsonify({'success': False, 'message': 'CN tidak ditemukan'}), 404

@app.route('/export/csv')
def export_csv():
    # """Queries all data from Postgres and streams it as a downloadable CSV file."""
    # try:
    #     # 1. Fetch all records sorted by ID
    #     all_entries = db.session.execute(
    #         db.select(DataEntry).order_by(DataEntry.id)
    #     ).scalars().all()
        
    #     # 2. Create an in-memory string buffer to write CSV data into
    #     output = io.StringIO()
    #     writer = csv.writer(output)
        
    #     # 3. Write the Header Row
    #     writer.writerow(['ID', 'Nama PT', 'Nama Asuransi', 'No Polisi', 'Objek Asuransi', 'No Polis', 'Net Premium', 'Biaya Admin', 'Pembulatan', 'Total'])
        
    #     # 4. Write the Data Rows
    #     for entry in all_entries:
    #         writer.writerow([entry.id, entry.pt, entry.nama_asuransi, entry.no_polisi, entry.objek_asuransi, entry.no_polis, entry.net_premium, entry.biaya_administrasi, entry.pembulatan, entry.total])
            
    #     # 5. Reset buffer pointer to the beginning
    #     output.seek(0)
        
    #     # 6. Return the data as a downloadable file response
    #     return Response(
    #         output.getvalue(),
    #         mimetype="text/csv",
    #         headers={"Content-Disposition": "attachment; filename=database_export.csv"}
    #     )
        
    # except Exception as e:
    #     return f"Could not export data: {e}", 500
    pass

if __name__ == '__main__':
    app.run(debug=True)