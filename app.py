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

class Pulau(db.Model):
    __tablename__ = 'pulau'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class Kota(db.Model):
    __tablename__ = 'kota'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    reference: Mapped[int] = mapped_column(db.ForeignKey('pulau.id'), nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

    @property
    def parent_nama(self):
        p = db.session.get(Pulau, self.reference)
        return p.nama if p else ""

class PT(db.Model):
    __tablename__ = 'pt'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=False, nullable=False)
    reference: Mapped[int] = mapped_column(db.ForeignKey('kota.id'), nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

    @property
    def parent_nama(self):
        k = db.session.get(Kota, self.reference)
        return k.nama if k else ""

class Unit(db.Model):
    __tablename__ = 'unit'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=False, nullable=False)
    reference: Mapped[int] = mapped_column(db.ForeignKey('pt.id'), nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

    @property
    def parent_nama(self):
        pt = db.session.get(PT, self.reference)
        if pt:
            kota = db.session.get(Kota, pt.reference)
            if kota:
                return f"{pt.nama} - {kota.nama}"
            return pt.nama
        return ""

class LokasiKerja(db.Model):
    __tablename__ = 'lokasi_kerja'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    kode_unit: Mapped[str] = mapped_column(db.String(50), nullable=False)
    owner: Mapped[int] = mapped_column(db.String(50), nullable=False)
    pulau: Mapped[int] = mapped_column(db.String(50), nullable=False)
    kota: Mapped[int] = mapped_column(db.String(50), nullable=False)
    pt: Mapped[int] = mapped_column(db.String(50), nullable=False)
    nama: Mapped[int] = mapped_column(db.String(50), nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class KodeUnit(db.Model):
    __tablename__ = 'kode_unit'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    reference: Mapped[int] = mapped_column(db.ForeignKey('unit.id'), nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class NamaAsuransi(db.Model):
    __tablename__ = 'nama_asuransi'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class Merk(db.Model):
    __tablename__ = 'merk'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class Kategori(db.Model):
    __tablename__ = 'kategori'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

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
    __tablename__ = 'images'
    
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
    nama_asuransi: Mapped[str] = mapped_column(nullable=True)
    no_polis: Mapped[str] = mapped_column(nullable=True)
    no_polisi: Mapped[str] = mapped_column(nullable=False)
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
    tanggal_berakhir_baru: Mapped[str] = mapped_column(nullable=True)
    jumlah_dibayar:Mapped[float] = mapped_column(nullable=False) 
    tanggal_bayar: Mapped[str] = mapped_column(nullable=False)
    tanggal_input: Mapped[str] = mapped_column(nullable=False)
    diinput_oleh: Mapped[str] = mapped_column(nullable=False)

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
    try:
        if selected_pulau:
            pulau = db.session.execute(
                db.select(Pulau).where(db.func.upper(Pulau.nama) == selected_pulau.upper().strip())
            ).scalar_one_or_none()
            if not pulau:
                return []
            db_entries = db.session.execute(
                db.select(Kota).where(Kota.reference == pulau.id).order_by(Kota.nama)
            ).scalars().all()
        else:
            db_entries = db.session.execute(
                db.select(Kota).order_by(Kota.nama)
            ).scalars().all()
        return [(k.nama, k.nama) for k in db_entries]
    except Exception as e:
        print(f"Error in get_kota_choices: {e}")
        return []

def get_pt_choices(selected_kota=None):
    if not selected_kota:
        return []
    try:
        kota = db.session.execute(
            db.select(Kota).where(db.func.upper(Kota.nama) == selected_kota.upper().strip())
        ).scalar_one_or_none()
        if not kota:
            return []
        db_entries = db.session.execute(
            db.select(PT).where(PT.reference == kota.id).order_by(PT.nama)
        ).scalars().all()
        seen = set()
        choices = []
        for pt in db_entries:
            if pt.nama not in seen:
                choices.append((pt.nama, pt.nama))
                seen.add(pt.nama)
        return choices
    except Exception as e:
        print(f"Error in get_pt_choices: {e}")
        return []

def get_unit_choices(selected_pt=None, selected_kota=None):
    if not selected_pt:
        return []
    try:
        pt_query = db.select(PT).where(db.func.upper(PT.nama) == selected_pt.upper().strip())
        if selected_kota:
            kota = db.session.execute(
                db.select(Kota).where(db.func.upper(Kota.nama) == selected_kota.upper().strip())
            ).scalar_one_or_none()
            if kota:
                pt_query = pt_query.where(PT.reference == kota.id)
        
        pt_list = db.session.execute(pt_query).scalars().all()
        if not pt_list:
            return []
        
        # If there are multiple PT objects with the same name, we can select their unit entries
        pt_ids = [pt.id for pt in pt_list]
        db_entries = db.session.execute(
            db.select(Unit).where(Unit.reference.in_(pt_ids)).order_by(Unit.nama)
        ).scalars().all()
        return [(u.nama, u.nama) for u in db_entries]
    except Exception as e:
        print(f"Error in get_unit_choices: {e}")
        return []

def get_cn_choices(selected_unit=None, selected_pt=None, selected_kota=None):
    if not selected_unit:
        return []
    try:
        unit_upper = selected_unit.upper().strip()
        
        # Build list of possible suffixes if unit_upper has hyphens
        possible_names = [unit_upper]
        if "-" in unit_upper:
            parts = unit_upper.split("-")
            for i in range(1, len(parts)):
                suffix = "-".join(parts[i:]).strip()
                if suffix:
                    possible_names.append(suffix)
        
        # Strip PT prefix if present as another possible name just in case
        if selected_pt and unit_upper.startswith(selected_pt.upper() + "-"):
            prefix_len = len(selected_pt) + 1
            stripped_unit = unit_upper[prefix_len:].strip()
            if stripped_unit not in possible_names:
                possible_names.append(stripped_unit)

        query = db.select(LokasiKerja.kode_unit).where(
            (db.func.upper(LokasiKerja.owner).in_(possible_names)) |
            (db.func.upper(LokasiKerja.nama).in_(possible_names))
        )
        if selected_pt:
            query = query.where(db.func.upper(LokasiKerja.pt) == selected_pt.upper().strip())
        if selected_kota:
            query = query.where(db.func.upper(LokasiKerja.kota) == selected_kota.upper().strip())
        db_entries = db.session.execute(query.distinct()).scalars().all()
        
        choices = []
        for cn_val in db_entries:
            if cn_val:
                cn_clean = cn_val.strip()
                choices.append((cn_clean, cn_clean))
        return sorted(choices, key=lambda x: x[1])
    except Exception as e:
        print(f"Error in get_cn_choices: {e}")
        return []

def get_cn_choices_asset(selected_unit=None, selected_pt=None, selected_kota=None):
    if not selected_unit:
        return []
    try:
        unit_upper = selected_unit.upper().strip()
        
        # Build list of possible suffixes if unit_upper has hyphens
        possible_names = [unit_upper]
        if "-" in unit_upper:
            parts = unit_upper.split("-")
            for i in range(1, len(parts)):
                suffix = "-".join(parts[i:]).strip()
                if suffix:
                    possible_names.append(suffix)
        
        # Strip PT prefix if present as another possible name just in case
        if selected_pt and unit_upper.startswith(selected_pt.upper() + "-"):
            prefix_len = len(selected_pt) + 1
            stripped_unit = unit_upper[prefix_len:].strip()
            if stripped_unit not in possible_names:
                possible_names.append(stripped_unit)

        query = db.select(DataEntry.kode_unit, DataEntry.pkey).where(
            (db.func.upper(DataEntry.unit).in_(possible_names)) |
            (db.func.upper(DataEntry.lokasi_kerja).in_(possible_names))
        )
        # Exclude already mutated units (notes containing "Dimutasi ke")
        query = query.where(
            (DataEntry.notes == None) |
            (~DataEntry.notes.ilike('%Dimutasi ke%'))
        )
        if selected_pt:
            query = query.where(db.func.upper(DataEntry.pt) == selected_pt.upper().strip())
        if selected_kota:
            query = query.where(db.func.upper(DataEntry.kota) == selected_kota.upper().strip())
        
        db_entries = db.session.execute(query.distinct()).all()
        
        choices = []
        for row in db_entries:
            cn_val = row[0]
            pkey_val = row[1]
            if cn_val:
                cn_clean = cn_val.strip()
                choices.append((pkey_val, cn_clean))
        return sorted(choices, key=lambda x: x[1])
    except Exception as e:
        print(f"Error in get_cn_choices_asset: {e}")
        return []


def populate_form_choices(form):
    pulau_entries = db.session.execute(db.select(Pulau).order_by(Pulau.nama)).scalars().all()
    form.pulau.choices = [('', '-- Pilih Pulau --')] + [(p.nama, p.nama) for p in pulau_entries]
    
    if form.pulau.data:
        form.kota.choices = [('', '-- Pilih Kota --')] + get_kota_choices(form.pulau.data)
    else:
        form.kota.choices = [('', '-- Pilih Kota --')]
        
    if form.kota.data:
        form.pt.choices = [('', '-- Pilih PT --')] + get_pt_choices(form.kota.data)
    else:
        form.pt.choices = [('', '-- Pilih PT --')]
        
    if form.pt.data:
        form.unit.choices = [('', '-- Pilih Unit PT --')] + get_unit_choices(form.pt.data, form.kota.data)
    else:
        form.unit.choices = [('', '-- Pilih Unit PT --')]
        
    unit_entries = db.session.execute(db.select(Unit).order_by(Unit.nama)).scalars().all()
    lokasi_choices = []
    for u in unit_entries:
        pt = db.session.get(PT, u.reference)
        if pt:
            display_val = f"{u.nama}"
            lokasi_choices.append((display_val, display_val))
        else:
            lokasi_choices.append((u.nama, u.nama))
    form.lokasi_kerja.choices = [('', '-- Pilih Unit Lokasi Kerja --')] + sorted(lokasi_choices, key=lambda x: x[0])

    asuransi_entries = db.session.execute(db.select(NamaAsuransi).order_by(NamaAsuransi.nama)).scalars().all()
    form.nama_asuransi.choices = [('', '-- Pilih Asuransi --'), ('-', '-')] + [(a.nama, a.nama) for a in asuransi_entries]
    
    merk_entries = db.session.execute(db.select(Merk).order_by(Merk.nama)).scalars().all()
    form.merk.choices = [('', '-- Pilih Merk --')] + [(m.nama, m.nama) for m in merk_entries]
    
    kategori_entries = db.session.execute(db.select(Kategori).order_by(Kategori.nama)).scalars().all()
    form.kategori.choices = [('', '-- Pilih Kategori --')] + [(k.nama, k.nama) for k in kategori_entries]

    current_year = datetime.today().year
    form.year.choices = [('', '-- Pilih Tahun --')] + [(str(y), str(y)) for y in range(current_year + 5, 1979, -1)]

def populate_mutasi_choices(form):
    pulau_entries = db.session.execute(db.select(Pulau).order_by(Pulau.nama)).scalars().all()
    pulau_choices = [('', '-- Pilih Pulau --')] + [(p.nama, p.nama) for p in pulau_entries]
    
    # Populate Source Dropdowns
    form.pulau_asal.choices = pulau_choices
    if form.pulau_asal.data:
        form.kota_asal.choices = [('', '-- Pilih Kota --')] + get_kota_choices(form.pulau_asal.data)
    else:
        form.kota_asal.choices = [('', '-- Pilih Kota --')]
        
    if form.kota_asal.data:
        form.pt_asal.choices = [('', '-- Pilih PT --')] + get_pt_choices(form.kota_asal.data)
    else:
        form.pt_asal.choices = [('', '-- Pilih PT --')]
        
    if form.pt_asal.data:
        form.unit_asal.choices = [('', '-- Pilih Unit PT --')] + get_unit_choices(form.pt_asal.data, form.kota_asal.data)
    else:
        form.unit_asal.choices = [('', '-- Pilih Unit PT --')]
        
    if form.unit_asal.data:
        form.cn_asal.choices = [('', '-- Pilih Kode Unit --')] + get_cn_choices_asset(form.unit_asal.data, form.pt_asal.data, form.kota_asal.data)
    else:
        form.cn_asal.choices = [('', '-- Pilih Kode Unit --')]

    # Populate Destination Dropdowns
    form.pulau_tujuan.choices = pulau_choices
    if form.pulau_tujuan.data:
        form.kota_tujuan.choices = [('', '-- Pilih Kota --')] + get_kota_choices(form.pulau_tujuan.data)
    else:
        form.kota_tujuan.choices = [('', '-- Pilih Kota --')]
        
    if form.kota_tujuan.data:
        form.pt_tujuan.choices = [('', '-- Pilih PT --')] + get_pt_choices(form.kota_tujuan.data)
    else:
        form.pt_tujuan.choices = [('', '-- Pilih PT --')]
        
    if form.pt_tujuan.data:
        form.unit_tujuan.choices = [('', '-- Pilih Unit PT --')] + get_unit_choices(form.pt_tujuan.data, form.kota_tujuan.data)
    else:
        form.unit_tujuan.choices = [('', '-- Pilih Unit PT --')]
        
    # Populate Lokasi Kerja Tujuan
    unit_entries = db.session.execute(db.select(Unit).order_by(Unit.nama)).scalars().all()
    lokasi_choices = []
    for u in unit_entries:
        pt = db.session.get(PT, u.reference)
        if pt:
            display_val = f"{u.nama}"
            lokasi_choices.append((display_val, display_val))
        else:
            lokasi_choices.append((u.nama, u.nama))
    form.lokasi_kerja_tujuan.choices = [('', '-- Pilih Unit Lokasi Kerja --')] + sorted(lokasi_choices, key=lambda x: x[0])
    
    # Fallback validation choice appending to prevent WTForms choice validation mismatch
    if form.pulau_asal.data and form.pulau_asal.data not in [c[0] for c in form.pulau_asal.choices]:
        form.pulau_asal.choices.append((form.pulau_asal.data, form.pulau_asal.data))
    if form.kota_asal.data and form.kota_asal.data not in [c[0] for c in form.kota_asal.choices]:
        form.kota_asal.choices.append((form.kota_asal.data, form.kota_asal.data))
    if form.pt_asal.data and form.pt_asal.data not in [c[0] for c in form.pt_asal.choices]:
        form.pt_asal.choices.append((form.pt_asal.data, form.pt_asal.data))
    if form.unit_asal.data and form.unit_asal.data not in [c[0] for c in form.unit_asal.choices]:
        form.unit_asal.choices.append((form.unit_asal.data, form.unit_asal.data))
    if form.cn_asal.data and form.cn_asal.data not in [c[0] for c in form.cn_asal.choices]:
        form.cn_asal.choices.append((form.cn_asal.data, form.cn_asal.data))

    if form.pulau_tujuan.data and form.pulau_tujuan.data not in [c[0] for c in form.pulau_tujuan.choices]:
        form.pulau_tujuan.choices.append((form.pulau_tujuan.data, form.pulau_tujuan.data))
    if form.kota_tujuan.data and form.kota_tujuan.data not in [c[0] for c in form.kota_tujuan.choices]:
        form.kota_tujuan.choices.append((form.kota_tujuan.data, form.kota_tujuan.data))
    if form.pt_tujuan.data and form.pt_tujuan.data not in [c[0] for c in form.pt_tujuan.choices]:
        form.pt_tujuan.choices.append((form.pt_tujuan.data, form.pt_tujuan.data))
    if form.unit_tujuan.data and form.unit_tujuan.data not in [c[0] for c in form.unit_tujuan.choices]:
        form.unit_tujuan.choices.append((form.unit_tujuan.data, form.unit_tujuan.data))
    if form.lokasi_kerja_tujuan.data and form.lokasi_kerja_tujuan.data not in [c[0] for c in form.lokasi_kerja_tujuan.choices]:
        form.lokasi_kerja_tujuan.choices.append((form.lokasi_kerja_tujuan.data, form.lokasi_kerja_tujuan.data))

class DataForm(FlaskForm):
    #Primary
    pulau = SelectField('Pulau', choices=[], validators=[DataRequired(message="Pulau wajib diisi!")])
    kota = SelectField('Kota', choices=[], validators=[DataRequired(message="Kota wajib diisi!")])
    pt = SelectField('Nama PT', choices=[], validators=[DataRequired(message="Nama PT wajib diisi!")])
    unit = SelectField('Nama Unit PT', choices=[], validators=[DataRequired(message="Nama Unit PT wajib diisi!")])
    kode_unit = StringField('Kode Unit', validators=[DataRequired(message="Kode Unit wajib diisi!"), Length(max=100)])
    pkey = StringField('PKEY', validators=[Optional()])
    lokasi_kerja = SelectField('Lokasi Kerja', choices=[], validators=[DataRequired(message="Lokasi Kerja wajib diisi!")])

    #Details
    nama_asuransi = SelectField('Nama Asuransi', choices=[], validators=[Optional()])
    no_polis = StringField('No Polis', validators=[Optional()])
    no_polisi = StringField('No Polisi', validators=[DataRequired(message="No. Polisi wajib diisi!"), Length(max=20)])
    merk = SelectField('Merk', choices=[], validators=[DataRequired(message="Merk wajib diisi!")])
    kategori = SelectField('Kategori', choices=[], validators=[DataRequired(message="Kategori wajib diisi!")])
    eqp_model = StringField('Equipment Model', validators=[DataRequired(message="Model Alat wajib diisi!"), Length(max=20)])
    sn_equipment = StringField('S/N Equipment', validators=[DataRequired(message="No. Rangka wajib diisi!"), Length(max=20)])
    sn_engine = StringField('S/N Engine', validators=[DataRequired(message="No. Mesin wajib diisi!"), Length(max=20)])
    
    status_stnk = SelectField('Status STNK', choices=[('OFF', 'OFF'), ('ON', 'ON')], validators=[DataRequired()])
    status_asuransi = SelectField('Status Asuransi', choices=[('OFF', 'OFF'), ('ON', 'ON')], validators=[DataRequired()])
    tanggal_berakhir_stnk = DateField('Tanggal Berakhir STNK', validators=[Optional()])
    tanggal_berakhir_asuransi = DateField('Tanggal Berakhir Asuransi', validators=[Optional()])
    
    year = SelectField('Tahun Pembuatan', choices=[], validators=[DataRequired(message="Tahun harus diisi!")])
    
    notes = StringField('Notes', validators=[Optional()])

class ExtendForm(FlaskForm):
    jenis = SelectField(
        'Jenis', 
        choices=[('STNK', 'STNK'), ('Asuransi', 'Asuransi')]
    )
    cn = SelectField('CN', choices=[], validators=[
        DataRequired(message="CN tidak boleh kosong.")])
    pulau = SelectField('Pulau', choices=[], validators=[DataRequired(message="Pulau wajib diisi!")])
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
    update_biaya_perpanjang = StringField('Biaya Perpanjang Baru', validators=[Optional()])
    update_biaya_admin = StringField('Biaya Admin Baru', validators=[Optional()])

class MutasiForm(FlaskForm):
    # Source (Unit to Mutate)
    pulau_asal = SelectField('Pulau Asal', choices=[], validators=[DataRequired(message="Pulau asal wajib diisi!")])
    kota_asal = SelectField('Kota Asal', choices=[], validators=[DataRequired(message="Kota asal wajib diisi!")])
    pt_asal = SelectField('Nama PT Asal', choices=[], validators=[DataRequired(message="Nama PT asal wajib diisi!")])
    unit_asal = SelectField('Nama Unit Asal', choices=[], validators=[DataRequired(message="Nama Unit asal wajib diisi!")])
    cn_asal = SelectField('Kode Unit (CN) Asal', choices=[], validators=[DataRequired(message="Kode Unit asal wajib diisi!")])

    # Destination (New Location)
    pulau_tujuan = SelectField('Pulau Tujuan', choices=[], validators=[DataRequired(message="Pulau tujuan wajib diisi!")])
    kota_tujuan = SelectField('Kota Tujuan', choices=[], validators=[DataRequired(message="Kota tujuan wajib diisi!")])
    pt_tujuan = SelectField('Nama PT Tujuan', choices=[], validators=[DataRequired(message="Nama PT tujuan wajib diisi!")])
    unit_tujuan = SelectField('Nama Unit Tujuan', choices=[], validators=[DataRequired(message="Nama Unit tujuan wajib diisi!")])
    lokasi_kerja_tujuan = SelectField('Lokasi Kerja Tujuan', choices=[], validators=[DataRequired(message="Lokasi Kerja tujuan wajib diisi!")])
    kode_unit_tujuan = StringField('Kode Unit (CN) Tujuan', validators=[DataRequired(message="Kode Unit tujuan wajib diisi!"), Length(max=100)])

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
    
    for log in all_logs:
        if log.pkey:
            log.unit = log.pkey.split('-')[-3] + '-' + log.pkey.split('-')[-2]
            log.cn = log.pkey.split('-')[-1]
        else:
            log.unit = '-'
            log.cn = '-'

    # 4. Tampilkan ke template baru dengan mengirim parameter active_page='logs'
    return render_template('logs.html', logs=all_logs, active_page='logs')

@app.route('/master-all')
def master_all():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    # Read group, sort, and filter criteria
    group_by = request.args.get('groupby', 'ALL').strip()
    sort_by = request.args.get('sortby', 'id_desc').strip()
    
    pulau_filter = request.args.get('pulau', '').strip()
    kota_filter = request.args.get('kota', '').strip()
    pt_filter = request.args.get('pt', '').strip()
    unit_filter = request.args.get('unit', '').strip()
    lokasi_kerja_filter = request.args.get('lokasi_kerja', '').strip()
    asuransi_filter = request.args.get('nama_asuransi', '').strip()
    merk_filter = request.args.get('merk', '').strip()
    kategori_filter = request.args.get('kategori', '').strip()
    model_filter = request.args.get('eqp_model', '').strip()
    
    query = db.select(DataEntry)
    
    # Apply filters
    if pulau_filter:
        query = query.where(db.func.upper(DataEntry.pulau) == pulau_filter.upper())
    if kota_filter:
        query = query.where(db.func.upper(DataEntry.kota) == kota_filter.upper())
    if pt_filter:
        query = query.where(db.func.upper(DataEntry.pt) == pt_filter.upper())
    if unit_filter:
        query = query.where(
            (db.func.upper(DataEntry.unit) == unit_filter.upper()) | 
            (DataEntry.unit.like(f"%{unit_filter}%"))
        )
    if asuransi_filter:
        query = query.where(db.func.upper(DataEntry.nama_asuransi) == asuransi_filter.upper())
    if merk_filter:
        query = query.where(db.func.upper(DataEntry.merk) == merk_filter.upper())
    if kategori_filter:
        query = query.where(db.func.upper(DataEntry.kategori) == kategori_filter.upper())
    if model_filter:
        query = query.where(db.func.upper(DataEntry.eqp_model) == model_filter.upper())
    if lokasi_kerja_filter:
        query = query.where(db.func.upper(DataEntry.lokasi_kerja) == lokasi_kerja_filter.upper())
        
    # Apply sorting
    if sort_by == 'pulau':
        query = query.order_by(DataEntry.pulau.asc())
    elif sort_by == 'kota':
        query = query.order_by(DataEntry.kota.asc())
    elif sort_by == 'pt':
        query = query.order_by(DataEntry.pt.asc())
    elif sort_by == 'unit':
        query = query.order_by(DataEntry.unit.asc())
    elif sort_by == 'lokasi_kerja':
        query = query.order_by(DataEntry.lokasi_kerja.asc())
    elif sort_by == 'nama_asuransi':
        query = query.order_by(DataEntry.nama_asuransi.asc())
    elif sort_by == 'merk':
        query = query.order_by(DataEntry.merk.asc())
    elif sort_by == 'kategori':
        query = query.order_by(DataEntry.kategori.asc())
    elif sort_by == 'eqp_model':
        query = query.order_by(DataEntry.eqp_model.asc())
    else: # id_desc
        query = query.order_by(DataEntry.id.desc())
        
    results = db.session.execute(query).scalars().all()
    
    # Extract distinct option lists from the actual master data tables
    unit_entries = db.session.execute(db.select(Unit).order_by(Unit.nama)).scalars().all()
    lokasi_choices = []
    for u in unit_entries:
        pt_obj = db.session.get(PT, u.reference)
        if pt_obj:
            display_val = f"{u.nama}"
            lokasi_choices.append(display_val)
        else:
            lokasi_choices.append(u.nama)

    filter_options = {
        'pulau': db.session.execute(db.select(Pulau.nama).order_by(Pulau.nama)).scalars().all(),
        'kota': db.session.execute(db.select(Kota.nama).order_by(Kota.nama)).scalars().all(),
        'pt': db.session.execute(db.select(PT.nama).distinct().order_by(PT.nama)).scalars().all(),
        'unit': db.session.execute(db.select(Unit.nama).distinct().order_by(Unit.nama)).scalars().all(),
        'lokasi_kerja': sorted(list(set(lokasi_choices))),
        'nama_asuransi': db.session.execute(db.select(NamaAsuransi.nama).order_by(NamaAsuransi.nama)).scalars().all(),
        'merk': db.session.execute(db.select(Merk.nama).order_by(Merk.nama)).scalars().all(),
        'kategori': db.session.execute(db.select(Kategori.nama).order_by(Kategori.nama)).scalars().all(),
        'eqp_model': db.session.execute(db.select(DataEntry.eqp_model).distinct().where(DataEntry.eqp_model != None).order_by(DataEntry.eqp_model)).scalars().all(),
    }
    
    selected_filters = {
        'pulau': pulau_filter,
        'kota': kota_filter,
        'pt': pt_filter,
        'unit': unit_filter,
        'lokasi_kerja': lokasi_kerja_filter,
        'nama_asuransi': asuransi_filter,
        'merk': merk_filter,
        'kategori': kategori_filter,
        'eqp_model': model_filter
    }
    
    # Group results into accordion sections
    grouped_data = {}
    if group_by == 'ALL':
        grouped_data = {'ALL': results}
    else:
        from collections import defaultdict
        grouped_dict = defaultdict(list)
        for entry in results:
            val = getattr(entry, group_by, None)
            key_name = str(val) if val is not None else "Tidak Ada Data"
            grouped_dict[key_name].append(entry)
        # Sort accordion groups alphabetically by their group name
        grouped_data = {k: grouped_dict[k] for k in sorted(grouped_dict.keys())}
        
    return render_template(
        'master-all.html', 
        grouped_data=grouped_data, 
        filter_options=filter_options, 
        selected_filters=selected_filters,
        active_groupby=group_by,
        active_sortby=sort_by,
        active_page='master'
    )

@app.route('/master-lokasi-kerja')
def master_lokasi_kerja():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    # Read group, sort, and filter criteria
    group_by = request.args.get('groupby', 'ALL').strip()
    sort_by = request.args.get('sortby', 'id_desc').strip()
    
    pulau_filter = request.args.get('pulau', '').strip()
    kota_filter = request.args.get('kota', '').strip()
    pt_filter = request.args.get('pt', '').strip()
    unit_filter = request.args.get('unit', '').strip()
    lokasi_kerja_filter = request.args.get('lokasi_kerja', '').strip()
    asuransi_filter = request.args.get('nama_asuransi', '').strip()
    merk_filter = request.args.get('merk', '').strip()
    kategori_filter = request.args.get('kategori', '').strip()
    model_filter = request.args.get('eqp_model', '').strip()
    
    query = db.select(LokasiKerja)
    
    # Apply filters
    if pulau_filter:
        query = query.where(db.func.upper(LokasiKerja.pulau) == pulau_filter.upper())
    if kota_filter:
        query = query.where(db.func.upper(LokasiKerja.kota) == kota_filter.upper())
    if pt_filter:
        query = query.where(db.func.upper(LokasiKerja.pt) == pt_filter.upper())
    if unit_filter:
        query = query.where(
            (db.func.upper(LokasiKerja.owner) == unit_filter.upper()) | 
            (LokasiKerja.owner.like(f"%{unit_filter}%"))
        )
        
    # Apply sorting
    if sort_by == 'pulau':
        query = query.order_by(LokasiKerja.pulau.asc())
    elif sort_by == 'kota':
        query = query.order_by(LokasiKerja.kota.asc())
    elif sort_by == 'pt':
        query = query.order_by(LokasiKerja.pt.asc())
    elif sort_by == 'unit':
        query = query.order_by(LokasiKerja.unit.asc())
    elif sort_by == 'lokasi_kerja':
        query = query.order_by(LokasiKerja.lokasi_kerja.asc())
    else: # id_desc
        query = query.order_by(LokasiKerja.id.desc())
        
    results = db.session.execute(query).scalars().all()
    
    # Extract distinct option lists from the actual master data tables
    unit_entries = db.session.execute(db.select(Unit).order_by(Unit.nama)).scalars().all()
    lokasi_choices = []
    for u in unit_entries:
        pt_obj = db.session.get(PT, u.reference)
        if pt_obj:
            display_val = f"{u.nama}"
            lokasi_choices.append(display_val)
        else:
            lokasi_choices.append(u.nama)

    filter_options = {
        'pulau': db.session.execute(db.select(Pulau.nama).order_by(Pulau.nama)).scalars().all(),
        'kota': db.session.execute(db.select(Kota.nama).order_by(Kota.nama)).scalars().all(),
        'pt': db.session.execute(db.select(PT.nama).distinct().order_by(PT.nama)).scalars().all(),
        'unit': db.session.execute(db.select(Unit.nama).distinct().order_by(Unit.nama)).scalars().all(),
        'lokasi_kerja': sorted(list(set(lokasi_choices)))
    }
    
    selected_filters = {
        'pulau': pulau_filter,
        'kota': kota_filter,
        'pt': pt_filter,
        'unit': unit_filter,
        'lokasi_kerja': lokasi_kerja_filter
    }
    
    # Group results into accordion sections
    grouped_data = {}
    if group_by == 'ALL':
        grouped_data = {'ALL': results}
    else:
        from collections import defaultdict
        grouped_dict = defaultdict(list)
        for entry in results:
            val = getattr(entry, group_by, None)
            key_name = str(val) if val is not None else "Tidak Ada Data"
            grouped_dict[key_name].append(entry)
        # Sort accordion groups alphabetically by their group name
        grouped_data = {k: grouped_dict[k] for k in sorted(grouped_dict.keys())}
        
    return render_template(
        'master-lokasi-kerja.html', 
        grouped_data=grouped_data, 
        filter_options=filter_options, 
        selected_filters=selected_filters,
        active_groupby=group_by,
        active_sortby=sort_by,
        active_page='master'
    )
    
@app.route('/master-pulau')
def master_pulau():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(Pulau).order_by(Pulau.nama)
    ).scalars().all()
    return render_template('master.html', type='Pulau', entries=all_entries, active_page='master')

@app.route('/master-kota')
def master_kota():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(Kota).order_by(Kota.nama)
    ).scalars().all()
    references = db.session.execute(
        db.select(Pulau).order_by(Pulau.nama)
    ).scalars().all()
    return render_template('master.html', type='Kota', entries=all_entries, references_list=references, active_page='master')

@app.route('/master-pt')
def master_pt():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(PT).order_by(PT.nama)
    ).scalars().all()
    references = db.session.execute(
        db.select(Kota).order_by(Kota.nama)
    ).scalars().all()
    return render_template('master.html', type='PT', entries=all_entries, references_list=references, active_page='master')

