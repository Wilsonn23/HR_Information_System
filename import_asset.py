"""
Script to import equipment data from an Excel file into the application's database.

Usage:
	python import_asset.py data.xlsx [--dry-run] [--update]

The script will map common column names from the spreadsheet
to the `DataEntry` model fields, auto-register master tables
(Pulau, Kota, PT, Unit, NamaAsuransi, Merk, Kategori, LokasiKerja),
and insert/update entries in the database.
"""

import sys
import argparse
from datetime import datetime, date
import os
import re

import pandas as pd

from app import (
	app, db, DataEntry, Pulau, Kota, PT, Unit,
	NamaAsuransi, Merk, Kategori, LokasiKerja, KodeUnit
)


COMMON_MAP = {
	# common spreadsheet headers -> DataEntry attribute
	'pulau': 'pulau',
	'kota': 'kota',
	'pt': 'pt',
	'perusahaan': 'pt',
	'unit': 'unit',
	'kode_unit': 'kode_unit',
	'kode unit': 'kode_unit',
	'cn': 'kode_unit',
	'code unit': 'kode_unit',
	'pkey': 'pkey',
	'lokasi_kerja': 'lokasi_kerja',
	'lokasi kerja': 'lokasi_kerja',
	'lokasi': 'lokasi_kerja',
	'site': 'lokasi_kerja',
	'nama_asuransi': 'nama_asuransi',
	'nama_2026': 'nama_asuransi',
	'nama asuransi': 'nama_asuransi',
	'asuransi': 'nama_asuransi',
	'perusahaan asuransi': 'nama_asuransi',
	'no_polis': 'no_polis',
	'no polis': 'no_polis',
	'nomor polis': 'no_polis',
	'polis': 'no_polis',
	'no_polis_2026': 'no_polis',
	'no_polisi': 'no_polisi',
	'no polisi': 'no_polisi',
	'nomor polisi': 'no_polisi',
	'nopol': 'no_polisi',
	'plat': 'no_polisi',
	'plat nomor': 'no_polisi',
	'no plat': 'no_polisi',
	'akhir_2026': 'tanggal_berakhir_asuransi',
	'akhir 2026': 'tanggal_berakhir_asuransi',
	'stnk': 'tanggal_berakhir_stnk',
	'tgl stnk': 'tanggal_berakhir_stnk',
	'pajak stnk': 'tanggal_berakhir_stnk',
	'jatuh tempo stnk': 'tanggal_berakhir_stnk',
	'exp stnk': 'tanggal_berakhir_stnk',
	'expired stnk': 'tanggal_berakhir_stnk',
	'berakhir stnk': 'tanggal_berakhir_stnk',
	'merk': 'merk',
	'brand': 'merk',
	'kategori': 'kategori',
	'category': 'kategori',
	'jenis': 'kategori',
	'eqp_model': 'eqp_model',
	'eqp model': 'eqp_model',
	'model': 'eqp_model',
	'tipe': 'eqp_model',
	'type': 'eqp_model',
	'sn_equipment': 'sn_equipment',
	'sn equipment': 'sn_equipment',
	'sn_eqp': 'sn_equipment',
	'sn eqp': 'sn_equipment',
	'sn_unit': 'sn_equipment',
	'sn unit': 'sn_equipment',
	'serial number': 'sn_equipment',
	'serial no': 'sn_equipment',
	'no rangka': 'sn_equipment',
	'nomor rangka': 'sn_equipment',
	'chassis no': 'sn_equipment',
	'sn_engine': 'sn_engine',
	'sn engine': 'sn_engine',
	'sn mesin': 'sn_engine',
	'sn_mesin': 'sn_engine',
	'no mesin': 'sn_engine',
	'nomor mesin': 'sn_engine',
	'engine no': 'sn_engine',
	'engine number': 'sn_engine',
	'status_stnk': 'status_stnk',
	'status stnk': 'status_stnk',
	'status_asuransi': 'status_asuransi',
	'status asuransi': 'status_asuransi',
	'tanggal_berakhir_stnk': 'tanggal_berakhir_stnk',
	'tgl_berakhir_stnk': 'tanggal_berakhir_stnk',
	'tanggal berakhir stnk': 'tanggal_berakhir_stnk',
	'tanggal_berakhir_asuransi': 'tanggal_berakhir_asuransi',
	'tgl_berakhir_asuransi': 'tanggal_berakhir_asuransi',
	'tanggal berakhir asuransi': 'tanggal_berakhir_asuransi',
	'tgl asuransi': 'tanggal_berakhir_asuransi',
	'jatuh tempo asuransi': 'tanggal_berakhir_asuransi',
	'exp asuransi': 'tanggal_berakhir_asuransi',
	'expired asuransi': 'tanggal_berakhir_asuransi',
	'berakhir asuransi': 'tanggal_berakhir_asuransi',
	'year': 'year',
	'tahun': 'year',
	'thn': 'year',
	'tahun pembuatan': 'year',
	'tahun rakit': 'year',
	'pembulatan_stnk': 'pembulatan_stnk',
	'pembulatan_asuransi': 'pembulatan_asuransi',
	'total_stnk': 'total_stnk',
	'total_asuransi': 'total_asuransi',
	'harus_dibayar_stnk': 'harus_dibayar_stnk',
	'harus_dibayar_asuransi': 'harus_dibayar_asuransi',
	'notes': 'notes',
	'catatan': 'notes',
	'keterangan': 'notes',
	'tanggal_input': 'tanggal_input',
	'diinput_oleh': 'diinput_oleh',
}


