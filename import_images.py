"""
Script untuk mengimpor gambar yang tertanam (embedded) di dalam file Excel ke database.

Cara penggunaan:
    python import_images.py <path_ke_file_excel> [--category <nama_kategori>] [--dry-run]

Argumen:
    file_path           : Path ke file Excel (.xlsx) yang berisi gambar tertanam
    --category          : Kategori foto untuk semua gambar yang diimpor.
                          Pilihan: no_mesin, no_rangka, bpkb_1, bpkb_2,
                                   tampak_depan, tampak_belakang, tampak_kiri, tampak_kanan,
                                   lainnya_1, lainnya_2, lainnya_3, lainnya_4
                          Default: lainnya_1
    --dry-run           : Simulasi tanpa menyimpan ke database
    --overwrite         : Timpa gambar lama dengan kategori yang sama (default: lewati jika sudah ada)
    --column            : Nama kolom di Excel yang berisi CN/kode unit (default: auto-detect)

Catatan:
    - Skrip akan membaca gambar yang tertanam di Excel berdasarkan baris tempat gambar berada.
    - Gambar dicocokkan ke aset di database berdasarkan nilai kolom CN/kode_unit di baris yang sama.
    - Gambar akan dikompres menggunakan zlib sebelum disimpan ke database.
"""

import sys
import os
import zipfile
import zlib
import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from io import BytesIO

import openpyxl

try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[WARNING] Pillow tidak tersedia. Gambar akan disimpan tanpa kompresi PIL.")
    print("          Install dengan: pip install Pillow")

from app import app, db, DataEntry, UnitImage, AuditLog

VALID_CATEGORIES = [
    'no_mesin', 'no_rangka',
    'bpkb_1', 'bpkb_2',
    'tampak_depan', 'tampak_belakang', 'tampak_kiri', 'tampak_kanan',
    'lainnya_1', 'lainnya_2', 'lainnya_3', 'lainnya_4'
]

CN_HEADER_ALIASES = [
    'cn', 'unit', 'kode_unit', 'kode unit', 'code unit', 'code number',
    'pkey', 'primary_key', 'no polisi', 'no_polisi', 'nopol',
    'sn_equipment', 'sn equipment', 'serial number'
]


def compress_image(image_bytes: bytes) -> bytes:
    if PIL_AVAILABLE:
        try:
            with PILImage.open(BytesIO(image_bytes)) as img:
                if img.mode in ('RGBA', 'P', 'LA'):
                    img = img.convert('RGB')
                max_size = 1920
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), PILImage.LANCZOS)
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=80, optimize=True)
                image_bytes = buffer.getvalue()
        except Exception as e:
            print(f"    [WARNING] PIL compress gagal ({e}), menggunakan bytes asli.")
    return zlib.compress(image_bytes)


def clean_tag(tag: str) -> str:
    return tag.split('}')[-1]


def parse_rels(zip_file: zipfile.ZipFile, rels_path: str) -> dict:
    rels = {}
    try:
        content = zip_file.read(rels_path)
        root = ET.fromstring(content)
        for child in root:
            r_id = child.attrib.get('Id')
            r_target = child.attrib.get('Target')
            if r_id and r_target:
                rels[r_id] = r_target
    except (KeyError, ET.ParseError):
        pass
    return rels


