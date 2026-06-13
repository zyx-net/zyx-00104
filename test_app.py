import pytest
from app import app, db
from models import Equipment, Certificate, AuditLog, WorkflowStatus
import json
import os
import time

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
    assert data['service'] == 'calibration-certificate-service'

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
    assert data['status'] == 'active'

def test_import_valid_certificate(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-001',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02,
                'calibrator': 'Zhang San'
            }]
        }),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['successful'] == 1
    assert data['failed'] == 0
    assert len(data['imported']) == 1

def test_import_certificate_date_inverted_error(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-002',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2027-07-01',
                'valid_until': '2027-06-01',
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
    assert any('after calibration date' in str(err).lower() for err in data['errors'][0]['errors'])

def test_import_certificate_equipment_not_found(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-003',
                'equipment_no': 'EQ-NONEXISTENT',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
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
    assert 'not found' in str(data['errors'][0]['errors']).lower()

def test_import_certificate_deviation_exceeds_tolerance(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-004',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
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
    assert any('deviation' in str(err).lower() and 'exceeds' in str(err).lower() for err in data['errors'][0]['errors'])

def test_import_certificate_unit_mismatch(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': 'CERT-TEST-005',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'A',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['failed'] == 1
    assert any('unit' in str(err).lower() for err in data['errors'][0]['errors'])

def test_batch_import_atomicity_all_or_nothing(client, sample_equipment):
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'batch_id': 'BATCH-ATOMICITY-TEST',
            'data': [
                {
                    'cert_no': f'CERT-ATOMICITY-{int(time.time())}-1',
                    'equipment_no': 'EQ-TEST-001',
                    'calibration_date': '2026-01-01',
                    'valid_until': '2027-01-01',
                    'range_min': 0,
                    'range_max': 100,
                    'unit': 'V',
                    'deviation': 0.02
                },
                {
                    'cert_no': f'CERT-ATOMICITY-{int(time.time())}-2',
                    'equipment_no': 'EQ-TEST-001',
                    'calibration_date': '2027-07-01',
                    'valid_until': '2027-06-01',
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
    assert data['failed'] >= 1
    assert len(data['imported']) == 0

    list_response = client.get('/api/certificates')
    list_data = json.loads(list_response.data)
    assert len(list_data) == 0

def test_workflow_full_path(client, sample_equipment):
    import_response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Operator1',
            'batch_id': 'BATCH-WORKFLOW-TEST',
            'data': [{
                'cert_no': 'CERT-WORKFLOW-001',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    assert import_response.status_code == 201
    import_data = json.loads(import_response.data)
    cert_id = import_data['imported'][0]

    cert_response = client.get(f'/api/certificates/{cert_id}')
    cert_data = json.loads(cert_response.data)
    assert cert_data['workflow_status'] == 'draft'
    assert cert_data['entered_by'] is None

    enter_response = client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({
            'operator': 'Operator1',
            'notes': 'Data entered and verified'
        }),
        content_type='application/json'
    )
    assert enter_response.status_code == 200
    enter_data = json.loads(enter_response.data)
    assert enter_data['workflow_status'] == 'entered'
    assert enter_data['entered_by'] == 'Operator1'

    review_response = client.post(f'/api/certificates/{cert_id}/review',
        data=json.dumps({
            'operator': 'Metrologist1',
            'notes': 'Technical review completed',
            'decision_basis': 'All parameters within specification'
        }),
        content_type='application/json'
    )
    assert review_response.status_code == 200
    review_data = json.loads(review_response.data)
    assert review_data['workflow_status'] == 'reviewed'
    assert review_data['reviewed_by'] == 'Metrologist1'

    approve_response = client.post(f'/api/certificates/{cert_id}/approve',
        data=json.dumps({
            'operator': 'Supervisor1',
            'notes': 'Approved for release',
            'decision_basis': 'Meets quality standards'
        }),
        content_type='application/json'
    )
    assert approve_response.status_code == 200
    approve_data = json.loads(approve_response.data)
    assert approve_data['workflow_status'] == 'approved'
    assert approve_data['approved_by'] == 'Supervisor1'

    release_response = client.post(f'/api/certificates/{cert_id}/release',
        data=json.dumps({
            'operator': 'Operator2',
            'notes': 'Device cleared for use',
            'decision_basis': 'All checks passed'
        }),
        content_type='application/json'
    )
    assert release_response.status_code == 200
    release_data = json.loads(release_response.data)
    assert release_data['workflow_status'] == 'released'
    assert release_data['released_by'] == 'Operator2'

def test_operator_cannot_release_own_entry(client, sample_equipment):
    import_response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Operator1',
            'batch_id': 'BATCH-PERMISSION-TEST',
            'data': [{
                'cert_no': 'CERT-PERMISSION-001',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    import_data = json.loads(import_response.data)
    cert_id = import_data['imported'][0]

    client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/review',
        data=json.dumps({'operator': 'Metrologist1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/approve',
        data=json.dumps({'operator': 'Supervisor1', 'decision_basis': 'OK'}),
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
    release_data = json.loads(release_response.data)
    assert any('cannot release their own entry' in str(err).lower() for err in release_data['errors'])

def test_audit_log_completeness(client, sample_equipment):
    import_response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'batch_id': 'BATCH-AUDIT-TEST',
            'data': [{
                'cert_no': 'CERT-AUDIT-001',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    import_data = json.loads(import_response.data)
    cert_id = import_data['imported'][0]

    client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({'operator': 'Operator1', 'notes': 'Entered'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/review',
        data=json.dumps({'operator': 'Metrologist1', 'notes': 'Reviewed', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    audit_response = client.get('/api/audit')
    audit_data = json.loads(audit_response.data)

    import_logs = [log for log in audit_data if log['action'] == 'import']
    assert len(import_logs) == 1
    assert import_logs[0]['operator'] == 'Test Operator'
    assert import_logs[0]['batch_id'] == 'BATCH-AUDIT-TEST'
    assert import_logs[0]['notes'] is not None

    review_logs = [log for log in audit_data if log['action'] == 'review']
    assert len(review_logs) == 1
    assert review_logs[0]['operator'] == 'Metrologist1'
    assert review_logs[0]['notes'] == 'Reviewed'
    assert review_logs[0]['decision_basis'] == 'OK'

def test_duplicate_import_rejected(client, sample_equipment):
    cert_data = {
        'cert_no': 'CERT-DUPLICATE-001',
        'equipment_no': 'EQ-TEST-001',
        'calibration_date': '2026-01-01',
        'valid_until': '2027-01-01',
        'range_min': 0,
        'range_max': 100,
        'unit': 'V',
        'deviation': 0.02
    }

    response1 = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [cert_data]
        }),
        content_type='application/json'
    )
    assert response1.status_code == 201

    response2 = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [cert_data]
        }),
        content_type='application/json'
    )
    assert response2.status_code == 400
    data = json.loads(response2.data)
    assert any('already exists' in str(err).lower() for err in data['errors'][0]['errors'])

def test_export_by_equipment(client, sample_equipment):
    cert_data = {
        'cert_no': 'CERT-EXPORT-001',
        'equipment_no': 'EQ-TEST-001',
        'calibration_date': '2026-01-01',
        'valid_until': '2027-01-01',
        'range_min': 0,
        'range_max': 100,
        'unit': 'V',
        'deviation': 0.02
    }

    client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [cert_data]
        }),
        content_type='application/json'
    )

    export_response = client.get(f'/api/export/equipment/{sample_equipment}')
    assert export_response.status_code == 200
    export_data = json.loads(export_response.data)
    assert len(export_data) == 1
    assert export_data[0]['cert_no'] == 'CERT-EXPORT-001'

def test_export_by_batch(client, sample_equipment):
    client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'batch_id': 'BATCH-EXPORT-TEST',
            'data': [{
                'cert_no': 'CERT-EXPORT-BATCH-001',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )

    export_response = client.get('/api/export/batch/BATCH-EXPORT-TEST')
    assert export_response.status_code == 200
    export_data = json.loads(export_response.data)
    assert len(export_data) == 1
    assert export_data[0]['batch_id'] == 'BATCH-EXPORT-TEST'

def test_limit_certificate(client, sample_equipment):
    cert_id = setup_certificate_for_workflow(client)

    client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/review',
        data=json.dumps({'operator': 'Metrologist1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/approve',
        data=json.dumps({'operator': 'Supervisor1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    limit_response = client.post(f'/api/certificates/{cert_id}/limit',
        data=json.dumps({
            'operator': 'Supervisor2',
            'notes': 'Limited to specific range',
            'decision_basis': 'Deviation in upper range'
        }),
        content_type='application/json'
    )
    assert limit_response.status_code == 200
    limit_data = json.loads(limit_response.data)
    assert limit_data['workflow_status'] == 'limited'

def test_stop_certificate(client, sample_equipment):
    cert_id = setup_certificate_for_workflow(client)

    client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/review',
        data=json.dumps({'operator': 'Metrologist1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_id}/approve',
        data=json.dumps({'operator': 'Supervisor1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    stop_response = client.post(f'/api/certificates/{cert_id}/stop',
        data=json.dumps({
            'operator': 'Supervisor2',
            'notes': 'Device decommissioned',
            'decision_basis': 'Failed accuracy requirements'
        }),
        content_type='application/json'
    )
    assert stop_response.status_code == 200
    stop_data = json.loads(stop_response.data)
    assert stop_data['workflow_status'] == 'stopped'

def setup_certificate_for_workflow(client):
    import_response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Operator1',
            'batch_id': 'BATCH-SETUP-TEST',
            'data': [{
                'cert_no': f'CERT-SETUP-{int(time.time())}',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02
            }]
        }),
        content_type='application/json'
    )
    import_data = json.loads(import_response.data)
    return import_data['imported'][0]
