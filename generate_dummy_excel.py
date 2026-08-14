import pandas as pd

# Define the dummy data columns
data = {
    "absen": [104, 102, 101, 105, 103, 106, 108, 107],
    "nik": ["NIK104", "NIK102", "NIK101", "NIK105", "NIK103", "NIK106", "NIK108", "NIK107"],
    "nama": [
        "Budi Santoso (Kepala Divisi Finance)",
        "Ani Wijaya (Kepala Dept Retail)",
        "Cahyo (Staff Retail)",
        "Dina (Kepala Dept Wholesale)",
        "Eko (Staff Wholesale)",
        "Feri (Kepala Divisi HR)",
        "Gita (Kepala Dept Recruitment)",
        "Hadi (Staff Recruitment)"
    ],
    "tmk": ["2020-01-01", "2020-05-12", "2021-03-15", "2019-11-01", "2022-02-20", "2018-06-01", "2020-08-10", "2021-09-01"],
    "jam masuk": ["08:00", "08:00", "08:00", "08:00", "08:00", "08:00", "08:00", "08:00"],
    "jam pulang": ["17:00", "17:00", "17:00", "17:00", "17:00", "17:00", "17:00", "17:00"],
    "pt": ["PT A", "PT A", "PT A", "PT A", "PT A", "PT B", "PT B", "PT B"],
    "staff": ["Staff", "Staff", "Staff", "Staff", "Staff", "Staff", "Staff", "Staff"],
    "jabatan": [
        "Kepala Divisi Finance",
        "Kepala Departemen Retail",
        "Staff Retail",
        "Kepala Departemen Wholesale",
        "Staff Wholesale",
        "Kepala Divisi HR",
        "Kepala Departemen Recruitment",
        "Staff Recruitment"
    ],
    "divisi": ["Finance", "Finance", "Finance", "Finance", "Finance", "HR", "HR", "HR"],
    "departemen": ["", "Retail", "Retail", "Wholesale", "Wholesale", "", "Recruitment", "Recruitment"],
    "priority level": [1, 2, 3, 2, 3, 1, 2, 3]
}

# Create DataFrame
df = pd.DataFrame(data)

# Export to Excel
filename = "dummy_karyawan_test.xlsx"
df.to_excel(filename, index=False)
print(f"Successfully generated '{filename}' in the root workspace directory!")