@app.route('/master-unit')
def master_unit():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(Unit).order_by(Unit.nama)
    ).scalars().all()
    references = db.session.execute(
        db.select(PT).order_by(PT.nama)
    ).scalars().all()
    return render_template('master.html', type='Unit PT', entries=all_entries, references_list=references, active_page='master')

@app.route('/master-asuransi')
def master_asuransi():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(NamaAsuransi).order_by(NamaAsuransi.nama)
    ).scalars().all()
    return render_template('master.html', type='Asuransi', entries=all_entries, active_page='master')

@app.route('/master-merk')
def master_merk():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(Merk).order_by(Merk.nama)
    ).scalars().all()
    return render_template('master.html', type='Merk', entries=all_entries, active_page='master')

@app.route('/master-kategori')
def master_kategori():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))
    
    all_entries = db.session.execute(
        db.select(Kategori).order_by(Kategori.nama)
    ).scalars().all()
    return render_template('master.html', type='Kategori', entries=all_entries, active_page='master')

@app.route('/master/add/<type>', methods=['POST'])
def master_add(type):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    
    nama_input = request.form.get('nama', '').strip().upper()
    if not nama_input:
        flash("⚠️ Nama tidak boleh kosong!", "danger")
        return redirect(request.referrer or url_for('master'))
    
    logged_user = session.get('logged_user', 'System')
    
    try:
        # Check duplicate
        duplicate = False
        if type == 'Pulau':
            duplicate = db.session.execute(db.select(Pulau).where(Pulau.nama == nama_input)).scalar_one_or_none() is not None
        elif type == 'Kota':
            duplicate = db.session.execute(db.select(Kota).where(Kota.nama == nama_input)).scalar_one_or_none() is not None
        elif type == 'PT':
            ref_id = request.form.get('reference')
            if ref_id:
                duplicate = db.session.execute(
                    db.select(PT).where(PT.nama == nama_input, PT.reference == int(ref_id))
                ).scalar_one_or_none() is not None
        elif type == 'Unit PT':
            duplicate = db.session.execute(db.select(Unit).where(Unit.nama == nama_input)).scalar_one_or_none() is not None
        elif type == 'Asuransi':
            duplicate = db.session.execute(db.select(NamaAsuransi).where(NamaAsuransi.nama == nama_input)).scalar_one_or_none() is not None
        elif type == 'Merk':
            duplicate = db.session.execute(db.select(Merk).where(Merk.nama == nama_input)).scalar_one_or_none() is not None
        elif type == 'Kategori':
            duplicate = db.session.execute(db.select(Kategori).where(Kategori.nama == nama_input)).scalar_one_or_none() is not None

        if duplicate:
            if type == 'PT':
                flash(f"⚠️ Gagal! PT '{nama_input}' sudah terdaftar untuk Kota ini.", "danger")
            else:
                flash(f"⚠️ Gagal! Data {type} '{nama_input}' sudah ada di database.", "danger")
            return redirect(request.referrer or url_for('master'))

        if type == 'Pulau':
            new_item = Pulau(nama=nama_input, dilakukan_oleh=logged_user)
        elif type == 'Kota':
            ref_id = request.form.get('reference')
            if not ref_id:
                flash("⚠️ Referensi Pulau wajib dipilih!", "danger")
                return redirect(request.referrer or url_for('master'))
            new_item = Kota(nama=nama_input, reference=int(ref_id), dilakukan_oleh=logged_user)
        elif type == 'PT':
            ref_id = request.form.get('reference')
            if not ref_id:
                flash("⚠️ Referensi Kota wajib dipilih!", "danger")
                return redirect(request.referrer or url_for('master'))
            new_item = PT(nama=nama_input, reference=int(ref_id), dilakukan_oleh=logged_user)
        elif type == 'Unit PT':
            ref_id = request.form.get('reference')
            if not ref_id:
                flash("⚠️ Referensi PT wajib dipilih!", "danger")
                return redirect(request.referrer or url_for('master'))
            new_item = Unit(nama=nama_input, reference=int(ref_id), dilakukan_oleh=logged_user)
        elif type == 'Asuransi':
            new_item = NamaAsuransi(nama=nama_input, dilakukan_oleh=logged_user)
        elif type == 'Merk':
            new_item = Merk(nama=nama_input, dilakukan_oleh=logged_user)
        elif type == 'Kategori':
            new_item = Kategori(nama=nama_input, dilakukan_oleh=logged_user)
        else:
            flash("⚠️ Tipe master data tidak dikenal!", "danger")
            return redirect(request.referrer or url_for('master'))
        
        db.session.add(new_item)
        db.session.commit()
        flash(f"✅ Data {type} '{nama_input}' berhasil ditambahkan!", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Terjadi kesalahan: {str(e)}", "danger")
        
    return redirect(request.referrer or url_for('master'))

@app.route('/master')
def master():
    if(session['role'] != 'admin'):
        return redirect(url_for('dashboard'))

    return render_template('master-landing.html', active_page='master')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    check_and_update_expired_units()
    query = text("SELECT COUNT(*) FROM data_entries WHERE (notes IS NULL OR UPPER(notes) NOT LIKE '%DIMUTASI KE%')")
    total_peralatan=db.session.execute(query).scalar()

    # today = datetime.now().date()
    today = datetime.today().date()
    
    query = text("SELECT COUNT(*) FROM data_entries WHERE :today <= tanggal_berakhir_stnk::date AND (notes IS NULL OR UPPER(notes) NOT LIKE '%DIMUTASI KE%')")
    jumlah_stnk_aktif=db.session.execute(query, {"today": today}).scalar()

    query = text("SELECT COUNT(*) FROM data_entries WHERE :today <= tanggal_berakhir_asuransi::date AND (notes IS NULL OR UPPER(notes) NOT LIKE '%DIMUTASI KE%')")
    jumlah_asuransi_aktif=db.session.execute(query, {"today": today}).scalar()

    hari_ini = today.strftime('%Y-%m-%d')
    dua_bulan_lagi = (today + timedelta(days=60)).strftime('%Y-%m-%d')
    tiga_bulan_lagi = (today + timedelta(days=90)).strftime('%Y-%m-%d')

    not_mutated = (DataEntry.notes == None) | (~DataEntry.notes.ilike('%Dimutasi ke%'))

    stnk_expired = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk < hari_ini, not_mutated).all()
    stnk_notice = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk >= dua_bulan_lagi, DataEntry.tanggal_berakhir_stnk <= tiga_bulan_lagi, not_mutated).all()
    stnk_warning = DataEntry.query.filter(DataEntry.tanggal_berakhir_stnk >= hari_ini, DataEntry.tanggal_berakhir_stnk <= dua_bulan_lagi, not_mutated).all()
    stnk_none = DataEntry.query.filter((DataEntry.tanggal_berakhir_stnk == None), not_mutated).all()
    
    asuransi_expired = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi < hari_ini, not_mutated).all()
    asuransi_notice = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi >= dua_bulan_lagi, DataEntry.tanggal_berakhir_asuransi <= tiga_bulan_lagi, not_mutated).all()
    asuransi_warning = DataEntry.query.filter(DataEntry.tanggal_berakhir_asuransi >= hari_ini, DataEntry.tanggal_berakhir_asuransi <= dua_bulan_lagi, not_mutated).all()
    asuransi_none = DataEntry.query.filter((DataEntry.tanggal_berakhir_asuransi == None), not_mutated).all()

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
    populate_form_choices(form)
    return render_template('form.html', form=form, active_page='transaksi')

