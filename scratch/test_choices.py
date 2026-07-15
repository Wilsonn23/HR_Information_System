from app import app, db, Pulau, Kota, PT, Unit, DataEntry, ExtendForm, get_cn_choices
from datetime import datetime

app.config['WTF_CSRF_ENABLED'] = False

with app.app_context(), app.test_request_context():
    try:
        # Create test master data
        p = db.session.execute(db.select(Pulau).where(Pulau.nama == "TEST_PULAU")).scalar_one_or_none()
        if not p:
            p = Pulau(nama="TEST_PULAU", dilakukan_oleh="Tester")
            db.session.add(p)
            db.session.commit()

        k = db.session.execute(db.select(Kota).where(Kota.nama == "TEST_KOTA")).scalar_one_or_none()
        if not k:
            k = Kota(nama="TEST_KOTA", reference=p.id, dilakukan_oleh="Tester")
            db.session.add(k)
            db.session.commit()

        pt = db.session.execute(db.select(PT).where(PT.nama == "TEST_PT", PT.reference == k.id)).scalar_one_or_none()
        if not pt:
            pt = PT(nama="TEST_PT", reference=k.id, dilakukan_oleh="Tester")
            db.session.add(pt)
            db.session.commit()

        u = db.session.execute(db.select(Unit).where(Unit.nama == "TEST_UNIT", Unit.reference == pt.id)).scalar_one_or_none()
        if not u:
            u = Unit(nama="TEST_UNIT", reference=pt.id, dilakukan_oleh="Tester")
            db.session.add(u)
            db.session.commit()

        # Create test equipment data in DataEntry
        e = db.session.execute(db.select(DataEntry).where(DataEntry.kode_unit == "TESTCN123")).scalar_one_or_none()
        if not e:
            e = DataEntry(
                pulau="TEST_PULAU",
                kota="TEST_KOTA",
                pt="TEST_PT",
                unit="TEST_PT-TEST_UNIT",
                kode_unit="TESTCN123",
                pkey="TEST_PULAU-TEST_KOTA-TEST_PT-TEST_UNIT-TESTCN123",
                lokasi_kerja="TEST_LOKASI",
                nama_asuransi="TEST_ASURANSI",
                no_polis="TEST_POLIS",
                no_polisi="TEST_POLISI",
                merk="TEST_MERK",
                kategori="TEST_KATEGORI",
                eqp_model="TEST_MODEL",
                sn_equipment="TEST_SN_EQP",
                sn_engine="TEST_SN_ENG",
                status_stnk="ON",
                status_asuransi="ON",
                year=2026,
                harus_dibayar_stnk=100000.0,
                tanggal_input=datetime.today().date(),
                diinput_oleh="Tester"
            )
            db.session.add(e)
            db.session.commit()

        # Simulate submit_extend POST call
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['logged_in'] = True
                sess['logged_user'] = 'Tester'
                sess['role'] = 'admin'
                
            response = client.post("/submit_extend", data={
                "pulau": "TEST_PULAU",
                "kota": "TEST_KOTA",
                "pt": "TEST_PT",
                "unit": "TEST_UNIT",
                "cn": "TESTCN123",
                "jenis": "STNK",
                "jumlah_dibayar": "100.000,00",
                "tanggal_bayar": datetime.today().date().strftime('%Y-%m-%d')
            }, follow_redirects=True)
            
            print("Response status code:", response.status_code)
            html = response.get_data(as_text=True)
            
            # If validation failed, it redirects to perpanjang page with validation error HTML
            assert "tidak ditemukan" not in html
            print("Form submission validation and unit lookup succeeded without errors!")
            
    except Exception as e:
        print("Test failed:", e)
