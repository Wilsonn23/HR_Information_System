from app import app, db, DataEntry
from datetime import datetime

with app.app_context(), app.test_request_context():
    try:
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
                harus_dibayar_stnk=1500000.0,
                tanggal_input=datetime.today().date(),
                diinput_oleh="Tester"
            )
            db.session.add(e)
            db.session.commit()

        # Simulate API call with session
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['logged_in'] = True
                sess['logged_user'] = 'Tester'
                sess['role'] = 'admin'
                
            url = "/api/get-tagihan/STNK/TESTCN123?pulau=TEST_PULAU&kota=TEST_KOTA&pt=TEST_PT&unit=TEST_PT-TEST_UNIT"
            print("Requesting API:", url)
            response = client.get(url)
            print("Response status:", response.status_code)
            data = response.get_json()
            print("Response data:", data)
            
            assert response.status_code == 200
            assert data['success'] is True
            assert data['total_tagihan'] == 1500000.0
            
            print("Tagihan lookup API check passed successfully!")
    except Exception as e:
        print("Test failed:", e)
