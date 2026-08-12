# ===============================================================================================================
# IMPORT AND SETUP
# ===============================================================================================================

import sys
if __name__ == '__main__':
    sys.modules['app'] = sys.modules['__main__']

from flask import Flask, render_template, request, redirect, url_for, Response, flash, session, send_file, send_from_directory
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
from datetime import datetime, timedelta, time
from collections import defaultdict
from werkzeug.security import check_password_hash, generate_password_hash
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from PIL import Image, ImageOps

import csv
import io
import zipfile
import zlib
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
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

csrf = CSRFProtect(app)

# ===============================================================================================================
# VARIABLES AND CONFIGURATION
# ===============================================================================================================

class Base(DeclarativeBase):
    pass

def decompress_data(data):
    if not data:
        return data
    try:
        return zlib.decompress(data)
    except zlib.error:
        return data

def compress_image_pil(binary_data, max_dimension=1600, quality=75):
    if not binary_data:
        return binary_data
    try:
        img = Image.open(io.BytesIO(binary_data))
        
        # Auto-rotate image based on EXIF orientation tag
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
            
        # Convert to RGB (required for saving transparent images to JPEG)
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # Resize if dimensions exceed max_dimension
        width, height = img.size
        if width > max_dimension or height > max_dimension:
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
        # Save to bytes in JPEG format with quality compression
        output_bytes = io.BytesIO()
        img.save(output_bytes, format='JPEG', quality=quality, optimize=True)
        return output_bytes.getvalue()
    except Exception:
        return binary_data

RAW_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "hris_db")
DB_HOST = os.getenv("DB_HOST", "localhost")

CATEGORIES = [
    'no_mesin', 'no_rangka', 
    'bpkb_1', 'bpkb_2',
    'tampak_depan', 'tampak_belakang', 'tampak_kiri', 'tampak_kanan',
    'lainnya_1', 'lainnya_2', 'lainnya_3', 'lainnya_4'
]

if RAW_PASSWORD:
    DB_PASSWORD = urllib.parse.quote_plus(RAW_PASSWORD)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"postgresql://postgres:{DB_PASSWORD}@{DB_HOST}:5432/{DB_NAME}"

@app.before_request
def batasi_akses_global():
    if request.path == '/login' or request.path == '/':
        return None 
        
    if 'logged_in' not in session:
        flash("Silakan login terlebih dahulu untuk mengakses halaman tersebut.", "warning")
        return redirect(url_for('login'))

    # Define route prefix groups for each module
    sdm_prefixes = [
        '/sdm-dashboard', '/sdm-transaksi', '/master-sdm', '/master-karyawan', 
        '/upload-karyawan', '/hapus-cuti', '/logs-cuti', '/nonaktifkan-karyawan', 
        '/master-cuti', '/tambah-cuti-dinas', '/form-ba', '/generate-laporan', 
        '/master-bulan', '/master-kehadiran', '/users', '/tambah-karyawan', 
        '/upload-kehadiran', '/atur-libur', '/edit-kehadiran', '/master-jam-kerja', 
        '/simulasi-tanggal', '/master-jabatan', '/master-sdm-pt', '/import-karyawan',
        '/master-sdm-divisi', '/master-sdm-departemen'
    ]
    
    aset_prefixes = [
        '/aset-dashboard', '/transaksi', '/entry', '/perpanjang', '/mutasi', 
        '/report', '/details', '/master-all', '/master-lokasi-kerja', 
        '/master-pulau', '/master-kota', '/master-pt', '/master-unit', 
        '/master-asuransi', '/master-merk', '/master-kategori', '/master/', 
        '/edit/', '/delete/', '/update/', '/submit_data', '/logs-aset'
    ]
    # /master exact route belongs to aset (landing page)
    aset_exact = ['/master']

    user_role = session.get('role')
    path = request.path

    # Public utility paths are always allowed
    if path in ['/logout', '/select-module', '/cek-cuti'] or path.startswith('/static/') or path.startswith('/temp_uploads/'):
        pass
    else:
        # Check SDM Module Access
        is_sdm_route = any(path.startswith(prefix) for prefix in sdm_prefixes)
        if is_sdm_route:
            # Staff Operasional cannot access SDM module at all
            if user_role in ['operasional', 'user']:
                flash("⚠️ Akses Ditolak: Peran Anda tidak memiliki izin untuk mengakses Modul SDM.", "danger")
                return redirect(url_for('select_module'))
                
            # Staff HR cannot access user management
            if user_role == 'hr':
                if path.startswith('/users'):
                    flash("⚠️ Akses Ditolak: Staff SDM tidak diizinkan mengakses Manajemen User.", "danger")
                    return redirect(url_for('sdm_dashboard'))

        # Check Aset Module Access
        is_aset_route = path in aset_exact or any(path.startswith(prefix) for prefix in aset_prefixes)
        if is_aset_route:
            # Staff HR and User cannot access Aset module
            if user_role in ['hr', 'user']:
                flash("⚠️ Akses Ditolak: Peran Anda tidak memiliki izin untuk mengakses Modul Aset.", "danger")
                return redirect(url_for('select_module'))

    # Auto-detect active module based on URL path for navigation state
    if request.path.startswith('/sdm') or any(request.path.startswith(prefix) for prefix in sdm_prefixes):
        session['module'] = 'sdm'
    elif path in aset_exact or any(request.path.startswith(prefix) for prefix in aset_prefixes):
        session['module'] = 'aset'

