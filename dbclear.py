from app import db, app

with app.app_context():
    # 1. Filter out the master tables so they don't get dropped
    excluded = {
        "users", 
        "pulau", 
        "kota", 
        "pt", 
        "unit", 
        "nama_asuransi", 
        "merk", 
        "kategori", 
        "bulan", 
        "hari_libur",
        "jabatan"
    }

    # 2. Get sorted list of tables to drop (respecting foreign key dependencies)
    sorted_tables = [table for table in db.metadata.sorted_tables if table.name not in excluded]

    # 3. Drop tables in reverse dependency order (child tables first)
    db.metadata.drop_all(bind=db.engine, tables=reversed(sorted_tables))
    
    # 4. Recreate tables in dependency order (parent tables first)
    db.metadata.create_all(bind=db.engine, tables=sorted_tables)