@app.route('/perpanjang')
def perpanjang():
    form = ExtendForm()
    pulau_entries = db.session.execute(db.select(Pulau).order_by(Pulau.nama)).scalars().all()
    form.pulau.choices = [('', '-- Pilih Pulau --')] + [(p.nama, p.nama) for p in pulau_entries]
    form.kota.choices = [('', '-- Pilih Kota --')]
    form.pt.choices = [('', '-- Pilih PT --')]
    form.unit.choices = [('', '-- Pilih Unit PT --')]
    form.cn.choices = [('', '-- Pilih Kode Unit --')]
    return render_template('perpanjang.html', form=form, active_page='transaksi')

@app.route('/mutasi', methods=['GET', 'POST'])
def mutasi():
    if session['role'] not in ['admin', 'user']:
        return redirect(url_for('dashboard'))
        
    form = MutasiForm()
    
    # Handle GET request with pre-selected pkey
    preselected_pkey = request.args.get('pkey', '').strip()
    preselected_entry = None
    if preselected_pkey:
        preselected_entry = db.session.execute(
            db.select(DataEntry).where(DataEntry.pkey == preselected_pkey)
        ).scalar_one_or_none()
        
    if request.method == 'POST':
        populate_mutasi_choices(form)
        
        if form.validate_on_submit():
            pkey_asal = form.cn_asal.data
            entry = db.session.execute(
                db.select(DataEntry).where(
                    (db.func.upper(DataEntry.pkey) == pkey_asal.upper().strip()) |
                    (
                        (db.func.upper(DataEntry.kode_unit) == pkey_asal.upper().strip()) &
                        (db.func.upper(DataEntry.pulau) == form.pulau_asal.data.upper().strip()) &
                        (db.func.upper(DataEntry.kota) == form.kota_asal.data.upper().strip()) &
                        (db.func.upper(DataEntry.pt) == form.pt_asal.data.upper().strip()) &
                        (db.func.upper(DataEntry.unit) == form.unit_asal.data.upper().strip())
                    )
                )
            ).scalar_one_or_none()
            
            if not entry:
                flash("Data unit asal tidak ditemukan.", "danger")
                return redirect(url_for('mutasi'))
            
            # Check if the unit is already mutated
            if entry.notes and "dimutasi ke" in entry.notes.lower():
                flash("Unit ini sudah pernah dimutasi dan tidak dapat dimutasi kembali.", "danger")
                return redirect(url_for('mutasi'))
            
            # Destination values
            dest_pulau = form.pulau_tujuan.data
            dest_kota = form.kota_tujuan.data
            dest_pt = form.pt_tujuan.data.upper().strip()
            dest_unit = form.unit_tujuan.data.upper().strip()
            dest_lokasi = form.lokasi_kerja_tujuan.data
            dest_cn = form.kode_unit_tujuan.data.upper().replace(" ", "")
            dest_unit_combined = f"{dest_unit}"
            
            new_pkey = f"{dest_pulau}-{dest_kota}-{dest_pt}-{dest_unit}-{dest_cn}"
            
            if new_pkey != entry.pkey:
                existing = db.session.execute(
                    db.select(DataEntry).where(DataEntry.pkey == new_pkey)
                ).scalar_one_or_none()
                if existing:
                    flash(f"Gagal mutasi: Unit dengan kode {dest_cn} sudah terdaftar di lokasi tujuan ({new_pkey}).", "danger")
                    return render_template('mutasi.html', form=form, preselected_entry=preselected_entry, active_page='transaksi')
            
            try:
                old_pkey = entry.pkey
                old_pulau = entry.pulau
                old_kota = entry.kota
                old_pt = entry.pt
                old_unit = entry.unit
                old_kode_unit = entry.kode_unit
                
                if old_pkey != new_pkey:
                    stmt = text("""
                        INSERT INTO images (pkey, filename, file_data)
                        SELECT :new_pkey, filename, file_data
                        FROM images
                        WHERE pkey = :old_pkey
                    """)

                    db.session.execute(stmt, {"new_pkey": new_pkey, "old_pkey": old_pkey})
                    
                new_record = DataEntry(
                    pulau=dest_pulau,
                    kota=dest_kota,
                    pt=dest_pt,
                    unit=dest_unit_combined,
                    kode_unit=dest_cn,
                    pkey=new_pkey,
                    lokasi_kerja=dest_lokasi,

                    nama_asuransi=entry.nama_asuransi.upper().strip(),
                    no_polis=entry.no_polis.upper().strip() if entry.no_polis else None,
                    no_polisi=entry.no_polisi.upper().replace(" ", "") if entry.no_polisi else None,
                    merk=entry.merk.upper().strip() if entry.merk else None,
                    kategori=entry.kategori.upper() if entry.kategori else None,
                    eqp_model=entry.eqp_model.upper().strip() if entry.eqp_model else None,
                    sn_equipment=entry.sn_equipment,
                    sn_engine=entry.sn_engine,
                    status_stnk=entry.status_stnk,
                    status_asuransi=entry.status_asuransi,
                    tanggal_berakhir_stnk=entry.tanggal_berakhir_stnk if entry.tanggal_berakhir_stnk else None,
                    tanggal_berakhir_asuransi=entry.tanggal_berakhir_asuransi if entry.tanggal_berakhir_asuransi else None,
                    year=entry.year,
                    notes=entry.notes,
                    tanggal_input=datetime.today().date(),
                    diinput_oleh=session['logged_user']
                )
                db.session.add(new_record)

                # Resolve Lokasi Kerja's pulau, kota, and pt from the selected lokasi_kerja (dest_lokasi)
                loc_unit = db.session.execute(
                    db.select(Unit).where(db.func.upper(Unit.nama) == dest_lokasi.upper().strip())
                ).scalars().first()
                
                loc_pt = ""
                loc_kota = ""
                loc_pulau = ""
                
                if loc_unit:
                    pt_obj = db.session.get(PT, loc_unit.reference)
                    if pt_obj:
                        loc_pt = pt_obj.nama
                        kota_obj = db.session.get(Kota, pt_obj.reference)
                        if kota_obj:
                            loc_kota = kota_obj.nama
                            pulau_obj = db.session.get(Pulau, kota_obj.reference)
                            if pulau_obj:
                                loc_pulau = pulau_obj.nama

                if not loc_pt:
                    loc_pt = dest_pt
                if not loc_kota:
                    loc_kota = dest_kota
                if not loc_pulau:
                    loc_pulau = dest_pulau

                lok_rec = db.session.execute(
                    db.select(LokasiKerja).where(
                        db.func.upper(LokasiKerja.kode_unit) == old_kode_unit.upper().strip(),
                        db.func.upper(LokasiKerja.owner) == old_unit.upper().strip()
                    )
                ).scalars().first()
                if lok_rec:
                    lok_rec.pulau = loc_pulau
                    lok_rec.kota = loc_kota
                    lok_rec.pt = loc_pt
                    lok_rec.owner = dest_unit
                    lok_rec.nama = dest_lokasi
                    lok_rec.kode_unit = dest_cn
                    lok_rec.dilakukan_oleh = session.get('logged_user', 'System')
                    lok_rec.tanggal_aksi = datetime.today()
                else:
                    new_lok = LokasiKerja(
                        kode_unit=dest_cn,
                        owner=dest_unit,
                        nama=dest_lokasi,
                        pt=loc_pt,
                        kota=loc_kota,
                        pulau=loc_pulau,
                        dilakukan_oleh=session.get('logged_user', 'System'),
                        tanggal_aksi=datetime.today()
                    )
                    db.session.add(new_lok)
                
                audit_log = AuditLog(
                    pkey=new_pkey,
                    aksi="EDIT",
                    kolom_diubah="Mutasi Unit",
                    nilai_lama=old_pkey,
                    nilai_baru=new_pkey,
                    dilakukan_oleh=session['logged_user']
                )
                db.session.add(audit_log)

                entry.notes = f"Dimutasi ke {dest_unit_combined.upper().strip()} ({dest_cn})"

                db.session.commit()
                flash(f"Sukses melakukan mutasi unit {dest_cn} ke lokasi baru.", "success")
                return redirect(url_for('details', pkey=new_pkey))
                
            except Exception as e:
                db.session.rollback()
                flash(f"Terjadi kesalahan saat menyimpan mutasi: {e}", "danger")
        else:
            flash(f"Gagal memvalidasi form mutasi: {form.errors}", "danger")
    else:
        # GET request, populate initial choices
        populate_mutasi_choices(form)
        if preselected_entry:
            # Prefill the source choices and fields
            form.pulau_asal.data = preselected_entry.pulau
            form.kota_asal.choices = [('', '-- Pilih Kota --')] + get_kota_choices(preselected_entry.pulau)
            form.kota_asal.data = preselected_entry.kota
            form.pt_asal.choices = [('', '-- Pilih PT --')] + get_pt_choices(preselected_entry.kota)
            form.pt_asal.data = preselected_entry.pt
            form.unit_asal.choices = [('', '-- Pilih Unit PT --')] + get_unit_choices(preselected_entry.pt, preselected_entry.kota)
            form.unit_asal.data = preselected_entry.unit
            form.cn_asal.choices = [(preselected_entry.pkey, preselected_entry.kode_unit)]
            form.cn_asal.data = preselected_entry.pkey
            # Prefill the destination CN field with the source CN
            form.kode_unit_tujuan.data = preselected_entry.kode_unit
            
    return render_template(
        'mutasi.html', 
        form=form, 
        preselected_entry=preselected_entry, 
        active_page='transaksi'
    )

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
    pulau_list = db.session.execute(db.select(Pulau).order_by(Pulau.nama)).scalars().all()
    
    if not pkey:        
        return render_template('details.html', entry=None, all_cn_list=all_cn_list, pulau_list=pulau_list, active_page='details')
    
    entry = db.session.execute(
        db.select(DataEntry).where(
            (db.func.upper(DataEntry.pkey) == pkey.upper().strip()) |
            (db.func.upper(DataEntry.kode_unit) == pkey.upper().strip())
        )
    ).scalar_one_or_none()
    
    if not entry:
        flash("Data unit tidak ditemukan!", "danger")
        return redirect(url_for('details'))
        
    key = entry.pkey
 
    db_images = db.session.execute(
        db.select(UnitImage.id).where(UnitImage.pkey == key).order_by(UnitImage.id)
    ).scalars().all()
        
    return render_template('details.html', all_cn_list=all_cn_list, entry=entry, db_images=db_images, pulau_list=pulau_list, active_page='details')