def cleanup_temp_uploads():
    import os
    import time
    temp_dir = os.path.join(app.root_path, 'temp_uploads')
    if os.path.exists(temp_dir):
        now = time.time()
        for f in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, f)
            if os.path.isfile(file_path):
                # 86400 seconds = 24 hours
                if os.stat(file_path).st_mtime < now - 86400:
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        print(f"Error removing temp file {file_path}: {e}")

# ===============================================================================================================
# DATABASE INITIALIZATION
# ===============================================================================================================

db = SQLAlchemy(model_class=Base)
db.init_app(app)

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

    @property
    def pkey(self):
        entry = db.session.execute(
            db.select(DataEntry.pkey).where(
                db.func.upper(DataEntry.kode_unit) == self.kode_unit.upper(),
                db.func.upper(DataEntry.unit) == self.owner.upper(),
                (DataEntry.notes == None) | (
                    (~DataEntry.notes.ilike('%Dimutasi ke%')) &
                    (~DataEntry.notes.ilike('%Dihapus%'))
                )
            )
        ).scalars().first()
        return entry or ""

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


class Jabatan(db.Model):
    __tablename__ = 'jabatan'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=True)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class SdmPT(db.Model):
    __tablename__ = 'sdm_pt'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=True)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class SdmDivisi(db.Model):
    __tablename__ = 'sdm_divisi'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=True)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class SdmDepartemen(db.Model):
    __tablename__ = 'sdm_departemen'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=True)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class UserEntry(db.Model):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nik: Mapped[str] = mapped_column(db.String(50), nullable=True)
    username: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(db.String(255), nullable=False)
    role: Mapped[str] = mapped_column(db.String(20))

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    pkey: Mapped[str] = mapped_column(db.String(150), nullable=False, index=True) 
    aksi: Mapped[str] = mapped_column(db.String(20), nullable=False) 
    kolom_diubah: Mapped[str] = mapped_column(db.Text, nullable=True) 
    nilai_lama: Mapped[str] = mapped_column(db.Text, nullable=True) 
    nilai_baru: Mapped[str] = mapped_column(db.Text, nullable=True) 
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class UnitImage(db.Model):
    __tablename__ = 'images'
    
    id = db.mapped_column(db.Integer, primary_key=True, autoincrement=True)
    pkey = db.mapped_column(db.String(150), db.ForeignKey('data_entries.pkey'), nullable=False, index=True) # Hubungkan dengan CN Utama
    filename = db.mapped_column(db.String(255), nullable=False)     # Menyimpan nama asli file (misal: depan.jpg)
    file_data = db.mapped_column(db.LargeBinary, nullable=False)    # Menyimpan data biner gambar asli (BLOB/BYTEA)
    category = db.mapped_column(db.String(50), nullable=True)       # Kategori/tipe foto (misal: no_mesin, no_rangka, dll)

