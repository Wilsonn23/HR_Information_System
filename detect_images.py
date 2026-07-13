#!/usr/bin/env python
"""
Utility script to count and detect images in each sheet of an Excel spreadsheet.
Usage:
    venv\\Scripts\\python detect_images.py <path_to_excel_file>
"""

import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

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

def detect_excel_images(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        return

    if not zipfile.is_zipfile(file_path):
        print(f"Error: File '{file_path}' is not a valid zip/xlsx archive.")
        return

    sheet_images = defaultdict(lambda: defaultdict(list))
    sheet_name_to_file = {}

    with zipfile.ZipFile(file_path, 'r') as z:
        # 1. Map sheet names to sheet IDs
        try:
            workbook_content = z.read('xl/workbook.xml')
            wb_root = ET.fromstring(workbook_content)
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
            print(f"Error parsing workbook sheets structure: {e}")
            return

        # 2. Map sheet IDs to XML files
        wb_rels = parse_rels(z, 'xl/_rels/workbook.xml.rels')
        for name, r_id in sheet_name_to_r_id.items():
            if r_id in wb_rels:
                sheet_name_to_file[name] = f"xl/{wb_rels[r_id]}"

        # 3. Process drawings for each worksheet
        for sheet_name, sheet_path in sheet_name_to_file.items():
            sheet_dir = os.path.dirname(sheet_path)
            sheet_file = os.path.basename(sheet_path)
            sheet_rels_path = f"{sheet_dir}/_rels/{sheet_file}.rels"
            sheet_rels = parse_rels(z, sheet_rels_path)
            
            drawing_paths = []
            for r_id, target in sheet_rels.items():
                if 'drawing' in target:
                    dr_path = os.path.normpath(os.path.join(sheet_dir, target)).replace('\\', '/')
                    drawing_paths.append(dr_path)
            
            for drawing_path in drawing_paths:
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
                                    
                                    embed_id = None
                                    for k, v in blip_node.attrib.items():
                                        if k.endswith('embed'):
                                            embed_id = v
                                            break
                                    if embed_id and embed_id in drawing_rels:
                                        media_rel_path = drawing_rels[embed_id]
                                        media_path = os.path.normpath(os.path.join(dr_dir, media_rel_path)).replace('\\', '/')
                                        sheet_images[sheet_name][row_idx].append(media_path)
                except Exception:
                    pass

    # Print results summary
    print(f"\n==============================================")
    print(f"IMAGE DETECTION SUMMARY FOR: {file_path}")
    print(f"==============================================")
    
    grand_total = 0
    for name in sheet_name_to_file.keys():
        images_by_row = sheet_images.get(name, {})
        sheet_total = sum(len(paths) for paths in images_by_row.values())
        grand_total += sheet_total
        
        print(f"\nSheet: '{name}'")
        print(f"  - Total images found: {sheet_total}")
        if sheet_total > 0:
            print(f"  - Anchored rows count: {len(images_by_row)}")
            # Show a brief preview of row-by-row counts
            sorted_rows = sorted(images_by_row.items())
            
            # Print row counts (limit to first 10 rows preview if many)
            preview_limit = 10
            print(f"  - Row breakdown (preview):")
            for r, p in sorted_rows[:preview_limit]:
                print(f"    * Row {r:03d} -> {len(p)} image(s) anchored")
            if len(sorted_rows) > preview_limit:
                print(f"    * ... and {len(sorted_rows) - preview_limit} more rows.")

    print(f"\n==============================================")
    print(f"GRAND TOTAL IMAGES ACROSS ALL SHEETS: {grand_total}")
    print(f"==============================================\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        default_file = "image.xlsx"
        if os.path.exists(default_file):
            detect_excel_images(default_file)
        else:
            print("Usage: venv\\Scripts\\python detect_images.py <path_to_excel_file>")
    else:
        detect_excel_images(sys.argv[1])
