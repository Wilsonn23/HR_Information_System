"""
Script to import equipment data from an Excel file into the application's database.

Usage:
	python insert.py data.xlsx [--dry-run]

The script will attempt to map common column names from the spreadsheet
to the `DataEntry` model fields. It skips rows where `pkey` already
exists in the database (to avoid duplicates).
"""

import sys
import argparse
from datetime import datetime

import pandas as pd
import re

from app import app, db, DataEntry, Pulau, Kota, PT, Unit


COMMON_MAP = {
	# common spreadsheet headers -> DataEntry attribute
	'pulau': 'pulau',
	'kota': 'kota',
	'pt': 'pt',
	'unit': 'unit',
	'kode_unit': 'kode_unit',
	'kode unit': 'kode_unit',
	'cn': 'kode_unit',
	'pkey': 'pkey',
	'lokasi_kerja': 'lokasi_kerja',
	'lokasi kerja': 'lokasi_kerja',
	'nama_asuransi': 'nama_asuransi',
	'nama_2026': 'nama_asuransi',
	'nama asuransi': 'nama_asuransi',
	'no_polis': 'no_polis',
	'no polis': 'no_polis',
	'no_polis_2026': 'no_polis',
    'no_polisi': 'no_polisi',
	'no polisi': 'no_polisi',
	'akhir_2026': 'tanggal_berakhir_asuransi',
	'akhir 2026': 'tanggal_berakhir_asuransi',
	'stnk': 'tanggal_berakhir_stnk',
	'merk': 'merk',
	'kategori': 'kategori',
	'eqp_model': 'eqp_model',
	'eqp model': 'eqp_model',
	'sn_equipment': 'sn_equipment',
	'sn equipment': 'sn_equipment',
	'sn_engine': 'sn_engine',
	'sn engine': 'sn_engine',
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
	'year': 'year',
	'tahun': 'year',
	'pembulatan_stnk': 'pembulatan_stnk',
	'pembulatan_asuransi': 'pembulatan_asuransi',
	'total_stnk': 'total_stnk',
	'total_asuransi': 'total_asuransi',
	'harus_dibayar_stnk': 'harus_dibayar_stnk',
	'harus_dibayar_asuransi': 'harus_dibayar_asuransi',
	'notes': 'notes',
	'catatan': 'notes',
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


def map_row_to_entry(row, colmap):
	data = {}
	for norm, dest in COMMON_MAP.items():
		if norm in colmap:
			val = row[colmap[norm]]
			# normalize NaN to None
			if pd.isna(val):
				val = None
			# dates: convert to YYYY-MM-DD strings if pandas Timestamp
			if hasattr(val, 'strftime'):
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


def import_excel(path, dry_run=False, debug_file=None, start=0, limit=None):
	df = pd.read_excel(path)
	colmap = normalize_columns(df.columns)

	inserted = 0
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

				# Ensure master records exist to satisfy FK constraints
				def ensure_master(m):
					pulau_name = (m.get('pulau') or '').strip() or 'UNKNOWN'
					kota_name = (m.get('kota') or '').strip() or 'UNKNOWN'
					pt_name = (m.get('pt') or '').strip() or 'UNKNOWN'
					unit_name = (m.get('unit') or '').strip() or (m.get('kode_unit') or 'UNKNOWN_UNIT')

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
							# create kota with pulau reference if available
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

				# flush creations so FK ids exist for later logic
				# note: we don't commit here; per-row commit happens later
				ensure_master(mapped)

				pkey = mapped.get('pkey')
				if not pkey:
					print(f"Skipping row {idx+1}: missing pkey and cannot compose one.")
					skipped += 1
					continue

				exists = db.session.get(DataEntry, pkey)
				if exists:
					print(f"Skipping existing pkey={pkey}")
					skipped += 1
					continue

				if dry_run:
					print(f"Would insert pkey={pkey}")
					inserted += 1
					continue

				entry = DataEntry(pkey=pkey)
				# set all mapped attributes
				for k, v in mapped.items():
					if k == 'pkey':
						continue
					if hasattr(entry, k):
						setattr(entry, k, v)
					else:
						# still set attribute even if not defined on model (SQLAlchemy will ignore unknowns on commit)
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
				# capture original row data plus error
				try:
					rdata = row.to_dict()
				except Exception:
					rdata = {"__row_index": idx}
				rdata.update({"__error": err_msg, "__pkey": mapped.get('pkey') if 'mapped' in locals() else None, "__row": idx+1})
				failed_rows.append(rdata)

	return inserted, skipped, errors, failed_rows



def main():
	parser = argparse.ArgumentParser(description='Import Excel to DB')
	parser.add_argument('file', help='Path to Excel file')
	parser.add_argument('--dry-run', action='store_true', help='Do not commit, just report')
	parser.add_argument('--debug-file', default='failed_rows.csv', help='Write rows that failed to this CSV')
	parser.add_argument('--start', type=int, default=0, help='Start row index (0-based)')
	parser.add_argument('--limit', type=int, default=None, help='Maximum number of rows to process')
	args = parser.parse_args()

	inserted, skipped, errors, failed_rows = import_excel(args.file, dry_run=args.dry_run, debug_file=args.debug_file, start=args.start, limit=args.limit)
	print('\nSummary:')
	print(f'  Inserted: {inserted}')
	print(f'  Skipped:  {skipped}')
	print(f'  Errors:   {errors}')

	if failed_rows and args.debug_file:
		try:
			pd.DataFrame(failed_rows).to_csv(args.debug_file, index=False)
			print(f"Wrote {len(failed_rows)} failed rows to {args.debug_file}")
		except Exception as e:
			print(f"Failed to write debug file: {e}")


if __name__ == '__main__':
	main()