class DocumentSurat(db.Model):
    __tablename__ = 'document_surat'
    
    id = db.mapped_column(db.Integer, primary_key=True, autoincrement=True)
    pkey = db.mapped_column(db.String(150), db.ForeignKey('data_entries.pkey'), nullable=False, index=True)
    filename = db.mapped_column(db.String(255), nullable=False)
    file_data = db.mapped_column(db.LargeBinary, nullable=False)
    jenis = db.mapped_column(db.String(20), nullable=False) # 'STNK' atau 'Asuransi'
    status_aktif = db.mapped_column(db.Boolean, default=True, nullable=False)
    tanggal_input = db.mapped_column(db.DateTime, default=datetime.now, nullable=False)

class DataEntry(db.Model):
    __tablename__ = "data_entries"
    
    #Primary
    id: Mapped[int] = mapped_column(Integer, Sequence("id"), unique=True, nullable=False)
    pulau: Mapped[str] = mapped_column(nullable=False)
    kota: Mapped[str] = mapped_column(nullable=False)
    pt: Mapped[str] = mapped_column(nullable=False)
    unit: Mapped[str] = mapped_column(nullable=False)
    kode_unit: Mapped[str] = mapped_column(nullable=False, index=True)
    pkey: Mapped[str] = mapped_column(primary_key=True, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="ON")
    lokasi_kerja: Mapped[str] = mapped_column(nullable=False)

    #Details
    nama_asuransi: Mapped[str] = mapped_column(nullable=True)
    no_polis: Mapped[str] = mapped_column(nullable=True)
    no_polisi: Mapped[str] = mapped_column(nullable=False, index=True)
    merk: Mapped[str] = mapped_column(nullable=False)
    kategori: Mapped[str] = mapped_column(nullable=False)
    eqp_model: Mapped[str] = mapped_column(nullable=False)
    sn_equipment: Mapped[str] = mapped_column(nullable=False, index=True)
    sn_engine: Mapped[str] = mapped_column(nullable=False, index=True)
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

class KaryawanEntry(db.Model):
    __tablename__ = "karyawan_entries"
    
    id: Mapped[int] = mapped_column(Integer, Sequence("id"), unique=True, nullable=False)
    absen: Mapped[int] = mapped_column(unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(nullable=False)
    nik: Mapped[str] = mapped_column(primary_key=True, nullable=False)
    jabatan: Mapped[str] = mapped_column(nullable=False)
    tmk: Mapped[str] = mapped_column(nullable=False)
    jam_masuk: Mapped[time] = mapped_column(db.Time, nullable=False)
    jam_pulang: Mapped[time] = mapped_column(db.Time, nullable=False)
    tanggal_resign: Mapped[str] = mapped_column(db.String(50), nullable=True)
    pt: Mapped[str] = mapped_column(db.String(100), nullable=True)
    staff: Mapped[str] = mapped_column(db.String(20), nullable=True)
    divisi: Mapped[str] = mapped_column(db.String(100), nullable=True)
    departemen: Mapped[str] = mapped_column(db.String(100), nullable=True)
    priority_level: Mapped[int] = mapped_column(db.Integer, nullable=True)
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=True)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

