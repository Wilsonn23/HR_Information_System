#!/usr/bin/env python
"""
Import script to load unit images from an Excel file into the PostgreSQL database.
This script extracts embedded images directly from the Excel ZIP structure.
Usage:
    venv\\Scripts\\python import_images.py <path_to_excel_file>
"""

import os
import sys
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import defaultdict
import openpyxl
from sqlalchemy.exc import SQLAlchemyError

# Import Flask app and db components
try:
    from app import app, db, DataEntry, UnitImage, AuditLog
except ImportError as e:
    print(f"Error: Could not import Flask application components: {e}")
    sys.exit(1)

def clean_tag(tag):
    return tag.split('}')[-1]

def parse_rels(zip_file, rels_path):
    rels = {}
    try:
        content = zip_file.read(rels_path)
        root = ET.fromstring(content)
        for child in root:
            r_id = child.attrib.get('Id')
            r_target = child.attrib.get('Target')
            rels[r_id] = r_target
    except (KeyError, ET.ParseError):
        pass
    return rels

def parse_excel_images(file_path):
    """
    Parses sheet names, columns, and maps (sheet_name, row) -> lists of zip media file paths.
    """
    sheet_images = defaultdict(lambda: defaultdict(list))
    sheet_name_to_file = {}
    
    if not zipfile.is_zipfile(file_path):
        print(f"Error: File '{file_path}' is not a valid zip/xlsx archive.")
        return sheet_images

    with zipfile.ZipFile(file_path, 'r') as z:
        # 1. Parse workbook XML to map sheet name -> sheet relationship ID (rId)
        try:
            workbook_content = z.read('xl/workbook.xml')
            wb_root = ET.fromstring(workbook_content)
            
            # Map sheet name to relationship ID
            sheet_name_to_r_id = {}
            for child in wb_root.iter():
                if clean_tag(child.tag) == 'sheet':
                    name = child.attrib.get('name')
                    # Find relationship ID attribute (often under r:id namespace)
                    r_id = None
                    for k, v in child.attrib.items():
                        if k.endswith('id'):
                            r_id = v
                            break
                    if name and r_id:
                        sheet_name_to_r_id[name] = r_id
        except Exception as e:
            print(f"Error parsing xl/workbook.xml: {e}")
            return sheet_images

        # 2. Parse workbook rels to map rId -> worksheets/sheetX.xml
        wb_rels = parse_rels(z, 'xl/_rels/workbook.xml.rels')
        
        # Combine: map sheet name -> worksheets/sheetX.xml (path inside zip)
        for name, r_id in sheet_name_to_r_id.items():
            if r_id in wb_rels:
                sheet_name_to_file[name] = f"xl/{wb_rels[r_id]}"

        # 3. For each worksheet, parse its rels to find drawings/drawingX.xml
        for sheet_name, sheet_path in sheet_name_to_file.items():
            # The rels file path is typically xl/worksheets/_rels/sheetX.xml.rels
            sheet_dir = os.path.dirname(sheet_path)
            sheet_file = os.path.basename(sheet_path)
            sheet_rels_path = f"{sheet_dir}/_rels/{sheet_file}.rels"
            
            sheet_rels = parse_rels(z, sheet_rels_path)
            
            # Find drawing relationship targets
            drawing_paths = []
            for r_id, target in sheet_rels.items():
                if 'drawing' in target:
                    # Resolve drawing path relative to worksheet directory
                    dr_path = os.path.normpath(os.path.join(sheet_dir, target)).replace('\\', '/')
                    drawing_paths.append(dr_path)
            
            # 4. Parse drawing files to map row index -> media files
            for drawing_path in drawing_paths:
                # Find drawing's rels file path, e.g. xl/drawings/_rels/drawingX.xml.rels
                dr_dir = os.path.dirname(drawing_path)
                dr_file = os.path.basename(drawing_path)
                dr_rels_path = f"{dr_dir}/_rels/{dr_file}.rels"
                
                drawing_rels = parse_rels(z, dr_rels_path)
                
                try:
                    drawing_content = z.read(drawing_path)
                    dr_root = ET.fromstring(drawing_content)
                    
                    for child in dr_root.iter():
                        tag = clean_tag(child.tag)
                        if tag in ['twoCellAnchor', 'oneCellAnchor']:
                            from_node = None
                            blip_node = None
                            for desc in child.iter():
                                desc_tag = clean_tag(desc.tag)
                                if desc_tag == 'from':
                                    from_node = desc
                                elif desc_tag == 'blip':
                                    blip_node = desc
                            
                            if from_node is not None and blip_node is not None:
                                col_node = None
                                row_node = None
                                for c in from_node.iter():
                                    c_tag = clean_tag(c.tag)
                                    if c_tag == 'col':
                                        col_node = c
                                    elif c_tag == 'row':
                                        row_node = c
                                
                                if col_node is not None and row_node is not None:
                                    col_idx = int(col_node.text) + 1
                                    row_idx = int(row_node.text) + 1
                                    
                                    # Extract relationship ID
                                    embed_id = None
                                    for k, v in blip_node.attrib.items():
                                        if k.endswith('embed'):
                                            embed_id = v
                                            break
                                    if embed_id and embed_id in drawing_rels:
                                        media_rel_path = drawing_rels[embed_id]
                                        # Resolve media path relative to drawing folder
                                        media_path = os.path.normpath(os.path.join(dr_dir, media_rel_path)).replace('\\', '/')
                                        sheet_images[sheet_name][row_idx].append(media_path)
                except Exception as e:
                    print(f"Error parsing drawing '{drawing_path}' in sheet '{sheet_name}': {e}")
                    
    return sheet_images