def parse_excel_images(file_path: str) -> dict:
    sheet_images = defaultdict(lambda: defaultdict(list))
    sheet_name_to_file = {}

    with zipfile.ZipFile(file_path, 'r') as z:
        try:
            wb_content = z.read('xl/workbook.xml')
            wb_root = ET.fromstring(wb_content)
            sheet_name_to_r_id = {}
            for child in wb_root.iter():
                if clean_tag(child.tag) == 'sheet':
                    name = child.attrib.get('name')
                    r_id = None
                    for k, v in child.attrib.items():
                        if k.endswith('id'):
                            r_id = v
                            break
                    if name and r_id:
                        sheet_name_to_r_id[name] = r_id
        except Exception as e:
            print(f"[ERROR] Gagal membaca struktur workbook: {e}")
            return sheet_images

        wb_rels = parse_rels(z, 'xl/_rels/workbook.xml.rels')
        for name, r_id in sheet_name_to_r_id.items():
            if r_id in wb_rels:
                sheet_name_to_file[name] = f"xl/{wb_rels[r_id]}"

        for sheet_name, sheet_path in sheet_name_to_file.items():
            sheet_dir = os.path.dirname(sheet_path)
            sheet_file = os.path.basename(sheet_path)
            sheet_rels_path = f"{sheet_dir}/_rels/{sheet_file}.rels"
            sheet_rels = parse_rels(z, sheet_rels_path)

            drawing_paths = []
            for r_id, target in sheet_rels.items():
                if 'drawing' in target.lower():
                    dr_path = os.path.normpath(
                        os.path.join(sheet_dir, target)
                    ).replace('\\', '/')
                    drawing_paths.append(dr_path)

            for drawing_path in drawing_paths:
                dr_dir = os.path.dirname(drawing_path)
                dr_file = os.path.basename(drawing_path)
                dr_rels_path = f"{dr_dir}/_rels/{dr_file}.rels"
                drawing_rels = parse_rels(z, dr_rels_path)

                try:
                    drawing_content = z.read(drawing_path)
                    dr_root = ET.fromstring(drawing_content)

                    for anchor in dr_root.iter():
                        tag = clean_tag(anchor.tag)
                        if tag not in ('twoCellAnchor', 'oneCellAnchor'):
                            continue

                        from_node = None
                        blip_node = None
                        for desc in anchor.iter():
                            desc_tag = clean_tag(desc.tag)
                            if desc_tag == 'from':
                                from_node = desc
                            elif desc_tag == 'blip':
                                blip_node = desc

                        if from_node is None or blip_node is None:
                            continue

                        col_node = row_node = None
                        for c in from_node.iter():
                            c_tag = clean_tag(c.tag)
                            if c_tag == 'col':
                                col_node = c
                            elif c_tag == 'row':
                                row_node = c

                        if col_node is None or row_node is None:
                            continue

                        row_idx = int(row_node.text) + 1

                        embed_id = None
                        for k, v in blip_node.attrib.items():
                            if k.endswith('embed'):
                                embed_id = v
                                break

                        if embed_id and embed_id in drawing_rels:
                            media_rel = drawing_rels[embed_id]
                            media_path = os.path.normpath(
                                os.path.join(dr_dir, media_rel)
                            ).replace('\\', '/')
                            col_idx = int(col_node.text) + 1
                            sheet_images[sheet_name][row_idx].append((col_idx, media_path))

                except Exception as e:
                    print(f"  [WARNING] Gagal memproses drawing '{drawing_path}': {e}")

    return sheet_images


def find_cn_column(header_row, custom_column: str = None) -> tuple:
    if custom_column:
        for idx, cell in enumerate(header_row, start=1):
            val = str(cell.value).strip() if cell.value is not None else ''
            if val.lower() == custom_column.lower():
                return idx, val
        print(f"  [WARNING] Kolom '{custom_column}' tidak ditemukan, akan auto-detect.")

    for idx, cell in enumerate(header_row, start=1):
        val = str(cell.value).strip().lower() if cell.value is not None else ''
        if val in CN_HEADER_ALIASES:
            return idx, str(cell.value).strip()

    for idx, cell in enumerate(header_row, start=1):
        val = str(cell.value).strip().lower() if cell.value is not None else ''
        if any(alias in val for alias in ['cn', 'unit', 'kode', 'pkey']):
            return idx, str(cell.value).strip()

    return 1, str(header_row[0].value) if header_row and header_row[0].value else 'Kolom 1'