class Cuti(db.Model):
    __tablename__ = "cuti"
    
    id: Mapped[int] = mapped_column(Integer, Sequence("id"), unique=True, nullable=False)
    nik: Mapped[str] = mapped_column(db.ForeignKey('karyawan_entries.nik'), primary_key=True, nullable=False)
    cuti_tahunan: Mapped[float] = mapped_column(db.Float, default=0.0, nullable=False)
    cuti_dinas: Mapped[float] = mapped_column(db.Float, default=0.0, nullable=False)
    cuti_dinas_period: Mapped[str] = mapped_column(db.String(50), nullable=True)
    
    karyawan: Mapped["KaryawanEntry"] = db.relationship("KaryawanEntry")

    @property
    def nama(self):
        return self.karyawan.nama if self.karyawan else ""

class CutiManual(db.Model):
    __tablename__ = "cuti_manual"
    
    id: Mapped[int] = mapped_column(Integer, Sequence("cuti_manual_id"), unique=True, primary_key=True, nullable=False)
    nik: Mapped[str] = mapped_column(db.ForeignKey('karyawan_entries.nik'), nullable=False)
    tanggal_input: Mapped[str] = mapped_column(db.String(50), nullable=False)
    jumlah: Mapped[float] = mapped_column(db.Float, nullable=False)
    tipe: Mapped[str] = mapped_column(db.String(10), nullable=False) # 'CT', 'CD', 'HANGUS'
    keterangan: Mapped[str] = mapped_column(db.String(255), nullable=True)
    tanggal_kadaluarsa: Mapped[str] = mapped_column(db.String(50), nullable=True)
    ba_nomor: Mapped[str] = mapped_column(db.String(100), nullable=True)
    ba_tanggal: Mapped[str] = mapped_column(db.String(50), nullable=True)
    ba_keterangan: Mapped[str] = mapped_column(db.String(255), nullable=True)
    
    karyawan: Mapped["KaryawanEntry"] = db.relationship("KaryawanEntry")

    @property
    def nama(self):
        return self.karyawan.nama if self.karyawan else ""

class Bulan(db.Model):
    __tablename__ = "bulan"
    nama: Mapped[str] = mapped_column(db.String(50), primary_key=True, nullable=False)
    jumlah_hari: Mapped[int] = mapped_column(db.Integer, nullable=False)

class HariLibur(db.Model):
    __tablename__ = "hari_libur"
    
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    tanggal: Mapped[datetime.date] = mapped_column(db.Date, unique=True, nullable=False)
    keterangan: Mapped[str] = mapped_column(db.String(150), nullable=False)

class Kehadiran(db.Model):
    __tablename__ = "kehadiran"
    
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    nik: Mapped[str] = mapped_column(db.String(50), db.ForeignKey('karyawan_entries.nik'), nullable=False)
    bulan: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tahun: Mapped[int] = mapped_column(db.Integer, nullable=False)
    
    status_hari: Mapped[dict] = mapped_column(db.JSON, default=dict, nullable=False)
    scan_masuk_hari: Mapped[dict] = mapped_column(db.JSON, default=dict, nullable=False)
    scan_pulang_hari: Mapped[dict] = mapped_column(db.JSON, default=dict, nullable=False)
    keterangan_hari: Mapped[dict] = mapped_column(db.JSON, default=dict, nullable=True)
    izin_hari: Mapped[dict] = mapped_column(db.JSON, default=dict, nullable=True)

    # Hubungan dengan KaryawanEntry untuk mendapatkan nama karyawan
    karyawan: Mapped["KaryawanEntry"] = db.relationship("KaryawanEntry")

    @property
    def nama(self):
        return self.karyawan.nama if self.karyawan else ""

class SdmActivityLog(db.Model):
    __tablename__ = 'sdm_activity_logs'
    
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    aksi: Mapped[str] = mapped_column(db.String(50), nullable=False)   # e.g. 'TAMBAH_KARYAWAN', 'RESIGN', 'UPLOAD_KEHADIRAN'
    kategori: Mapped[str] = mapped_column(db.String(50), nullable=False) # e.g. 'KARYAWAN', 'CUTI', 'KEHADIRAN', 'LIBUR'
    nik: Mapped[str] = mapped_column(db.String(50), nullable=True)       # NIK yang terlibat (bisa null untuk bulk)
    nama_karyawan: Mapped[str] = mapped_column(db.String(150), nullable=True)
    detail: Mapped[str] = mapped_column(db.Text, nullable=True)          # Deskripsi lengkap aksi
    dilakukan_oleh: Mapped[str] = mapped_column(db.String(50), nullable=False)
    tanggal_aksi: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.now)

