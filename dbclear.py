from app import db, app

with app.app_context():
    # 1. Get a list of all table objects from the metadata
    all_tables = db.metadata.tables
    
    # 2. Filter out the 'users' table so it doesn't get dropped
    tables_to_drop = [table for name, table in all_tables.items() if name != 'users']
    
    # 3. Drop only the filtered tables
    print("Dropping tables (excluding 'users')...")
    db.metadata.drop_all(bind=db.engine, tables=tables_to_drop)
    
    # 4. Recreate only the tables that were dropped (excluding 'users' since it still exists)
    print("Recreating tables (excluding 'users')...")
    db.metadata.create_all(bind=db.engine, tables=tables_to_drop)