def category_from_header(header_value) -> str:
    """Map common Excel image-column labels to the database category."""
    normalized = str(header_value or '').strip().lower().replace('_', ' ')
    normalized = ' '.join(normalized.split())
    aliases = {
        'no mesin': 'no_mesin',
        'nomor mesin': 'no_mesin',
        'no rangka': 'no_rangka',
        'nomor rangka': 'no_rangka',
        'bpkb 1': 'bpkb_1',
        'bpkb1': 'bpkb_1',
        'foto bpkb 1': 'bpkb_1',
        'foto bpkb1': 'bpkb_1',
        'bpkb 2': 'bpkb_2',
        'bpkb2': 'bpkb_2',
        'foto bpkb 2': 'bpkb_2',
        'foto bpkb2': 'bpkb_2',
        'tampak depan': 'tampak_depan',
        'tampak belakang': 'tampak_belakang',
        'tampak kiri': 'tampak_kiri',
        'tampak kanan': 'tampak_kanan',
        'lainnya 1': 'lainnya_1',
        'lainnya 2': 'lainnya_2',
        'lainnya 3': 'lainnya_3',
        'lainnya 4': 'lainnya_4',
    }
    return aliases.get(normalized)


def import_images(file_path: str, category: str, dry_run: bool, overwrite: bool, custom_column: str = None):
    print(f"\nMembuka file Excel: {file_path}")
    print(f"Kategori foto     : {category}")
    print(f"Mode              : {'DRY-RUN (tidak menyimpan)' if dry_run else 'AKTIF'}")
    print(f"Overwrite         : {'Ya' if overwrite else 'Tidak (lewati jika sudah ada)'}")
    print("=" * 60)

    if not os.path.exists(file_path):
        print(f"[ERROR] File tidak ditemukan: {file_path}")
        return

    print("Membaca posisi gambar tertanam di Excel...")
    sheet_images = parse_excel_images(file_path)

    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
    except Exception as e:
        print(f"[ERROR] Gagal membuka workbook: {e}")
        return

    total_inserted = 0
    total_skipped = 0
    total_errors = 0
    total_not_found = 0

    with app.app_context():
        with zipfile.ZipFile(file_path, 'r') as z:
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                print(f"\nSheet: '{ws.title}'")

                rows = list(ws.iter_rows())
                if not rows:
                    print("  -> Sheet kosong, dilewati.")
                    continue

                header_row = rows[0]
                images_by_row = sheet_images.get(ws.title, {})

                if not images_by_row:
                    print("  -> Tidak ada gambar tertanam di sheet ini.")
                    continue

                print(f"  Ditemukan gambar di {len(images_by_row)} baris.")

                cn_col_idx, cn_header_name = find_cn_column(header_row, custom_column)
                print(f"  Kolom CN/kode_unit: '{cn_header_name}' (Kolom {cn_col_idx})")

                for row_idx in range(2, ws.max_row + 1):
                    if row_idx not in images_by_row:
                        continue

                    cn_cell = ws.cell(row=row_idx, column=cn_col_idx)
                    cn_val = str(cn_cell.value).strip().upper().replace(' ', '') \
                        if cn_cell.value is not None else ''

                    if not cn_val or cn_val in ('-', 'NONE', 'NULL', 'NAN'):
                        print(f"  Baris {row_idx}: CN kosong, dilewati.")
                        total_skipped += 1
                        continue

                    entry = db.session.execute(
                        db.select(DataEntry).where(
                            db.or_(
                                db.func.upper(DataEntry.kode_unit) == cn_val,
                                db.func.upper(DataEntry.pkey) == cn_val
                            )
                        )
                    ).scalars().first()

                    if not entry:
                        print(f"  Baris {row_idx}: CN '{cn_val}' tidak ditemukan di database, dilewati.")
                        total_not_found += 1
                        continue

                    pkey = entry.pkey
                    row_image_paths = images_by_row[row_idx]
                    print(f"  Baris {row_idx}: CN='{cn_val}' -> pkey='{pkey}' ({len(row_image_paths)} gambar)")

                    for img_idx, (image_col_idx, media_path) in enumerate(row_image_paths, start=1):
                        header_category = category_from_header(
                            ws.cell(row=1, column=image_col_idx).value
                        )
                        actual_category = header_category or category
                        if not header_category and len(row_image_paths) > 1 and img_idx > 1:
                            base_idx = VALID_CATEGORIES.index(category) if category in VALID_CATEGORIES else -1
                            next_idx = base_idx + (img_idx - 1)
                            if 0 <= next_idx < len(VALID_CATEGORIES):
                                actual_category = VALID_CATEGORIES[next_idx]

                        existing = db.session.execute(
                            db.select(UnitImage).where(
                                UnitImage.pkey == pkey,
                                UnitImage.category == actual_category
                            )
                        ).scalar_one_or_none()

                        if existing and not overwrite:
                            print(f"    Gambar {img_idx} (kategori={actual_category}): sudah ada, dilewati. "
                                  f"Gunakan --overwrite untuk menimpa.")
                            total_skipped += 1
                            continue

                        try:
                            image_bytes = z.read(media_path)
                            ext = media_path.rsplit('.', 1)[-1].lower() if '.' in media_path else 'png'
                            filename = f"import_{cn_val}_{actual_category}.{ext}"

                            compressed = compress_image(image_bytes)

                            if not dry_run:
                                if existing and overwrite:
                                    db.session.delete(existing)
                                    db.session.flush()

                                new_img = UnitImage(
                                    pkey=pkey,
                                    filename=filename,
                                    file_data=compressed,
                                    category=actual_category
                                )
                                db.session.add(new_img)

                                log = AuditLog(
                                    pkey=pkey,
                                    aksi='EDIT',
                                    kolom_diubah=f'Foto Unit ({actual_category})',
                                    nilai_lama='-',
                                    nilai_baru=f'Import gambar dari Excel: {filename}',
                                    dilakukan_oleh='Excel Image Import'
                                )
                                db.session.add(log)

                            action = 'OVERWRITE' if (existing and overwrite) else 'INSERT'
                            size_kb = len(image_bytes) / 1024
                            compressed_kb = len(compressed) / 1024
                            print(f"    [{action}] Gambar {img_idx}: {filename} "
                                  f"({size_kb:.1f} KB -> {compressed_kb:.1f} KB compressed)")
                            total_inserted += 1

                        except KeyError:
                            print(f"    [ERROR] Gambar {img_idx}: file '{media_path}' tidak ditemukan di ZIP.")
                            total_errors += 1
                        except Exception as e:
                            print(f"    [ERROR] Gambar {img_idx} (pkey={pkey}): {e}")
                            total_errors += 1

                if not dry_run:
                    try:
                        db.session.commit()
                        print(f"  Berhasil disimpan.")
                    except Exception as e:
                        db.session.rollback()
                        print(f"  [ERROR] Commit gagal untuk sheet '{ws.title}': {e}")

    print("\n" + "=" * 60)
    print("Ringkasan Impor Gambar:")
    print(f"   - Berhasil Diimpor   : {total_inserted}")
    print(f"   - Dilewati (Skipped) : {total_skipped}")
    print(f"   - Tidak Ditemukan    : {total_not_found}")
    print(f"   - Galat (Errors)     : {total_errors}")
    if dry_run:
        print("\n   Mode DRY-RUN -- tidak ada data yang disimpan ke database.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Import gambar tertanam (embedded) dari Excel ke database aset.'
    )
    parser.add_argument('file_path', help='Path ke file Excel (.xlsx)')
    parser.add_argument(
        '--category',
        default='lainnya_1',
        choices=VALID_CATEGORIES,
        help=(
            'Kategori foto untuk gambar yang diimpor. '
            f'Pilihan: {", ".join(VALID_CATEGORIES)}. '
            'Default: lainnya_1'
        )
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulasi tanpa menyimpan ke database'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Timpa gambar lama dengan kategori yang sama'
    )
    parser.add_argument(
        '--column',
        default=None,
        help='Nama kolom di Excel yang berisi CN/kode unit (default: auto-detect)'
    )

    args = parser.parse_args()

    if not os.path.exists(args.file_path):
        print(f"[ERROR] File tidak ditemukan: {args.file_path}")
        sys.exit(1)

    if not args.file_path.lower().endswith('.xlsx'):
        print("[WARNING] Skrip hanya mendukung format .xlsx (Excel 2007+).")

    import_images(
        file_path=args.file_path,
        category=args.category,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        custom_column=args.column
    )


if __name__ == '__main__':
    main()