# ===============================================================================================================
# ROUTING
# ===============================================================================================================

# Import the modules to register their models and routes directly on app
import aset
import sdm

with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text
        from werkzeug.security import generate_password_hash
        user_count = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        if user_count == 0:
            hashed_pw = generate_password_hash("admin123")
            db.session.execute(
                text("INSERT INTO users (username, password, role) VALUES (:username, :password, :role)"),
                {"username": "admin", "password": hashed_pw, "role": "admin"}
            )
            db.session.commit()
            print("Default admin user created (username: admin, password: admin123).")
    except Exception as e:
        db.session.rollback()
        print(f"Error seeding default user: {e}")
        
    try:
        from sqlalchemy import text
        # Check if 'category' column exists in 'images' table, if not, add it
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='images' AND column_name='category'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE images ADD COLUMN category VARCHAR(50)"))
            db.session.commit()
            print("Successfully added category column to images table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding category column: {e}")
        
    try:
        from sqlalchemy import text
        # Check if 'cuti_dinas_period' column exists in 'cuti' table for PostgreSQL
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='cuti' AND column_name='cuti_dinas_period'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE cuti ADD COLUMN cuti_dinas_period VARCHAR(50)"))
            db.session.commit()
            print("Successfully added cuti_dinas_period column to cuti table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding cuti_dinas_period column: {e}")
        
    try:
        from sqlalchemy import text
        # Check if 'tanggal_kadaluarsa' column exists in 'cuti_manual' table for PostgreSQL
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='cuti_manual' AND column_name='tanggal_kadaluarsa'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE cuti_manual ADD COLUMN tanggal_kadaluarsa VARCHAR(50)"))
            db.session.commit()
            print("Successfully added tanggal_kadaluarsa column to cuti_manual table.")
            
        # Check if 'ba_nomor' column exists
        result_ba = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='cuti_manual' AND column_name='ba_nomor'"
        )).fetchone()
        if not result_ba:
            db.session.execute(text("ALTER TABLE cuti_manual ADD COLUMN ba_nomor VARCHAR(100)"))
            db.session.execute(text("ALTER TABLE cuti_manual ADD COLUMN ba_tanggal VARCHAR(50)"))
            db.session.execute(text("ALTER TABLE cuti_manual ADD COLUMN ba_keterangan VARCHAR(255)"))
            db.session.commit()
            print("Successfully added ba_nomor, ba_tanggal, and ba_keterangan columns to cuti_manual table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding cuti_manual columns: {e}")
        
    try:
        # Check if 'nik' column exists in 'users' table, if not, add it
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='nik'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE users ADD COLUMN nik VARCHAR(50)"))
            db.session.commit()
            print("Successfully added nik column to users table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding nik column to users: {e}")

    try:
        # Check if 'pt' column exists in 'karyawan_entries' table, if not, add it
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='karyawan_entries' AND column_name='pt'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE karyawan_entries ADD COLUMN pt VARCHAR(100)"))
            db.session.commit()
            print("Successfully added pt column to karyawan_entries table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding pt column to karyawan_entries: {e}")

    try:
        # Check if 'staff' column exists in 'karyawan_entries' table, if not, add it
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='karyawan_entries' AND column_name='staff'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE karyawan_entries ADD COLUMN staff VARCHAR(20) DEFAULT 'Staff'"))
            db.session.commit()
            print("Successfully added staff column to karyawan_entries table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding staff column to karyawan_entries: {e}")

    try:
        # Check if 'divisi' column exists in 'karyawan_entries' table, if not, add it
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='karyawan_entries' AND column_name='divisi'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE karyawan_entries ADD COLUMN divisi VARCHAR(100)"))
            db.session.commit()
            print("Successfully added divisi column to karyawan_entries table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding divisi column to karyawan_entries: {e}")

    try:
        # Check if 'departemen' column exists in 'karyawan_entries' table, if not, add it
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='karyawan_entries' AND column_name='departemen'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE karyawan_entries ADD COLUMN departemen VARCHAR(100)"))
            db.session.commit()
            print("Successfully added departemen column to karyawan_entries table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding departemen column to karyawan_entries: {e}")

    try:
        # Check if 'priority_level' column exists in 'karyawan_entries' table, if not, add it
        result = db.session.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='karyawan_entries' AND column_name='priority_level'"
        )).fetchone()
        if not result:
            db.session.execute(text("ALTER TABLE karyawan_entries ADD COLUMN priority_level INTEGER"))
            db.session.commit()
            print("Successfully added priority_level column to karyawan_entries table.")
        elif 'integer' not in result[1].lower():
            db.session.execute(text("ALTER TABLE karyawan_entries ALTER COLUMN priority_level TYPE INTEGER USING (CASE WHEN priority_level = 'High' THEN 1 WHEN priority_level = 'Medium' THEN 2 WHEN priority_level = 'Low' THEN 3 ELSE NULL END)"))
            db.session.commit()
            print("Successfully altered priority_level column type to INTEGER.")
    except Exception as e:
        db.session.rollback()
        print(f"Error checking/adding/altering priority_level column: {e}")

    # Migrasi auditing fields untuk tabel jabatan
    try:
        # dilakukan_oleh
        res = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='jabatan' AND column_name='dilakukan_oleh'"
        )).fetchone()
        if not res:
            db.session.execute(text("ALTER TABLE jabatan ADD COLUMN dilakukan_oleh VARCHAR(50)"))
            db.session.commit()
            print("Successfully added dilakukan_oleh column to jabatan table.")
        # tanggal_aksi
        res2 = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='jabatan' AND column_name='tanggal_aksi'"
        )).fetchone()
        if not res2:
            db.session.execute(text("ALTER TABLE jabatan ADD COLUMN tanggal_aksi TIMESTAMP DEFAULT NOW()"))
            db.session.commit()
            print("Successfully added tanggal_aksi column to jabatan table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error migrating auditing columns in jabatan table: {e}")

    # Migrasi auditing fields untuk tabel karyawan_entries
    try:
        # dilakukan_oleh
        res = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='karyawan_entries' AND column_name='dilakukan_oleh'"
        )).fetchone()
        if not res:
            db.session.execute(text("ALTER TABLE karyawan_entries ADD COLUMN dilakukan_oleh VARCHAR(50)"))
            db.session.commit()
            print("Successfully added dilakukan_oleh column to karyawan_entries table.")
        # tanggal_aksi
        res2 = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='karyawan_entries' AND column_name='tanggal_aksi'"
        )).fetchone()
        if not res2:
            db.session.execute(text("ALTER TABLE karyawan_entries ADD COLUMN tanggal_aksi TIMESTAMP DEFAULT NOW()"))
            db.session.commit()
            print("Successfully added tanggal_aksi column to karyawan_entries table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error migrating auditing columns in karyawan_entries table: {e}")

    try:
        # Pindahkan data jabatan unik dari karyawan ke tabel jabatan jika tabel jabatan kosong
        res = db.session.execute(text("SELECT COUNT(*) FROM jabatan")).fetchone()
        if res and res[0] == 0:
            karyawan_jabs = db.session.execute(text("SELECT DISTINCT jabatan FROM karyawan_entries")).fetchall()
            for row in karyawan_jabs:
                if row[0]:
                    # Cek case-insensitive duplicate sebelum insert
                    exist = db.session.execute(text("SELECT id FROM jabatan WHERE LOWER(nama) = LOWER(:nama)"), {"nama": row[0].strip()}).fetchone()
                    if not exist:
                        db.session.execute(text("INSERT INTO jabatan (nama) VALUES (:nama)"), {"nama": row[0].strip()})
            db.session.commit()
            print("Successfully migrated existing jabatans to jabatan table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error migrating jabatans: {e}")

    try:
        cleanup_temp_uploads()
        print("Successfully cleaned up old temporary uploads.")
    except Exception as e:
        print(f"Error cleaning temp uploads: {e}")