@app.route('/submit_extend', methods=['POST'])
def submit_extend():
    form = ExtendForm()

    pulau_entries = db.session.execute(db.select(Pulau).order_by(Pulau.nama)).scalars().all()
    form.pulau.choices = [('', '-- Pilih Pulau --')] + [(p.nama, p.nama) for p in pulau_entries]
    form.kota.choices = [('', '-- Pilih Kota --')] + get_kota_choices(form.pulau.data)
    form.pt.choices = [('', '-- Pilih PT --')] + get_pt_choices(form.kota.data)
    form.unit.choices = [('', '-- Pilih Unit PT --')] + get_unit_choices(form.pt.data, form.kota.data)
    
    if form.pt.data and form.unit.data:
        choices = get_cn_choices(form.unit.data, form.pt.data, form.kota.data)
        form.cn.choices = [('', '-- Pilih Kode Unit --')] + [(label, label) for val, label in choices]
    else:
        form.cn.choices = [('', '-- Pilih Kode Unit --')]

    # Fallback to bypass WTForms strict choice validation errors on cascading fields
    if form.pulau.data and form.pulau.data not in [c[0] for c in form.pulau.choices]:
        form.pulau.choices.append((form.pulau.data, form.pulau.data))
    if form.kota.data and form.kota.data not in [c[0] for c in form.kota.choices]:
        form.kota.choices.append((form.kota.data, form.kota.data))
    if form.pt.data and form.pt.data not in [c[0] for c in form.pt.choices]:
        form.pt.choices.append((form.pt.data, form.pt.data))
    if form.unit.data and form.unit.data not in [c[0] for c in form.unit.choices]:
        form.unit.choices.append((form.unit.data, form.unit.data))
    if form.cn.data and form.cn.data not in [c[0] for c in form.cn.choices]:
        form.cn.choices.append((form.cn.data, form.cn.data))

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

        lokasi_record = db.session.execute(
            db.select(LokasiKerja).where(
                db.func.upper(LokasiKerja.kode_unit) == cn.upper().strip(),
                db.func.upper(LokasiKerja.pulau) == form.pulau.data.upper().strip(),
                db.func.upper(LokasiKerja.kota) == form.kota.data.upper().strip(),
                db.func.upper(LokasiKerja.pt) == form.pt.data.upper().strip(),
                ((db.func.upper(LokasiKerja.owner) == form.unit.data.upper().strip()) |
                 (db.func.upper(LokasiKerja.nama) == form.unit.data.upper().strip()))
            )
        ).scalar_one_or_none()

        if not lokasi_record:
            flash("Data lokasi kerja unit tidak ditemukan!", "danger")
            return render_template('perpanjang.html', form=form)

        entry = db.session.execute(
            db.select(DataEntry).where(
                db.func.upper(DataEntry.kode_unit) == lokasi_record.kode_unit.upper(),
                (db.func.upper(DataEntry.unit) == lokasi_record.owner.upper()) | (db.func.upper(DataEntry.unit) == lokasi_record.nama.upper())
            )
        ).scalar_one_or_none()

        if not entry:
            flash("Data master unit tidak ditemukan!", "danger")
            return render_template('perpanjang.html', form=form)

        pkey = entry.pkey

        try:
            # 1. Update the DataEntry object (asset) with the new expiry date and status
            if jenis == "STNK":
                old_status = entry.status_stnk
                old_tanggal = entry.tanggal_berakhir_stnk
                
                entry.status_stnk = "ON"
                if form.tanggal_berakhir_baru.data:
                    entry.tanggal_berakhir_stnk = form.tanggal_berakhir_baru.data
                
                old_val_str = f"Status: {old_status}, Masa Berlaku: {old_tanggal or '-'}"
                new_val_str = f"Status: ON, Masa Berlaku Baru: {entry.tanggal_berakhir_stnk or '-'}"
            else: # Asuransi
                old_status = entry.status_asuransi
                old_tanggal = entry.tanggal_berakhir_asuransi
                
                entry.status_asuransi = "ON"
                if form.tanggal_berakhir_baru.data:
                    entry.tanggal_berakhir_asuransi = form.tanggal_berakhir_baru.data
                
                old_val_str = f"Status: {old_status}, Masa Berlaku: {old_tanggal or '-'}"
                new_val_str = f"Status: ON, Masa Berlaku Baru: {entry.tanggal_berakhir_asuransi or '-'}"

            # 2. Add ReportEntry record
            new_record = ReportEntry(
                jenis=jenis,
                pkey=pkey,
                jumlah_dibayar=jumlah_dibayar,
                tanggal_bayar=form.tanggal_bayar.data,
                tanggal_berakhir_baru=form.tanggal_berakhir_baru.data if form.tanggal_berakhir_baru.data else None,
                tanggal_input=datetime.today().date(),
                diinput_oleh=session.get('logged_user', 'System')
            )
            db.session.add(new_record)

            # 3. Add Audit Log
            log_extend = AuditLog(
                pkey=pkey,
                aksi="EDIT",
                kolom_diubah=f"Perpanjang {jenis}",
                nilai_lama='-',
                nilai_baru=f"Bayar: Rp {jumlah_dibayar:,.2f}. {new_val_str}".replace(',', 'X').replace('.', ',').replace('X', '.'),
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
    populate_form_choices(form)

    if request.method == 'POST' and request.form.get('status_asuransi') == 'OFF':
        if not form.nama_asuransi.data:
            form.nama_asuransi.data = '-'
        if not form.no_polis.data:
            form.no_polis.data = '-'

    if form.validate_on_submit():
        new_record = DataEntry(
            pulau=form.pulau.data,
            kota=form.kota.data,
            pt=form.pt.data.upper().strip(),
            unit=form.unit.data.upper().strip(),
            kode_unit=form.kode_unit.data.upper().replace(" ", ""),
            pkey=form.pulau.data+"-"+form.kota.data+"-"+form.pt.data.upper().strip()+"-"+form.unit.data.upper().strip()+"-"+form.kode_unit.data.upper().replace(" ", ""),
            lokasi_kerja=form.lokasi_kerja.data.upper().strip() if form.lokasi_kerja.data else None,

            nama_asuransi=form.nama_asuransi.data.upper().strip() if form.nama_asuransi.data else None,
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
            notes=form.notes.data,
            tanggal_input=datetime.today().date(),
            diinput_oleh=session['logged_user']
        )

        loc_nama = form.lokasi_kerja.data.upper().strip() if form.lokasi_kerja.data else ""
        
        loc_unit = db.session.execute(
            db.select(Unit).where(db.func.upper(Unit.nama) == loc_nama.upper())
        ).scalars().first()
        
        pt_name = ""
        kota_name = ""
        pulau_name = ""
        
        if loc_unit:
            pt_obj = db.session.get(PT, loc_unit.reference)
            if pt_obj:
                pt_name = pt_obj.nama
                kota_obj = db.session.get(Kota, pt_obj.reference)
                if kota_obj:
                    kota_name = kota_obj.nama
                    pulau_obj = db.session.get(Pulau, kota_obj.reference)
                    if pulau_obj:
                        pulau_name = pulau_obj.nama

        if not pt_name:
            pt_name = form.pt.data.upper().strip()
        if not kota_name:
            kota_name = form.kota.data.upper().strip()
        if not pulau_name:
            pulau_name = form.pulau.data.upper().strip()

        owner_unit_name = form.unit.data.upper().strip()
        owner_unit = db.session.execute(
            db.select(Unit).where(db.func.upper(Unit.nama) == owner_unit_name.upper())
        ).scalars().first()
        owner_id = owner_unit.id if owner_unit else 1

        cn_val = form.kode_unit.data.upper().replace(" ", "")
        kode_unit_obj = db.session.execute(
            db.select(KodeUnit).where(db.func.upper(KodeUnit.nama) == cn_val.upper())
        ).scalars().first()
        
        if not kode_unit_obj:
            kode_unit_obj = KodeUnit(
                nama=cn_val,
                reference=owner_id,
                dilakukan_oleh=session['logged_user']
            )
            db.session.add(kode_unit_obj)
            db.session.flush()

        new_work_location_record = LokasiKerja(
            kode_unit=form.kode_unit.data,
            owner=form.unit.data,
            nama=loc_nama if loc_nama else None,
            pulau=pulau_name,
            kota=kota_name,
            pt=pt_name,
            dilakukan_oleh=session['logged_user']
        )

        uploaded_photos = request.files.getlist('unit_photos')

        if len(uploaded_photos) > 10:
            flash("⚠️ Gagal! Maksimal foto yang dapat diunggah adalah 10 foto per unit.", "danger")
            return render_template('form.html', form=form)

        print(form.errors)

        try:
            db.session.add(new_record)
            db.session.add(new_work_location_record)

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
        
    if entry.notes and "dimutasi ke" in entry.notes.lower():
        flash("Unit ini sudah pernah dimutasi dan tidak dapat diedit kembali.", "danger")
        return redirect(url_for('details', pkey=pkey))
        
    form = DataForm(obj=entry)
    populate_form_choices(form)

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


    
    return render_template('edit.html', form=form, entry=entry, photo=photo)

@app.route('/delete/<pkey>', methods=['GET'])
def delete(pkey):
    entry = db.session.execute(
        db.select(DataEntry).where(DataEntry.pkey == pkey)
    ).scalar_one_or_none()
    
    if not entry:
        flash("Data unit dengan PKEY tersebut tidak ditemukan.", "danger")
        return redirect(url_for('details'))
        
    if entry.notes and "dimutasi ke" in entry.notes.lower():
        flash("Unit ini sudah pernah dimutasi dan tidak dapat dihapus.", "danger")
        return redirect(url_for('details', pkey=pkey))
    
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
        
    if entry.notes and "dimutasi ke" in entry.notes.lower():
        flash("Unit ini sudah pernah dimutasi dan tidak dapat diperbarui.", "danger")
        return redirect(url_for('details', pkey=pkey))
        
    form = DataForm()
    form.pulau.data = entry.pulau
    form.kota.data = entry.kota
    form.pt.data = entry.pt
    form.unit.data = entry.unit
    populate_form_choices(form)
    form.pkey.data = pkey
    form.status_stnk.data=entry.status_stnk
    form.status_asuransi.data=entry.status_asuransi
    form.tanggal_berakhir_stnk.data=entry.tanggal_berakhir_stnk
    form.tanggal_berakhir_asuransi.data=entry.tanggal_berakhir_asuransi

    if request.method == 'POST' and request.form.get('status_asuransi') == 'OFF':
        form.nama_asuransi.validators = [Optional()]
        form.no_polis.validators = [Optional()]
        if not form.nama_asuransi.data:
            form.nama_asuransi.data = '-'
        if not form.no_polis.data:
            form.no_polis.data = '-'

    if form.validate_on_submit():
        # Resolve Lokasi Kerja's pulau, kota, and pt from the selected lokasi_kerja (nama)
        loc_nama = form.lokasi_kerja.data.upper().strip() if form.lokasi_kerja.data else ""
        
        loc_unit = db.session.execute(
            db.select(Unit).where(db.func.upper(Unit.nama) == loc_nama.upper())
        ).scalars().first()
        
        pt_name = ""
        kota_name = ""
        pulau_name = ""
        
        if loc_unit:
            pt_obj = db.session.get(PT, loc_unit.reference)
            if pt_obj:
                pt_name = pt_obj.nama
                kota_obj = db.session.get(Kota, pt_obj.reference)
                if kota_obj:
                    kota_name = kota_obj.nama
                    pulau_obj = db.session.get(Pulau, kota_obj.reference)
                    if pulau_obj:
                        pulau_name = pulau_obj.nama

        fields_to_check = [
            ('lokasi_kerja', 'Lokasi Kerja', loc_nama if loc_nama else None),
            ('nama_asuransi', 'Nama Asuransi', form.nama_asuransi.data.upper().strip() if form.nama_asuransi.data else None),
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
        entry.lokasi_kerja = loc_nama
        entry.nama_asuransi = form.nama_asuransi.data.upper().strip() if form.nama_asuransi.data else None
        entry.no_polis = form.no_polis.data.upper().strip() if form.no_polis.data else None
        entry.no_polisi = form.no_polisi.data.upper().replace(" ", "") if form.no_polisi.data else None
        entry.merk = form.merk.data.upper().strip() if form.merk.data else None
        entry.kategori = form.kategori.data.upper().strip() if form.kategori.data else None
        entry.eqp_model = form.eqp_model.data.upper().strip() if form.eqp_model.data else None
        entry.sn_equipment = form.sn_equipment.data
        entry.sn_engine = form.sn_engine.data
        entry.year = form.year.data
        
        # Sync / update the LokasiKerja master record for this unit
        lok_rec = db.session.execute(
            db.select(LokasiKerja).where(
                db.func.upper(LokasiKerja.kode_unit) == entry.kode_unit.upper(),
                db.func.upper(LokasiKerja.pulau) == entry.pulau.upper().strip(),
                db.func.upper(LokasiKerja.kota) == entry.kota.upper().strip(),
                db.func.upper(LokasiKerja.pt) == entry.pt.upper().strip(),
                db.func.upper(LokasiKerja.owner) == entry.unit.upper().strip()
            )
        ).scalars().first()
        if lok_rec:
            lok_rec.pulau = pulau_name
            lok_rec.kota = kota_name
            lok_rec.pt = pt_name
            lok_rec.owner = loc_nama
            lok_rec.nama = loc_nama
            lok_rec.dilakukan_oleh = session.get('logged_user', 'System')
            lok_rec.tanggal_aksi = datetime.today()

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

    stmt = db.select(LokasiKerja).where(db.func.upper(LokasiKerja.kode_unit) == pkey.upper())
    if pulau:
        stmt = stmt.where(db.func.upper(LokasiKerja.pulau) == pulau.upper())
    if kota:
        stmt = stmt.where(db.func.upper(LokasiKerja.kota) == kota.upper())
    if pt:
        stmt = stmt.where(db.func.upper(LokasiKerja.pt) == pt.upper())
    if unit:
        unit_upper = unit.upper()
        possible_names = [unit_upper]
        if "-" in unit_upper:
            parts = unit_upper.split("-")
            for i in range(1, len(parts)):
                suffix = "-".join(parts[i:]).strip()
                if suffix:
                    possible_names.append(suffix)
        if pt and unit_upper.startswith(pt.upper() + "-"):
            prefix_len = len(pt) + 1
            stripped_unit = unit_upper[prefix_len:].strip()
            if stripped_unit not in possible_names:
                possible_names.append(stripped_unit)

        stmt = stmt.where(
            (db.func.upper(LokasiKerja.owner).in_(possible_names)) |
            (db.func.upper(LokasiKerja.nama).in_(possible_names))
        )

    lok_record = db.session.execute(stmt).scalar_one_or_none()
    
    if lok_record:
        entry = db.session.execute(
            db.select(DataEntry).where(
                db.func.upper(DataEntry.kode_unit) == lok_record.kode_unit.upper(),
                (db.func.upper(DataEntry.unit) == lok_record.owner.upper()) | (db.func.upper(DataEntry.unit) == lok_record.nama.upper())
            )
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
    kota = request.args.get('kota')
    choices = get_unit_choices(pt, kota)
    return jsonify([{'value': val, 'label': label} for val, label in choices])

@app.route('/api/get-cn/<unit>')
def get_cn_api(unit):
    pt = request.args.get('pt')
    kota = request.args.get('kota')
    source = request.args.get('source')
    if source == 'asset':
        choices = get_cn_choices_asset(unit, pt, kota)
    else:
        choices = get_cn_choices(unit, pt, kota)
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
        # 1. Ambil data dari database dengan filter pencarian jika ada
        search_query = request.args.get('search', '').strip()
        pulau_filter = request.args.get('pulau', '').strip()
        kota_filter = request.args.get('kota', '').strip()
        pt_filter = request.args.get('pt', '').strip()
        unit_filter = request.args.get('unit', '').strip()
        lokasi_kerja_filter = request.args.get('lokasi_kerja', '').strip()
        asuransi_filter = request.args.get('nama_asuransi', '').strip()
        merk_filter = request.args.get('merk', '').strip()
        kategori_filter = request.args.get('kategori', '').strip()
        model_filter = request.args.get('eqp_model', '').strip()
        
        groupby = request.args.get('groupby', '').strip()
        groupval = request.args.get('groupval', '').strip()
        sort_by = request.args.get('sortby', 'id_desc').strip()
        
        query = db.select(DataEntry)
        
        # Apply filters
        if search_query:
            search_pattern = f"%{search_query}%"
            query = query.where(
                DataEntry.pulau.ilike(search_pattern) |
                DataEntry.kota.ilike(search_pattern) |
                DataEntry.pt.ilike(search_pattern) |
                DataEntry.unit.ilike(search_pattern) |
                DataEntry.kode_unit.ilike(search_pattern) |
                DataEntry.nama_asuransi.ilike(search_pattern) |
                DataEntry.no_polis.ilike(search_pattern) |
                DataEntry.no_polisi.ilike(search_pattern) |
                DataEntry.merk.ilike(search_pattern) |
                DataEntry.kategori.ilike(search_pattern) |
                DataEntry.eqp_model.ilike(search_pattern)
            )
        if pulau_filter:
            query = query.where(db.func.upper(DataEntry.pulau) == pulau_filter.upper())
        if kota_filter:
            query = query.where(db.func.upper(DataEntry.kota) == kota_filter.upper())
        if pt_filter:
            query = query.where(db.func.upper(DataEntry.pt) == pt_filter.upper())
        if unit_filter:
            query = query.where(
                (db.func.upper(DataEntry.unit) == unit_filter.upper()) | 
                (DataEntry.unit.like(f"%{unit_filter}%"))
            )
        if asuransi_filter:
            query = query.where(db.func.upper(DataEntry.nama_asuransi) == asuransi_filter.upper())
        if merk_filter:
            query = query.where(db.func.upper(DataEntry.merk) == merk_filter.upper())
        if kategori_filter:
            query = query.where(db.func.upper(DataEntry.kategori) == kategori_filter.upper())
        if model_filter:
            query = query.where(db.func.upper(DataEntry.eqp_model) == model_filter.upper())
        if lokasi_kerja_filter:
            query = query.where(db.func.upper(DataEntry.lokasi_kerja) == lokasi_kerja_filter.upper())
            
        # Apply group filtering
        if groupby and groupval and groupby != 'ALL':
            query = query.where(db.func.upper(getattr(DataEntry, groupby)) == groupval.upper())
            
        # Apply sorting
        if sort_by == 'pulau':
            query = query.order_by(DataEntry.pulau.asc())
        elif sort_by == 'kota':
            query = query.order_by(DataEntry.kota.asc())
        elif sort_by == 'pt':
            query = query.order_by(DataEntry.pt.asc())
        elif sort_by == 'unit':
            query = query.order_by(DataEntry.unit.asc())
        elif sort_by == 'lokasi_kerja':
            query = query.order_by(DataEntry.lokasi_kerja.asc())
        elif sort_by == 'nama_asuransi':
            query = query.order_by(DataEntry.nama_asuransi.asc())
        elif sort_by == 'merk':
            query = query.order_by(DataEntry.merk.asc())
        elif sort_by == 'kategori':
            query = query.order_by(DataEntry.kategori.asc())
        elif sort_by == 'eqp_model':
            query = query.order_by(DataEntry.eqp_model.asc())
        else: # id_desc
            query = query.order_by(DataEntry.id.desc())
            
        all_entries = db.session.execute(query).scalars().all()
        
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
                idx, entry.pt, entry.nama_asuransi, entry.pulau, entry.kota, entry.pkey,
                entry.no_polis, entry.no_polisi, entry.merk, entry.kategori, entry.eqp_model,
                entry.sn_equipment, entry.sn_engine, entry.status_stnk, 
                entry.tanggal_berakhir_stnk if entry.tanggal_berakhir_stnk else '-',
                entry.status_asuransi,
                entry.tanggal_berakhir_asuransi if entry.tanggal_berakhir_asuransi else '-',
                entry.year,
                entry.notes if entry.notes else '-',
                entry.diinput_oleh, entry.tanggal_input if entry.tanggal_input else '-'
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
                elif 20 <= col_num <= 27: # Total
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
    today = datetime.today().date()
    hari_ini_str = today.strftime('%Y-%m-%d')
    threshold_date = (today + timedelta(days=90)).strftime('%Y-%m-%d')
    
    all_entries = db.session.execute(db.select(DataEntry)).scalars().all()
    
    updated = False
    for entry in all_entries:
        # Check STNK status and billing
        if entry.tanggal_berakhir_stnk:
            if entry.tanggal_berakhir_stnk <= threshold_date:
                # Load bill 90 days before expiration if currently 0
                if entry.harus_dibayar_stnk == 0.0 and entry.total_stnk > 0:
                    entry.harus_dibayar_stnk = entry.total_stnk
                    updated = True
                
                # Update status based on actual expiration
                if entry.tanggal_berakhir_stnk > hari_ini_str:
                    if entry.status_stnk != 'ON':
                        entry.status_stnk = 'ON'
                        updated = True
                else:
                    if entry.status_stnk != 'OFF':
                        entry.status_stnk = 'OFF'
                        updated = True
            else:
                if entry.status_stnk != 'ON':
                    entry.status_stnk = 'ON'
                    updated = True
        else:
            if entry.status_stnk != 'OFF':
                entry.status_stnk = 'OFF'
                updated = True
                
        # Check Asuransi status and billing
        if entry.tanggal_berakhir_asuransi:
            if entry.tanggal_berakhir_asuransi <= threshold_date:
                # Load bill 90 days before expiration if currently 0
                if entry.harus_dibayar_asuransi == 0.0 and entry.total_asuransi > 0:
                    entry.harus_dibayar_asuransi = entry.total_asuransi
                    updated = True
                
                # Update status based on actual expiration
                if entry.tanggal_berakhir_asuransi > hari_ini_str:
                    if entry.status_asuransi != 'ON':
                        entry.status_asuransi = 'ON'
                        updated = True
                else:
                    if entry.status_asuransi != 'OFF':
                        entry.status_asuransi = 'OFF'
                        updated = True
            else:
                if entry.status_asuransi != 'ON':
                    entry.status_asuransi = 'ON'
                    updated = True
        else:
            if entry.status_asuransi != 'OFF':
                entry.status_asuransi = 'OFF'
                updated = True
                
    if updated:
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)