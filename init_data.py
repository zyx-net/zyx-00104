import json
from app import app, db
from models import Equipment, Certificate
import os

def load_equipment():
    with app.app_context():
        if Equipment.query.count() > 0:
            print("Equipment already loaded, skipping...")
            return

        equipment_file = os.path.join(os.path.dirname(__file__), 'samples', 'equipment.json')
        with open(equipment_file, 'r', encoding='utf-8') as f:
            equipment_list = json.load(f)

        for eq_data in equipment_list:
            operator = eq_data.pop('operator', 'system')
            equipment = Equipment(**eq_data)
            db.session.add(equipment)

        db.session.commit()
        print(f"Loaded {len(equipment_list)} equipment records")

def load_certificates():
    with app.app_context():
        if Certificate.query.count() > 0:
            print("Certificates already loaded, skipping...")
            return

        certs_file = os.path.join(os.path.dirname(__file__), 'samples', 'certificates_valid.json')
        with open(certs_file, 'r', encoding='utf-8') as f:
            certs_list = json.load(f)

        from services import CertificateImportService
        import_service = CertificateImportService()

        for cert_data in certs_list:
            result, success = import_service._import_single_certificate(
                cert_data,
                cert_data.get('operator', 'system'),
                'BATCH-INIT-001'
            )
            if not success:
                print(f"Failed to import {cert_data.get('cert_no')}: {result.get('errors')}")

        db.session.commit()
        print(f"Loaded {len(certs_list)} certificate records")

def reset_database():
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Database reset complete")

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == 'reset':
            reset_database()
        elif sys.argv[1] == 'equipment':
            load_equipment()
        elif sys.argv[1] == 'certificates':
            load_certificates()
        else:
            print("Usage: python init_data.py [reset|equipment|certificates]")
    else:
        reset_database()
        load_equipment()
        load_certificates()
        print("All sample data loaded successfully!")