def normalize_columns(columns):
	"""Return mapping of normalized col -> original col name."""
	mapping = {}
	for c in columns:
		if not isinstance(c, str):
			continue
		key = c.strip().lower()
		mapping[key] = c
	return mapping


def clean_and_parse_date(val):
	if pd.isna(val) or val is None:
		return None
	# If already a datetime or timestamp
	if hasattr(val, 'strftime'):
		try:
			return val.strftime('%Y-%m-%d')
		except Exception:
			pass
	
	date_str = str(val).strip().upper()
	if date_str in ('NAN', 'NONE', '', 'X', '-'):
		return None

	# YYYY-MM-DD pattern
	if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
		return date_str

	month_map = {
		'JAN': '01', 'JANUARI': '01',
		'FEB': '02', 'FEBRUARI': '02',
		'MAR': '03', 'MARET': '03',
		'APR': '04', 'APRIL': '04',
		'MEI': '05', 'MAY': '05',
		'JUN': '06', 'JUNI': '06',
		'JUL': '07', 'JULI': '07',
		'AGS': '08', 'AGT': '08', 'AGST': '08', 'AGUSTUS': '08', 'AUG': '08', 'AUGUST': '08',
		'SEP': '09', 'SEPT': '09', 'SEPTEMBER': '09',
		'OKT': '10', 'OKTOBER': '10', 'OCT': '10', 'OCTOBER': '10',
		'NOV': '11', 'NOP': '11', 'NOPEMBER': '11', 'NOVEMBER': '11',
		'DES': '12', 'DESEMBER': '12', 'DEC': '12', 'DECEMBER': '12'
	}

	m = re.match(r'^(\d{1,2})[\s\-/\.]*([A-Z]+)[\s\-/\.]*(\d{4})$', date_str)
	if m:
		day_str, mon_str, year_str = m.groups()
		mon_num = month_map.get(mon_str)
		if mon_num:
			return f"{year_str}-{mon_num}-{day_str.zfill(2)}"

	m = re.match(r'^(\d{4})[\s\-/\.]*([A-Z]+)[\s\-/\.]*(\d{1,2})$', date_str)
	if m:
		year_str, mon_str, day_str = m.groups()
		mon_num = month_map.get(mon_str)
		if mon_num:
			return f"{year_str}-{mon_num}-{day_str.zfill(2)}"

	m = re.match(r'^(\d{1,2})[\s\-/\.]+(\d{1,2})[\s\-/\.]+(\d{4})$', date_str)
	if m:
		day_str, mon_str, year_str = m.groups()
		return f"{year_str}-{mon_str.zfill(2)}-{day_str.zfill(2)}"

	m = re.match(r'^(\d{4})[\s\-/\.]+(\d{1,2})[\s\-/\.]+(\d{1,2})$', date_str)
	if m:
		year_str, mon_str, day_str = m.groups()
		return f"{year_str}-{mon_str.zfill(2)}-{day_str.zfill(2)}"

	return None


