from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE unit DROP CONSTRAINT IF EXISTS unit_nama_key;"))
        db.session.commit()
        print("Successfully dropped unit_nama_key constraint.")
    except Exception as e:
        db.session.rollback()
        print("Failed to drop constraint:", e)