@app.route('/')
def index():
    return redirect(url_for('login'))

# User management routes shifted to sdm.py

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'logged_in' in session:
        return redirect(url_for('select_module'))

    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password')
        
        # Coba login dengan username terlebih dahulu
        query = text("SELECT id, username, password, role FROM users WHERE username = :val")
        result = db.session.execute(query, {"val": identifier}).fetchone()
        
        # Jika tidak ditemukan via username, coba via NIK (untuk role user)
        if not result:
            query_nik = text("SELECT id, username, password, role FROM users WHERE nik = :val")
            result = db.session.execute(query_nik, {"val": identifier.upper()}).fetchone()
        
        if result and check_password_hash(result.password, password):
            # Regenerasi session ID baru untuk mencegah Session Fixation Attack
            session.clear()
            
            # Set cookie session aman
            session['logged_in'] = True
            session['result_id'] = result.id
            session['logged_user'] = result.username
            session['role'] = result.role
            
            return redirect(url_for('select_module'))
        else:
            flash("Username / NIK atau Password salah!", "danger")
        
    return render_template('login.html')

@app.route('/select-module')
def select_module():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    return render_template('select_module.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/temp_uploads/<filename>')
def serve_temp_file(filename):
    import os
    return send_from_directory(os.path.join(app.root_path, 'temp_uploads'), filename)