def map_row_to_entry(row, colmap):
	data = {}
	for norm, dest in COMMON_MAP.items():
		if norm in colmap:
			val = row[colmap[norm]]
			# normalize NaN to None
			if pd.isna(val):
				val = None
			# dates: convert to YYYY-MM-DD strings
			if dest in ('tanggal_berakhir_asuransi', 'tanggal_berakhir_stnk'):
				val = clean_and_parse_date(val)
			elif hasattr(val, 'strftime'):
				try:
					val = val.strftime('%Y-%m-%d')
				except Exception:
					pass
			data[dest] = val

	# After collecting all mapped values, drop only the fields we DO NOT want to load from Excel.
	# We allow `tanggal_berakhir_asuransi` and `tanggal_berakhir_stnk` to be imported,
	# but still avoid copying any explicit status values from the spreadsheet.
	for _k in ('status_stnk', 'status_asuransi'):
		data.pop(_k, None)
	# ensure pkey exists (compose if not provided)
	if not data.get('pkey'):
		# try to build pkey from pulau-kota-unit-kode_unit
		parts = [data.get('pulau') or '', data.get('kota') or '', data.get('unit') or '', data.get('kode_unit') or '']
		# ensure all parts are strings to avoid TypeError when joining
		str_parts = [str(p).strip() for p in parts if p is not None and str(p).strip() != '']
		candidate = '-'.join(str_parts)
		data['pkey'] = candidate if candidate else None

	# cast year to int if possible
	if data.get('year') is not None:
		# handle direct ints
		try:
			data['year'] = int(data['year'])
		except Exception:
			# try to extract first 4-digit year (e.g. '2014 / 2015', '2019 (2018)')
			try:
				ys = str(data['year'])
				m = re.search(r"(19|20)\d{2}", ys)
				if m:
					data['year'] = int(m.group(0))
				else:
					# fallback: take integer part before decimal
					data['year'] = int(ys.split('.')[0]) if ys.split('.')[0].isdigit() else None
			except Exception:
				data['year'] = None

	# numeric fields
	for f in ('pembulatan_stnk', 'pembulatan_asuransi', 'total_stnk', 'total_asuransi', 'harus_dibayar_stnk', 'harus_dibayar_asuransi'):
		if data.get(f) is not None:
			try:
				data[f] = float(data[f])
			except Exception:
				data[f] = None
	# Normalize common string fields (avoid numpy types ending up in SQL params)
	str_fields = ['status_stnk', 'status_asuransi', 'sn_engine', 'sn_equipment', 'no_polisi', 'no_polis', 'nama_asuransi', 'notes', 'lokasi_kerja', 'unit', 'pt', 'pulau', 'kota', 'kode_unit', 'merk', 'kategori', 'eqp_model', 'tanggal_berakhir_stnk', 'tanggal_berakhir_asuransi']
	for f in str_fields:
		if data.get(f) is not None:
			try:
				v = data[f]
				# pandas/numpy scalars may not be plain Python types
				if hasattr(v, 'item'):
					v = v.item()
				# convert to string, uppercase and strip
				v = str(v).strip().upper()
				if f == 'no_polisi':
					v = v.replace(" ", "")
				if v.lower() in ('nan', 'none', '', 'x'):
					data[f] = None
				else:
					data[f] = v
			except Exception:
				data[f] = None

	# Derive insurance/stnk status from a future expiry date.
	for expiry_key, status_key in (('tanggal_berakhir_asuransi', 'status_asuransi'), ('tanggal_berakhir_stnk', 'status_stnk')):
		if data.get(expiry_key):
			try:
				value = data[expiry_key]
				parsed = None
				from datetime import date as _date, datetime as _dt
				if isinstance(value, _dt):
					parsed = value.date()
				elif isinstance(value, _date):
					parsed = value
				elif isinstance(value, str):
					parsed = _dt.strptime(value.strip(), '%Y-%m-%d').date()
				
				if parsed is not None:
					if parsed > _date.today():
						data[status_key] = 'ON'
					else:
						data[status_key] = 'OFF'
			except Exception:
				pass

	# Defaults for NOT NULL fields in DataEntry
	if not data.get('status_stnk'):
		data['status_stnk'] = 'OFF'
	if not data.get('status_asuransi'):
		data['status_asuransi'] = 'OFF'
	if not data.get('sn_engine'):
		data['sn_engine'] = '-'

	# Ensure required non-null fields have safe defaults
	if not data.get('no_polisi'):
		data['no_polisi'] = '-'

	# If status_asuransi accidentally contains a year/date numeric value, replace with default
	if data.get('status_asuransi'):
		if re.search(r'\d', data['status_asuransi']):
			data['status_asuransi'] = 'OFF'

	# More defaults for other NOT NULL fields on DataEntry
	if not data.get('kode_unit'):
		# prefer unit or fallback to pkey fragment
		data['kode_unit'] = data.get('unit') or (data.get('pkey') or '-')

	if not data.get('lokasi_kerja'):
		data['lokasi_kerja'] = data.get('unit') or '-'

	for fld in ('merk', 'kategori', 'eqp_model', 'sn_equipment'):
		if not data.get(fld):
			data[fld] = '-'

	# If year still missing, default to current year to satisfy NOT NULL
	if data.get('year') is None:
		data['year'] = datetime.now().year

	return data


