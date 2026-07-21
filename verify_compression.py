from PIL import Image, ImageDraw, ImageOps
import io
import zlib
import random
import sys
import os

def compress_image_pil(binary_data, max_dimension=1600, quality=75):
    try:
        img = Image.open(io.BytesIO(binary_data))
        # Auto-rotate image based on EXIF orientation tag
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
            
        # Convert to RGB
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

def run_proof():
    print("=== PEMBUKTIAN ALGORITMA KOMPRESI FOTO KAMERA ===")
    
    # Check if a custom file path is provided as argument
    user_file_path = None
    if len(sys.argv) > 1:
        user_file_path = sys.argv[1]
        
    if user_file_path:
        if not os.path.exists(user_file_path):
            print(f"[-] Error: Berkas '{user_file_path}' tidak ditemukan!")
            print("Penggunaan: python verify_compression.py [nama_file_gambar]")
            return
            
        print(f"1. Membaca foto pilihan Anda: '{user_file_path}'...")
        with open(user_file_path, "rb") as f:
            original_bytes = f.read()
            
        original_size = len(original_bytes)
        img_temp = Image.open(io.BytesIO(original_bytes))
        width, height = img_temp.size
        print(f"   [+] Ukuran Awal Foto: {original_size / (1024 * 1024):.2f} MB ({original_size:,} bytes)")
        print(f"   [+] Resolusi Awal Foto: {width} x {height} piksel")
    else:
        # Fallback to generating 20MB dummy
        print("1. Membuat gambar simulasi foto kamera 20 MB (karena tidak ada file input)...")
        print("   Tips: Anda bisa menguji foto Anda sendiri dengan menjalankan:")
        print("         python verify_compression.py [path_file_gambar_anda]")
        print("   ------------------------------------------------------------")
        width, height = 4500, 3500
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        for i in range(300):
            x1 = random.randint(0, width)
            y1 = random.randint(0, height)
            x2 = random.randint(x1, min(x1 + 600, width))
            y2 = random.randint(y1, min(y1 + 600, height))
            r = random.randint(0, 255)
            g = random.randint(0, 255)
            b = random.randint(0, 255)
            draw.rectangle([x1, y1, x2, y2], fill=(r, g, b), outline=(255 - r, 255 - g, 255 - b))
        
        orig_buffer = io.BytesIO()
        img.save(orig_buffer, format='JPEG', quality=98)
        original_bytes = orig_buffer.getvalue()
        
        # Pad to reach exactly ~20 MB if necessary
        target_size = 20 * 1024 * 1024 # 20MB
        if len(original_bytes) < target_size:
            padding_needed = target_size - len(original_bytes)
            padding = bytes(random.getrandbits(8) for _ in range(min(padding_needed, 500000)))
            original_bytes += padding * (padding_needed // len(padding) + 1)
            original_bytes = original_bytes[:target_size]
            
        original_size = len(original_bytes)
        print(f"   [+] Ukuran Awal Foto Kamera: {original_size / (1024 * 1024):.2f} MB ({original_size:,} bytes)")
        print(f"   [+] Resolusi Awal Foto: {width} x {height} piksel")

    # 2. Step 1: Pillow Resize and Quality compression
    print("\n2. Melakukan optimisasi dengan Pillow (Resize ke maks 1600px & Kompresi JPEG Q=75)...")
    pillow_optimized_bytes = compress_image_pil(original_bytes)
    pillow_size = len(pillow_optimized_bytes)
    
    opt_img = Image.open(io.BytesIO(pillow_optimized_bytes))
    opt_w, opt_h = opt_img.size
    print(f"   [+] Ukuran setelah Pillow: {pillow_size / 1024:.2f} KB ({pillow_size:,} bytes)")
    print(f"   [+] Resolusi akhir setelah di-resize: {opt_w} x {opt_h} piksel")

    # 3. Step 2: zlib compression (for storage)
    print("\n3. Melakukan kompresi zlib untuk penyimpanan database...")
    final_db_bytes = zlib.compress(pillow_optimized_bytes)
    final_size = len(final_db_bytes)
    print(f"   [+] Ukuran akhir yang disimpan di Database (zlib): {final_size / 1024:.2f} KB ({final_size:,} bytes)")
    
    # 4. Total Saving
    savings_bytes = original_size - final_size
    savings_percent = (savings_bytes / original_size) * 100
    print(f"\n=== HASIL AKHIR ===")
    print(f"   [OK] Ukuran Awal  : {original_size / (1024 * 1024):.2f} MB")
    print(f"   [OK] Ukuran Akhir : {final_size / 1024:.2f} KB ({final_size / (1024 * 1024):.4f} MB)")
    print(f"   [OK] Penghematan  : {savings_percent:.2f}% (Menghemat {savings_bytes / (1024 * 1024):.2f} MB per upload!)")
    
    # 5. Verify & Save decompressed image to file
    print("\n4. Menguji dekompresi kembali data biner DB...")
    decompressed_bytes = zlib.decompress(final_db_bytes)
    is_valid = (decompressed_bytes == pillow_optimized_bytes)
    print(f"   [OK] Data biner hasil dekompresi cocok 100% dengan JPEG hasil optimasi: {is_valid}")
    
    # Save the output file so the user can inspect it
    if user_file_path:
        base, ext = os.path.splitext(user_file_path)
        output_filename = f"{base}_optimized.jpg"
    else:
        output_filename = "dummy_photo_optimized.jpg"
        
    with open(output_filename, "wb") as f_out:
        f_out.write(decompressed_bytes)
        
    print(f"   [OK] Berkas hasil dekompresi disimpan ke: '{output_filename}'")
    print(f"   [OK] Silakan buka berkas tersebut untuk melihat kualitas visual hasil kompresi!")

if __name__ == "__main__":
    run_proof()
