from app import app, db, Pulau, Kota, PT

with app.app_context():
    try:
        # Create island
        p = db.session.execute(db.select(Pulau).where(Pulau.nama == "TEST_JAWA")).scalar_one_or_none()
        if not p:
            p = Pulau(nama="TEST_JAWA", dilakukan_oleh="Tester")
            db.session.add(p)
            db.session.commit()
        
        # Create city 1
        k1 = db.session.execute(db.select(Kota).where(Kota.nama == "TEST_JAKARTA")).scalar_one_or_none()
        if not k1:
            k1 = Kota(nama="TEST_JAKARTA", reference=p.id, dilakukan_oleh="Tester")
            db.session.add(k1)
            db.session.commit()

        # Create city 2
        k2 = db.session.execute(db.select(Kota).where(Kota.nama == "TEST_SURABAYA")).scalar_one_or_none()
        if not k2:
            k2 = Kota(nama="TEST_SURABAYA", reference=p.id, dilakukan_oleh="Tester")
            db.session.add(k2)
            db.session.commit()

        # Try to add PT 'TEST_PT' to City 1
        pt1 = db.session.execute(db.select(PT).where(PT.nama == "TEST_PT", PT.reference == k1.id)).scalar_one_or_none()
        if not pt1:
            pt1 = PT(nama="TEST_PT", reference=k1.id, dilakukan_oleh="Tester")
            db.session.add(pt1)
            db.session.commit()
            print("Successfully added TEST_PT under TEST_JAKARTA.")

        # Try to add PT 'TEST_PT' to City 2 (Should succeed since unique=False and reference is different)
        pt2 = db.session.execute(db.select(PT).where(PT.nama == "TEST_PT", PT.reference == k2.id)).scalar_one_or_none()
        if not pt2:
            pt2 = PT(nama="TEST_PT", reference=k2.id, dilakukan_oleh="Tester")
            db.session.add(pt2)
            db.session.commit()
            print("Successfully added TEST_PT under TEST_SURABAYA (non-unique PT check).")

        # Verify both exist
        assert pt1 is not None and pt2 is not None
        print("Verification: PT names are not unique globally, but are linked to different cities.")
        
    except Exception as e:
        print("Test failed:", e)