def import_excel(path, dry_run=False, update_existing=False, debug_file=None, start=0, limit=None):
	if not os.path.exists(path):
		print(f"Error: Berkas '{path}' tidak ditemukan.")
		return 0, 0, 0, 0, []

	ext = path.split('.')[-1].lower()
	engine = 'openpyxl' if ext == 'xlsx' else ('xlrd' if ext == 'xls' else None)
	try:
		if engine:
			df = pd.read_excel(path, engine=engine)
		else:
			df = pd.read_excel(path)
	except Exception as e:
		print(f"Error saat membaca berkas Excel: {e}")
		return 0, 0, 0, 0, []

	colmap = normalize_columns(df.columns)

	inserted = 0
	updated = 0
	skipped = 0
	errors = 0
	failed_rows = []

	with app.app_context():
		total = len(df)
		end = total if limit is None else min(total, start + limit)
		for idx in range(start, end):
			row = df.iloc[idx]
			try:
				mapped = map_row_to_entry(row, colmap)

				# Ensure master records exist to satisfy FK constraints and populate dropdowns
				def ensure_master(m):
					pulau_name = (m.get('pulau') or '').strip() or 'UNKNOWN'
					kota_name = (m.get('kota') or '').strip() or 'UNKNOWN'
					pt_name = (m.get('pt') or '').strip() or 'UNKNOWN'
					unit_name = (m.get('unit') or '').strip() or (m.get('kode_unit') or 'UNKNOWN_UNIT')
					lokasi_name = (m.get('lokasi_kerja') or '').strip()
					asuransi_name = (m.get('nama_asuransi') or '').strip()
					merk_name = (m.get('merk') or '').strip()
					kategori_name = (m.get('kategori') or '').strip()

					pulau_obj = None
					kota_obj = None
					pt_obj = None
					unit_obj = None

					# Pulau
					if pulau_name:
						pulau_obj = db.session.execute(db.select(Pulau).where(db.func.upper(Pulau.nama) == pulau_name.upper())).scalar_one_or_none()
						if not pulau_obj:
							pulau_obj = Pulau(nama=pulau_name, dilakukan_oleh='Import Script')
							db.session.add(pulau_obj)
							db.session.flush()

					# Kota
					if kota_name:
						if not pulau_obj:
							kota_obj = db.session.execute(db.select(Kota).where(db.func.upper(Kota.nama) == kota_name.upper())).scalar_one_or_none()
						else:
							kota_obj = db.session.execute(db.select(Kota).where(db.func.upper(Kota.nama) == kota_name.upper(), Kota.reference == pulau_obj.id)).scalar_one_or_none()
						if not kota_obj:
							ref_id = pulau_obj.id if pulau_obj else None
							kota_obj = Kota(nama=kota_name, reference=ref_id if ref_id is not None else 0, dilakukan_oleh='Import Script')
							db.session.add(kota_obj)
							db.session.flush()

					# PT
					if pt_name:
						if kota_obj:
							pt_obj = db.session.execute(db.select(PT).where(db.func.upper(PT.nama) == pt_name.upper(), PT.reference == kota_obj.id)).scalar_one_or_none()
						else:
							pt_obj = db.session.execute(db.select(PT).where(db.func.upper(PT.nama) == pt_name.upper())).scalar_one_or_none()
						if not pt_obj:
							ref_id = kota_obj.id if kota_obj else None
							pt_obj = PT(nama=pt_name, reference=ref_id if ref_id is not None else 0, dilakukan_oleh='Import Script')
							db.session.add(pt_obj)
							db.session.flush()

					# Unit
					if unit_name:
						if pt_obj:
							unit_obj = db.session.execute(db.select(Unit).where(db.func.upper(Unit.nama) == unit_name.upper(), Unit.reference == pt_obj.id)).scalar_one_or_none()
						else:
							unit_obj = db.session.execute(db.select(Unit).where(db.func.upper(Unit.nama) == unit_name.upper())).scalar_one_or_none()
						if not unit_obj:
							ref_id = pt_obj.id if pt_obj else None
							unit_obj = Unit(nama=unit_name, reference=ref_id if ref_id is not None else 0, dilakukan_oleh='Import Script')
							db.session.add(unit_obj)
							db.session.flush()

					# Nama Asuransi
					if asuransi_name and asuransi_name.upper() not in ('NAN', 'NONE', '-', ''):
						asuransi_obj = db.session.execute(db.select(NamaAsuransi).where(db.func.upper(NamaAsuransi.nama) == asuransi_name.upper())).scalar_one_or_none()
						if not asuransi_obj:
							asuransi_obj = NamaAsuransi(nama=asuransi_name, dilakukan_oleh='Import Script')
							db.session.add(asuransi_obj)
							db.session.flush()

					# Merk
					if merk_name and merk_name.upper() not in ('NAN', 'NONE', '-', ''):
						merk_obj = db.session.execute(db.select(Merk).where(db.func.upper(Merk.nama) == merk_name.upper())).scalar_one_or_none()
						if not merk_obj:
							merk_obj = Merk(nama=merk_name, dilakukan_oleh='Import Script')
							db.session.add(merk_obj)
							db.session.flush()

					# Kategori
					if kategori_name and kategori_name.upper() not in ('NAN', 'NONE', '-', ''):
						kategori_obj = db.session.execute(db.select(Kategori).where(db.func.upper(Kategori.nama) == kategori_name.upper())).scalar_one_or_none()
						if not kategori_obj:
							kategori_obj = Kategori(nama=kategori_name, dilakukan_oleh='Import Script')
							db.session.add(kategori_obj)
							db.session.flush()

					# Lokasi Kerja
					if lokasi_name and lokasi_name.upper() not in ('NAN', 'NONE', '-', ''):
						kode_u = m.get('kode_unit') or '-'
						owner_u = m.get('unit') or '-'
						lokasi_obj = db.session.execute(
							db.select(LokasiKerja).where(
								db.func.upper(LokasiKerja.nama) == lokasi_name.upper(),
								db.func.upper(LokasiKerja.kode_unit) == kode_u.upper()
							)
						).scalar_one_or_none()
						if not lokasi_obj:
							lokasi_obj = LokasiKerja(
								kode_unit=kode_u,
								owner=owner_u,
								pulau=pulau_name,
								kota=kota_name,
								pt=pt_name,
								nama=lokasi_name,
								dilakukan_oleh='Import Script'
							)
							db.session.add(lokasi_obj)
							db.session.flush()

				ensure_master(mapped)

				pkey = mapped.get('pkey')
				if not pkey:
					print(f"Skipping row {idx+1}: missing pkey and cannot compose one.")
					skipped += 1
					continue

				exists = db.session.get(DataEntry, pkey)
				if exists:
					if update_existing:
						if dry_run:
							print(f"Would update existing pkey={pkey}")
							updated += 1
							continue
						# Update attributes
						for k, v in mapped.items():
							if k == 'pkey':
								continue
							if hasattr(exists, k):
								setattr(exists, k, v)
						db.session.commit()
						updated += 1
						print(f"Updated pkey={pkey}")
						continue
					else:
						print(f"Skipping existing pkey={pkey} (use --update to overwrite)")
						skipped += 1
						continue

				if dry_run:
					print(f"Would insert pkey={pkey}")
					inserted += 1
					continue

				entry = DataEntry(pkey=pkey)
				for k, v in mapped.items():
					if k == 'pkey':
						continue
					if hasattr(entry, k):
						setattr(entry, k, v)
					else:
						try:
							setattr(entry, k, v)
						except Exception:
							pass

				db.session.add(entry)
				db.session.commit()
				inserted += 1
				print(f"Inserted pkey={pkey}")
			except Exception as e:
				db.session.rollback()
				err_msg = f"{type(e).__name__}: {e}"
				print(f"Error importing row {idx+1} (pkey={pkey if 'pkey' in locals() else 'N/A'}): {err_msg}")
				errors += 1
				try:
					rdata = row.to_dict()
				except Exception:
					rdata = {"__row_index": idx}
				rdata.update({"__error": err_msg, "__pkey": mapped.get('pkey') if 'mapped' in locals() else None, "__row": idx+1})
				failed_rows.append(rdata)

	return inserted, updated, skipped, errors, failed_rows



