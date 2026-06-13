import pytest
from app import app, db
from models import Equipment, Certificate, AuditLog, WorkflowStatus
import json
import os

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()

@pytest.fixture
def sample_equipment(client):
    with app.app_context():
        equipment = Equipment(
            equipment_no='EQ-TEST-001',
            equipment_name='Test Equipment',
            model_spec='TEST-100',
            manufacturer='Test Corp',
            range_min=0,
            range_max=100,
            unit='V',
            tolerance=0.05,
            location='Lab 1'
        )
        db.session.add(equipment)
        db.session.commit()
        return equipment.id

def test_health_check(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'ok'

def test_create_equipment(client):
    response = client.post('/api/equipment',
        data=json.dumps({
            'equipment_no': 'EQ-TEST-002',
            'equipment_name': 'Test Equipment 2',
            'range_min': 0,
            'range_max': 100,
            'unit': 'V',
            'tolerance': 0.01
        }),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['equipment_no'] == 'EQ-TEST-002'

def test_import_valid_certificate(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-001',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2024-06-01',
                'valid_until': '2025-06-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['successful'] == 1
    assert data['failed'] == 0

def test_import_certificate_date_error(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-002',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2025-07-01',
                'valid_until': '2025-06-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['failed'] == 1

def test_import_certificate_deviation_error(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-003',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2024-06-01',
                'valid_until': '2025-06-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.1
            }]
        }),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['failed'] == 1
    assert any('deviation' in str(err).lower() for err in data['errors'][0]['errors'])

def test_workflow_transition(client, sample_equipment):
    import_response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-004',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2024-06-01',
                'valid_until': '2025-06-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    data = json.loads(import_response.data)
    cert_id = data['imported'][0]

    enter_response = client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({
            'operator': 'Operator1',
            'notes': 'Entered'
        }),
        content_type='application/json'
    )
    assert enter_response.status_code == 200

    review_response = client.post(f'/api/certificates/{cert_id}/review',
        data=json.dumps({
            'operator': 'Metrologist1',
            'notes': 'Reviewed',
            'decision_basis': 'OK'
        }),
        content_type='application/json'
    )
    assert review_response.status_code == 200

    approve_response = client.post(f'/api/certificates/{cert_id}/approve',
        data=json.dumps({
            'operator': 'Supervisor1',
            'notes': 'Approved',
            'decision_basis': 'OK'
        }),
        content_type='application/json'
    )
    assert approve_response.status_code == 200

    release_response = client.post(f'/api/certificates/{cert_id}/release',
        data=json.dumps({
            'operator': 'Operator2',
            'notes': 'Released',
            'decision_basis': 'OK'
        }),
        content_type='application/json'
    )
    assert release_response.status_code == 200

def test_operator_cannot_release_own_entry(client, sample_equipment):
    import_response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-005',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2024-06-01',
                'valid_until': '2025-06-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    data = json.loads(import_response.data)
    cert_id = data['imported'][0]

    enter_response = client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({
            'operator': 'Operator1'
        }),
        content_type='application/json'
    )
    assert enter_response.status_code == 200

    client.post(f'/api/certificates/{cert_id}/review',
        data=json.dumps({
            'operator': 'Metrologist1',
            'decision_basis': 'OK'
        }),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/approve',
        data=json.dumps({
            'operator': 'Supervisor1',
            'decision_basis': 'OK'
        }),
        content_type='application/json'
    )

    release_response = client.post(f'/api/certificates/{cert_id}/release',
        data=json.dumps({
            'operator': 'Operator1',
            'notes': 'Try to release own entry'
        }),
        content_type='application/json'
    )
    assert release_response.status_code == 400
    data = json.loads(release_response.data)
    assert any('cannot release their own entry' in str(err).lower() for err in data['errors'])

def test_batch_import_atomicity(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'batch_id': 'BATCH-ATOMICITY-TEST',
            'data': [
                {
                    'cert_no': 'CERT-TEST-006',
                    'equipment_no': 'EQ-TEST-001',
                    'calibration_date': '2024-06-01',
                    'valid_until': '2025-06-01',
                    'range_min': 0,
                    'range_max': 100,
                    'unit': 'V',
                    'deviation': 0.02
                },
                {
                    'cert_no': 'CERT-TEST-007',
                    'equipment_no': 'EQ-TEST-001',
                    'calibration_date': '2025-07-01',
                    'valid_until': '2025-06-01',
                    'range_min': 0,
                    'range_max': 100,
                    'unit': 'V',
                    'deviation': 0.02
                }
            ]
        }),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['successful'] == 0
    assert data['failed'] == 2
    assert len(data['imported']) == 0

def test_audit_log_created(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-008',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2024-06-01',
                'valid_until': '2025-06-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )

    audit_response = client.get('/api/audit')
    data = json.loads(audit_response.data)
    assert len(data) > 0
    assert data[0]['operator'] == 'Test Operator'
    assert data[0]['action'] == 'import'