@app.route('/logs-aset')
def view_asset_audit_logs():
    # 1. Pastikan user sudah login
    if 'logged_user' not in session:
        return redirect(url_for('login'))
    
    # 2. Batasi akses: Hanya user dengan role 'admin' yang boleh masuk
    if session.get('role') != 'admin':
        flash("⚠️ Anda tidak memiliki izin (Akses Ditolak) untuk membuka halaman Jejak Audit.", "danger")
        return redirect(url_for('aset_dashboard'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    q = request.args.get('q', '').strip()
    
    stmt = db.select(AuditLog)
    if q:
        search_filter = f"%{q}%"
        stmt = stmt.where(
            or_(
                AuditLog.pkey.ilike(search_filter),
                AuditLog.aksi.ilike(search_filter),
                AuditLog.kolom_diubah.ilike(search_filter),
                AuditLog.nilai_lama.ilike(search_filter),
                AuditLog.nilai_baru.ilike(search_filter),
                AuditLog.dilakukan_oleh.ilike(search_filter)
            )
        )
    
    # Get total count of audit logs
    total_count = db.session.scalar(db.select(db.func.count()).select_from(stmt.subquery())) or 0
    
    # 3. Ambil data logs dengan limit dan offset (paginasi)
    all_logs = db.session.execute(
        stmt.order_by(AuditLog.tanggal_aksi.desc())
        .limit(per_page)
        .offset(offset)
    ).scalars().all()
    
    for log in all_logs:
        if log.pkey:
            parts = log.pkey.split('-')
            if len(parts) >= 3:
                log.unit = parts[-3] + '-' + parts[-2]
                log.cn = parts[-1]
            else:
                log.unit = log.pkey
                log.cn = log.pkey
        else:
            log.unit = '-'
            log.cn = '-'

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    # 4. Tampilkan ke template dengan parameter paginasi
    return render_template(
        'aset/logs.html', 
        logs=all_logs, 
        page=page, 
        total_pages=total_pages, 
        total_count=total_count, 
        q=q,
        active_page='logs-aset'
    )

# Modules are imported above database initialization to ensure models register before db.create_all()

if __name__ == '__main__':
    # app.run(debug=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