def import_images(file_path):
    print(f"Opening Excel workbook as archive: {file_path}")
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        return

    # Extract all images mapped to sheets and row indices
    sheet_images = parse_excel_images(file_path)
    
    # Load sheet data (headers and cells) using openpyxl
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        print(f"Workbook sheets loaded: {wb.sheetnames}")
    except Exception as e:
        print(f"Error loading workbook cell data: {e}")
        return

    total_images_inserted = 0
    total_rows_processed = 0

    with app.app_context():
        # Open ZIP for reading image bytes
        with zipfile.ZipFile(file_path, 'r') as z:
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                print(f"\nProcessing sheet: {ws.title}")
                
                rows = list(ws.iter_rows())
                if not rows:
                    print(f"Sheet '{ws.title}' is empty.")
                    continue

                header_row = rows[0]
                
                # Find column index for CN/Unit (1-indexed)
                unit_col_idx = None
                for col_idx, cell in enumerate(header_row, start=1):
                    val = str(cell.value).strip().lower() if cell.value is not None else ""
                    if val in ['unit', 'cn', 'unit cn', 'code number', 'code_number', 'unit_cn']:
                        unit_col_idx = col_idx
                        break
                
                if unit_col_idx is None:
                    # Fallback matching
                    for col_idx, cell in enumerate(header_row, start=1):
                        val = str(cell.value).strip().lower() if cell.value is not None else ""
                        if 'unit' in val or 'cn' in val:
                            unit_col_idx = col_idx
                            break
                
                if unit_col_idx is None:
                    print(f"Warning: Could not identify CN column in sheet '{ws.title}'. Defaulting to Column 1.")
                    unit_col_idx = 1
                else:
                    print(f"CN column found: '{header_row[unit_col_idx-1].value}' (Column {unit_col_idx})")

                # Get the images map for this sheet
                images_by_row = sheet_images.get(ws.title, {})
                if not images_by_row:
                    print(f"No cell-anchored images found in sheet '{ws.title}'.")
                    continue

                print(f"Found image anchors for {len(images_by_row)} rows in sheet '{ws.title}'.")

                for row_idx in range(2, ws.max_row + 1):
                    # Only process row if it contains images (the user requested only importing rows containing images)
                    if row_idx not in images_by_row:
                        continue

                    total_rows_processed += 1
                    
                    # Extract CN
                    cn_cell = ws.cell(row=row_idx, column=unit_col_idx)
                    cn_val = str(cn_cell.value).strip().upper().replace(" ", "") if cn_cell.value is not None else ""
                    
                    if not cn_val or cn_val in ['-', 'NONE', 'NULL']:
                        print(f"Row {row_idx}: Skipped because CN is empty or invalid.")
                        continue

                    # Verify CN exists in database
                    existing_entry = db.session.query(DataEntry).filter_by(cn=cn_val).first()
                    if not existing_entry:
                        print(f"Row {row_idx}: CN '{cn_val}' not found in database. Skipping image.")
                        continue

                    row_images = images_by_row[row_idx]
                    print(f"Row {row_idx}: Processing {len(row_images)} image(s) for CN '{cn_val}'...")
                    
                    for img_idx, media_path in enumerate(row_images, start=1):
                        try:
                            # Read raw bytes directly from the ZIP archive
                            image_bytes = z.read(media_path)
                            
                            # Deduce file extension
                            ext = media_path.split('.')[-1].lower() if '.' in media_path else 'png'
                            filename = f"excel_import_{cn_val}_{row_idx}_{img_idx}.{ext}"
                            
                            new_img = UnitImage(
                                cn=cn_val,
                                filename=filename,
                                file_data=image_bytes
                            )
                            db.session.add(new_img)
                            
                            log_upload = AuditLog(
                                cn=cn_val,
                                aksi="EDIT",
                                kolom_diubah="Tambah Foto Unit via Excel",
                                nilai_lama="-",
                                nilai_baru=f"Unggah foto: {filename}",
                                diubah_oleh="Excel Image Import",
                                tanggal_aksi=datetime.now()
                            )
                            db.session.add(log_upload)
                            total_images_inserted += 1
                            
                        except Exception as e:
                            print(f"Row {row_idx} (CN={cn_val}), Image {img_idx} ({media_path}): Error processing image - {e}")
                            db.session.rollback()

                try:
                    db.session.commit()
                except SQLAlchemyError as e:
                    db.session.rollback()
                    print(f"Database commit error: {e}")

    print(f"\nImport finished!")
    print(f"  - Total rows with images processed: {total_rows_processed}")
    print(f"  - Total images inserted: {total_images_inserted}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Check if there is a default file
        default_file = "image.xlsx"
        if os.path.exists(default_file):
            print(f"No file path specified. Using default file: {default_file}")
            import_images(default_file)
        else:
            print("Usage: venv\\Scripts\\python import_images.py <path_to_excel_file>")
            print("Or place 'image.xlsx' in the root directory and run: venv\\Scripts\\python import_images.py")
    else:
        file_path = sys.argv[1]
        if not os.path.exists(file_path):
            print(f"Error: File '{file_path}' does not exist.")
        else:
            import_images(file_path)