def main():
	parser = argparse.ArgumentParser(description='Import Excel to DB (Asset Management)')
	parser.add_argument('file', help='Path to Excel file (.xlsx / .xls)')
	parser.add_argument('--dry-run', action='store_true', help='Do not commit, just report')
	parser.add_argument('--update', action='store_true', help='Update existing entries if pkey already exists')
	parser.add_argument('--debug-file', default='failed_rows.csv', help='Write rows that failed to this CSV')
	parser.add_argument('--start', type=int, default=0, help='Start row index (0-based)')
	parser.add_argument('--limit', type=int, default=None, help='Maximum number of rows to process')
	args = parser.parse_args()

	inserted, updated, skipped, errors, failed_rows = import_excel(
		args.file,
		dry_run=args.dry_run,
		update_existing=args.update,
		debug_file=args.debug_file,
		start=args.start,
		limit=args.limit
	)
	print('\n' + '='*40)
	print('📊 Ringkasan Impor Aset:')
	print(f'   - Data Baru Ditambahkan (Inserted): {inserted}')
	if updated > 0:
		print(f'   - Data Diperbarui (Updated):        {updated}')
	print(f'   - Dilewati (Skipped):               {skipped}')
	print(f'   - Galat/Error (Errors):             {errors}')
	print('='*40)

	if failed_rows and args.debug_file:
		try:
			pd.DataFrame(failed_rows).to_csv(args.debug_file, index=False)
			print(f"Detail baris galat disimpan ke: {args.debug_file}")
		except Exception as e:
			print(f"Gagal menulis file debug: {e}")


if __name__ == '__main__':
	main()

