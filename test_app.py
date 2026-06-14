import pytest
from app import app, db
from models import Equipment, Certificate, AuditLog, WorkflowStatus
from datetime import datetime
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

def test_create_equipment_array(client):
    """测试数组格式创建设备"""
    response = client.post('/api/equipment',
        data=json.dumps([
            {
                'equipment_no': f'EQ-ARRAY-{int(time.time())}-1',
                'equipment_name': 'Test Multimeter',
                'model_spec': 'FLUKE 87V',
                'manufacturer': 'Fluke',
                'range_min': 0,
                'range_max': 1000,
                'unit': 'V',
                'tolerance': 0.05,
                'location': 'Lab 1'
            },
            {
                'equipment_no': f'EQ-ARRAY-{int(time.time())}-2',
                'equipment_name': 'Test Pressure Gauge',
                'model_spec': 'WIKA S-10',
                'manufacturer': 'WIKA',
                'range_min': 0,
                'range_max': 10,
                'unit': 'MPa',
                'tolerance': 0.002,
                'location': 'Lab 2'
            }
        ]),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]['equipment_name'] == 'Test Multimeter'
    assert data[1]['equipment_name'] == 'Test Pressure Gauge'

def test_export_equipment_csv(client, sample_equipment):
    """测试按设备ID导出CSV"""
    client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': f'CERT-EXPORT-CSV-{int(time.time())}',
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

    cert_response = client.get('/api/certificates')
    certs = json.loads(cert_response.data)
    cert_id = certs[0]['id']

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

    client.post(f'/api/certificates/{cert_id}/release',
        data=json.dumps({'operator': 'Operator2', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    export_response = client.get(f'/api/export/equipment/{sample_equipment}?format=csv')
    assert export_response.status_code == 200
    assert 'text/csv' in export_response.content_type
    csv_content = export_response.data.decode('utf-8')
    assert 'cert_no' in csv_content
    assert 'equipment_no' in csv_content
    lines = csv_content.strip().split('\n')
    assert len(lines) >= 2

def test_export_equipment_json(client, sample_equipment):
    """测试按设备ID导出JSON"""
    client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'data': [{
                'cert_no': f'CERT-EXPORT-JSON-{int(time.time())}',
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

    export_response = client.get(f'/api/export/equipment/{sample_equipment}?format=json')
    assert export_response.status_code == 200
    data = json.loads(export_response.data)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]['equipment_no'] == 'EQ-TEST-001'

def test_import_certificate_array_format(client, sample_equipment):
    """测试数组格式导入证书（按 README 方式）"""
    response = client.post('/api/certificates/import',
        data=json.dumps([
            {
                'cert_no': f'CERT-ARRAY-{int(time.time())}-1',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-01',
                'valid_until': '2027-01-01',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.02,
                'calibrator': 'Zhang San'
            },
            {
                'cert_no': f'CERT-ARRAY-{int(time.time())}-2',
                'equipment_no': 'EQ-TEST-001',
                'calibration_date': '2026-01-02',
                'valid_until': '2027-01-02',
                'range_min': 0,
                'range_max': 100,
                'unit': 'V',
                'deviation': 0.03,
                'calibrator': 'Li Si'
            }
        ]),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['successful'] == 2
    assert data['failed'] == 0
    assert len(data['imported']) == 2

def test_import_certificate_wrapped_format(client, sample_equipment):
    """测试包装格式导入证书（{data: [...]})"""
    response = client.post('/api/certificates/import',
        data=json.dumps({
            'operator': 'Test Operator',
            'batch_id': f'BATCH-WRAPPED-{int(time.time())}',
            'data': [{
                'cert_no': f'CERT-WRAPPED-{int(time.time())}',
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

def test_import_certificate_no_500_on_array(client, sample_equipment):
    """测试数组格式导入不会返回 500"""
    response = client.post('/api/certificates/import',
        data=json.dumps([{
            'cert_no': f'CERT-NO500-{int(time.time())}',
            'equipment_no': 'EQ-TEST-001',
            'calibration_date': '2026-01-01',
            'valid_until': '2027-01-01',
            'range_min': 0,
            'range_max': 100,
            'unit': 'V',
            'deviation': 0.02
        }]),
        content_type='application/json'
    )
    assert response.status_code in [200, 201, 400]
    assert response.status_code != 500

def test_import_error_certificate_still_fails(client, sample_equipment):
    """测试错误证书仍按预期失败（设备不存在）"""
    response = client.post('/api/certificates/import',
        data=json.dumps([{
            'cert_no': f'CERT-ERROR-{int(time.time())}',
            'equipment_no': 'EQ-NONEXISTENT',
            'calibration_date': '2026-01-01',
            'valid_until': '2027-01-01',
            'range_min': 0,
            'range_max': 100,
            'unit': 'V',
            'deviation': 0.02
        }]),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['failed'] == 1
    assert 'not found' in str(data['errors'][0]['errors']).lower()



def test_create_equipment_with_negative_range(client):
    """测试创建设备支持负量程（温度计）"""
    response = client.post('/api/equipment',
        data=json.dumps({
            'equipment_no': f'EQ-NEG-{int(time.time())}',
            'equipment_name': 'Thermometer',
            'range_min': -40,
            'range_max': 150,
            'unit': '°C',
            'tolerance': 0.1
        }),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['range_min'] == -40
    assert data['range_max'] == 150

def test_import_certificate_with_negative_range(client):
    """测试导入负量程证书（温度计）- 修复 Range min must be non-negative 误拒问题"""
    with app.app_context():
        equipment = Equipment(
            equipment_no=f'EQ-THERMO-{int(time.time())}',
            equipment_name='Thermometer',
            range_min=-40,
            range_max=150,
            unit='°C',
            tolerance=0.1
        )
        db.session.add(equipment)
        db.session.commit()
        eq_no = equipment.equipment_no

    response = client.post('/api/certificates/import',
        data=json.dumps([{
            'cert_no': f'CERT-THERMO-{int(time.time())}',
            'equipment_no': eq_no,
            'calibration_date': '2026-01-01',
            'valid_until': '2027-01-01',
            'range_min': -40,
            'range_max': 150,
            'unit': '°C',
            'deviation': 0.05
        }]),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['successful'] == 1
    assert data['failed'] == 0

def test_import_certificate_exceeds_equipment_range_still_fails(client):
    """测试证书量程超出设备范围仍应失败"""
    with app.app_context():
        equipment = Equipment(
            equipment_no=f'EQ-LIMIT-{int(time.time())}',
            equipment_name='Thermometer',
            range_min=-40,
            range_max=150,
            unit='°C',
            tolerance=0.1
        )
        db.session.add(equipment)
        db.session.commit()
        eq_no = equipment.equipment_no

    response = client.post('/api/certificates/import',
        data=json.dumps([{
            'cert_no': f'CERT-OUT-{int(time.time())}',
            'equipment_no': eq_no,
            'calibration_date': '2026-01-01',
            'valid_until': '2027-01-01',
            'range_min': -50,
            'range_max': 200,
            'unit': '°C',
            'deviation': 0.05
        }]),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['failed'] == 1
    assert 'exceeds equipment range' in str(data['errors'][0]['errors']).lower()

def test_expiry_warning_default_days(client, sample_equipment):
    """测试过期预警接口使用默认配置"""
    with app.app_context():
        cert = Certificate(
            cert_no='CERT-EXPIRY-001',
            batch_id='BATCH-EXPIRY-TEST',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2026, 6, 20).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02
        )
        db.session.add(cert)
        db.session.commit()

    response = client.get('/api/certificates/expiry-warning')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'warning_days_used' in data
    assert 'count' in data
    assert 'certificates' in data
    assert data['count'] >= 1

def test_expiry_warning_custom_days(client, sample_equipment):
    """测试过期预警接口使用自定义天数"""
    response = client.get('/api/certificates/expiry-warning?days=7')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['warning_days_used'] == 7

def test_batch_stats(client, sample_equipment):
    """测试批次统计接口"""
    with app.app_context():
        cert1 = Certificate(
            cert_no='CERT-BATCH-001',
            batch_id='BATCH-STATS-001',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2027, 1, 1).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02,
            workflow_status='draft'
        )
        cert2 = Certificate(
            cert_no='CERT-BATCH-002',
            batch_id='BATCH-STATS-001',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2027, 1, 1).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02,
            workflow_status='released'
        )
        cert3 = Certificate(
            cert_no='CERT-BATCH-003',
            batch_id='BATCH-STATS-002',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2027, 1, 1).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02,
            workflow_status='approved'
        )
        db.session.add_all([cert1, cert2, cert3])
        db.session.commit()

    response = client.get('/api/batches/stats')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'BATCH-STATS-001' in data
    assert 'BATCH-STATS-002' in data
    assert data['BATCH-STATS-001']['total'] == 2
    assert data['BATCH-STATS-001']['draft'] == 1
    assert data['BATCH-STATS-001']['released'] == 1
    assert data['BATCH-STATS-002']['total'] == 1
    assert data['BATCH-STATS-002']['approved'] == 1

def test_config_get_expiry_warning_days(client):
    """测试获取配置的过期预警天数"""
    response = client.get('/api/config/expiry-warning-days')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'expiry_warning_days' in data
    assert isinstance(data['expiry_warning_days'], int)
    assert data['expiry_warning_days'] > 0

def test_config_set_expiry_warning_days(client):
    """测试设置配置的过期预警天数"""
    response = client.put('/api/config/expiry-warning-days',
        data=json.dumps({'days': 60}),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['expiry_warning_days'] == 60

    get_response = client.get('/api/config/expiry-warning-days')
    assert get_response.status_code == 200
    get_data = json.loads(get_response.data)
    assert get_data['expiry_warning_days'] == 60

def test_config_set_expiry_warning_days_invalid(client):
    """测试设置无效的过期预警天数"""
    response = client.put('/api/config/expiry-warning-days',
        data=json.dumps({'days': -1}),
        content_type='application/json'
    )
    assert response.status_code == 400

    response = client.put('/api/config/expiry-warning-days',
        data=json.dumps({'days': 'invalid'}),
        content_type='application/json'
    )
    assert response.status_code == 400

def test_export_by_equipment_with_date_range(client, sample_equipment):
    """测试按设备导出时按到期时间范围筛选"""
    with app.app_context():
        cert1 = Certificate(
            cert_no='CERT-DATE-001',
            batch_id='BATCH-DATE-TEST',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2026, 6, 15).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02
        )
        cert2 = Certificate(
            cert_no='CERT-DATE-002',
            batch_id='BATCH-DATE-TEST',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2026, 6, 30).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02
        )
        db.session.add_all([cert1, cert2])
        db.session.commit()

    response = client.get(f'/api/export/equipment/{sample_equipment}?valid_from=2026-06-14&valid_to=2026-06-20')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 1
    assert data[0]['cert_no'] == 'CERT-DATE-001'

def test_export_by_batch_with_date_range(client, sample_equipment):
    """测试按批次导出时按到期时间范围筛选"""
    with app.app_context():
        cert1 = Certificate(
            cert_no='CERT-BATCH-DATE-001',
            batch_id='BATCH-DATE-FILTER',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2026, 6, 15).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02
        )
        cert2 = Certificate(
            cert_no='CERT-BATCH-DATE-002',
            batch_id='BATCH-DATE-FILTER',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2026, 7, 1).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02
        )
        db.session.add_all([cert1, cert2])
        db.session.commit()

    response = client.get('/api/export/batch/BATCH-DATE-FILTER?valid_to=2026-06-30')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 1
    assert data[0]['cert_no'] == 'CERT-BATCH-DATE-001'


def test_batch_approve_empty_list(client):
    """测试批量审批空列表"""
    response = client.post('/api/certificates/batch/approve',
        data=json.dumps({
            'operator': 'Supervisor1',
            'certificate_ids': []
        }),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'empty' in data['error'].lower()


def test_batch_approve_mixed_states(client, sample_equipment):
    """测试批量审批混合状态证书"""
    cert_ids = []
    with app.app_context():
        for i in range(3):
            cert = Certificate(
                cert_no=f'CERT-BATCH-APPROVE-{int(time.time())}-{i}',
                batch_id='BATCH-APPROVE-TEST',
                equipment_id=sample_equipment,
                calibration_date=datetime(2026, 1, 1).date(),
                valid_until=datetime(2027, 1, 1).date(),
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02
            )
            db.session.add(cert)
            db.session.flush()
            cert_ids.append(cert.id)
        db.session.commit()

    client.post(f'/api/certificates/{cert_ids[0]}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )
    client.post(f'/api/certificates/{cert_ids[0]}/review',
        data=json.dumps({'operator': 'Metrologist1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    client.post(f'/api/certificates/{cert_ids[1]}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )

    response = client.post('/api/certificates/batch/approve',
        data=json.dumps({
            'operator': 'Supervisor1',
            'certificate_ids': cert_ids,
            'decision_basis': 'Batch approval test'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] == 3
    assert data['successful'] == 1
    assert data['failed'] == 2

    successful_results = [r for r in data['results'] if r['success']]
    failed_results = [r for r in data['results'] if not r['success']]
    assert len(successful_results) == 1
    assert len(failed_results) == 2


def test_batch_release_mixed_states(client, sample_equipment):
    """测试批量放行混合状态证书"""
    cert_ids = []
    with app.app_context():
        for i in range(3):
            cert = Certificate(
                cert_no=f'CERT-BATCH-RELEASE-{int(time.time())}-{i}',
                batch_id='BATCH-RELEASE-TEST',
                equipment_id=sample_equipment,
                calibration_date=datetime(2026, 1, 1).date(),
                valid_until=datetime(2027, 1, 1).date(),
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02
            )
            db.session.add(cert)
            db.session.flush()
            cert_ids.append(cert.id)
        db.session.commit()

    for cert_id in cert_ids[:2]:
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

    response = client.post('/api/certificates/batch/release',
        data=json.dumps({
            'operator': 'Operator2',
            'certificate_ids': cert_ids,
            'decision_basis': 'Batch release test'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] == 3
    assert data['successful'] == 2
    assert data['failed'] == 1


def test_batch_release_self_entry_blocked(client, sample_equipment):
    """测试批量放行时录入员不能放行自己录入的证书"""
    cert_ids = []
    with app.app_context():
        cert = Certificate(
            cert_no=f'CERT-SELF-RELEASE-{int(time.time())}',
            batch_id='BATCH-SELF-RELEASE',
            equipment_id=sample_equipment,
            calibration_date=datetime(2026, 1, 1).date(),
            valid_until=datetime(2027, 1, 1).date(),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02
        )
        db.session.add(cert)
        db.session.flush()
        cert_ids.append(cert.id)
        db.session.commit()

    client.post(f'/api/certificates/{cert_ids[0]}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )
    client.post(f'/api/certificates/{cert_ids[0]}/review',
        data=json.dumps({'operator': 'Metrologist1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )
    client.post(f'/api/certificates/{cert_ids[0]}/approve',
        data=json.dumps({'operator': 'Supervisor1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    response = client.post('/api/certificates/batch/release',
        data=json.dumps({
            'operator': 'Operator1',
            'certificate_ids': cert_ids,
            'decision_basis': 'Try to release own entry'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['successful'] == 0
    assert data['failed'] == 1
    assert any('cannot release their own entry' in str(r.get('errors', [])).lower() for r in data['results'])


def test_revert_workflow_success(client, sample_equipment):
    """测试成功撤销工作流变更"""
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

    cert_response = client.get(f'/api/certificates/{cert_id}')
    cert_data = json.loads(cert_response.data)
    assert cert_data['workflow_status'] == 'approved'

    revert_response = client.post(f'/api/certificates/{cert_id}/revert',
        data=json.dumps({
            'operator': 'Admin1',
            'notes': 'Revert to reviewed state'
        }),
        content_type='application/json'
    )
    assert revert_response.status_code == 200
    reverted_data = json.loads(revert_response.data)
    assert reverted_data['workflow_status'] == 'reviewed'


def test_revert_restores_equipment_status(client, sample_equipment):
    """测试撤销时恢复设备状态"""
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
    client.post(f'/api/certificates/{cert_id}/release',
        data=json.dumps({'operator': 'Operator2', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    cert_response = client.get(f'/api/certificates/{cert_id}')
    cert_data = json.loads(cert_response.data)
    equipment_id = cert_data['equipment_id']

    eq_response = client.get(f'/api/equipment/{equipment_id}')
    eq_data = json.loads(eq_response.data)
    assert eq_data['status'] == 'active'

    revert_response = client.post(f'/api/certificates/{cert_id}/revert',
        data=json.dumps({
            'operator': 'Admin1',
            'notes': 'Revert release'
        }),
        content_type='application/json'
    )
    assert revert_response.status_code == 200

    eq_response = client.get(f'/api/equipment/{equipment_id}')
    eq_data = json.loads(eq_response.data)
    assert eq_data['status'] == 'active'


def test_revert_creates_audit_log(client, sample_equipment):
    """测试撤销创建审计日志"""
    cert_id = setup_certificate_for_workflow(client)

    client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )

    revert_response = client.post(f'/api/certificates/{cert_id}/revert',
        data=json.dumps({
            'operator': 'Admin1',
            'notes': 'Revert enter'
        }),
        content_type='application/json'
    )
    assert revert_response.status_code == 200

    audit_response = client.get(f'/api/audit?certificate_id={cert_id}')
    audit_data = json.loads(audit_response.data)

    revert_logs = [log for log in audit_data if log['action'] == 'revert']
    assert len(revert_logs) == 1
    assert revert_logs[0]['operator'] == 'Admin1'
    assert revert_logs[0]['previous_state'] == 'entered'
    assert revert_logs[0]['new_state'] == 'draft'


def test_revert_double_fails(client, sample_equipment):
    """测试重复撤销同一变更失败"""
    cert_id = setup_certificate_for_workflow(client)

    client.post(f'/api/certificates/{cert_id}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )

    revert_response1 = client.post(f'/api/certificates/{cert_id}/revert',
        data=json.dumps({
            'operator': 'Admin1',
            'notes': 'First revert'
        }),
        content_type='application/json'
    )
    assert revert_response1.status_code == 200

    revert_response2 = client.post(f'/api/certificates/{cert_id}/revert',
        data=json.dumps({
            'operator': 'Admin1',
            'notes': 'Second revert'
        }),
        content_type='application/json'
    )
    assert revert_response2.status_code == 400
    data = json.loads(revert_response2.data)
    assert any('no workflow change' in str(err).lower() for err in data['errors'])


def test_revert_draft_fails(client, sample_equipment):
    """测试撤销草稿状态失败"""
    cert_id = setup_certificate_for_workflow(client)

    revert_response = client.post(f'/api/certificates/{cert_id}/revert',
        data=json.dumps({
            'operator': 'Admin1',
            'notes': 'Try to revert draft'
        }),
        content_type='application/json'
    )
    assert revert_response.status_code == 400
    data = json.loads(revert_response.data)
    assert any('no workflow change' in str(err).lower() for err in data['errors'])


def test_revert_nonexistent_certificate(client):
    """测试撤销不存在的证书"""
    revert_response = client.post('/api/certificates/99999/revert',
        data=json.dumps({
            'operator': 'Admin1',
            'notes': 'Try to revert nonexistent'
        }),
        content_type='application/json'
    )
    assert revert_response.status_code == 400
    data = json.loads(revert_response.data)
    assert any('not found' in str(err).lower() for err in data['errors'])


def test_batch_approve_all_success(client, sample_equipment):
    """测试批量审批全部成功"""
    cert_ids = []
    with app.app_context():
        for i in range(3):
            cert = Certificate(
                cert_no=f'CERT-BATCH-ALL-{int(time.time())}-{i}',
                batch_id='BATCH-ALL-TEST',
                equipment_id=sample_equipment,
                calibration_date=datetime(2026, 1, 1).date(),
                valid_until=datetime(2027, 1, 1).date(),
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02
            )
            db.session.add(cert)
            db.session.flush()
            cert_ids.append(cert.id)
        db.session.commit()

    for cert_id in cert_ids:
        client.post(f'/api/certificates/{cert_id}/enter',
            data=json.dumps({'operator': 'Operator1'}),
            content_type='application/json'
        )
        client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({'operator': 'Metrologist1', 'decision_basis': 'OK'}),
            content_type='application/json'
        )

    response = client.post('/api/certificates/batch/approve',
        data=json.dumps({
            'operator': 'Supervisor1',
            'certificate_ids': cert_ids,
            'decision_basis': 'All approved'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] == 3
    assert data['successful'] == 3
    assert data['failed'] == 0


def test_batch_release_all_success(client, sample_equipment):
    """测试批量放行全部成功"""
    cert_ids = []
    with app.app_context():
        for i in range(3):
            cert = Certificate(
                cert_no=f'CERT-BATCH-RELEASE-ALL-{int(time.time())}-{i}',
                batch_id='BATCH-RELEASE-ALL',
                equipment_id=sample_equipment,
                calibration_date=datetime(2026, 1, 1).date(),
                valid_until=datetime(2027, 1, 1).date(),
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02
            )
            db.session.add(cert)
            db.session.flush()
            cert_ids.append(cert.id)
        db.session.commit()

    for cert_id in cert_ids:
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

    response = client.post('/api/certificates/batch/release',
        data=json.dumps({
            'operator': 'Operator2',
            'certificate_ids': cert_ids,
            'decision_basis': 'All released'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] == 3
    assert data['successful'] == 3
    assert data['failed'] == 0


def test_batch_operations_no_rollback_on_failure(client, sample_equipment):
    """测试批量操作失败不影响已成功的记录"""
    cert_ids = []
    with app.app_context():
        for i in range(2):
            cert = Certificate(
                cert_no=f'CERT-NO-ROLLBACK-{int(time.time())}-{i}',
                batch_id='BATCH-NO-ROLLBACK',
                equipment_id=sample_equipment,
                calibration_date=datetime(2026, 1, 1).date(),
                valid_until=datetime(2027, 1, 1).date(),
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02
            )
            db.session.add(cert)
            db.session.flush()
            cert_ids.append(cert.id)
        db.session.commit()

    client.post(f'/api/certificates/{cert_ids[0]}/enter',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )
    client.post(f'/api/certificates/{cert_ids[0]}/review',
        data=json.dumps({'operator': 'Metrologist1', 'decision_basis': 'OK'}),
        content_type='application/json'
    )

    response = client.post('/api/certificates/batch/approve',
        data=json.dumps({
            'operator': 'Supervisor1',
            'certificate_ids': cert_ids,
            'decision_basis': 'Test no rollback'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['successful'] == 1
    assert data['failed'] == 1

    cert0_response = client.get(f'/api/certificates/{cert_ids[0]}')
    cert0_data = json.loads(cert0_response.data)
    assert cert0_data['workflow_status'] == 'approved'
