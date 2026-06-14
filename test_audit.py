import pytest
from app import app, db
from models import Equipment, Certificate, AuditLog, AuditArchive, User, UserRole
from services import AuditService, ConfigService
from datetime import datetime, timedelta, timezone
import json
import os

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        operator1 = User(username='Operator1', role='operator')
        metrologist1 = User(username='Metrologist1', role='metrologist')
        supervisor1 = User(username='Supervisor1', role='supervisor')
        db.session.add_all([operator1, metrologist1, supervisor1])
        db.session.commit()
        
        config_service = ConfigService()
        if config_service._config is None:
            config_service._config = {
                'expiry_warning_days': 30,
                'expiry_check_interval_hours': 24,
                'audit': {
                    'retention_days': 90,
                    'export_max_rows': 10000,
                    'auto_reload': True,
                    'reload_interval_seconds': 5,
                    'archive_time_hour': 3
                }
            }
        
        yield app.test_client()
        db.session.remove()
        db.drop_all()

@pytest.fixture
def sample_equipment(client):
    with app.app_context():
        equipment = Equipment(
            equipment_no='EQ-TEST-AUDIT',
            equipment_name='Test Equipment',
            range_min=0,
            range_max=100,
            unit='V',
            tolerance=0.05
        )
        db.session.add(equipment)
        db.session.commit()
        return equipment.id

@pytest.fixture
def sample_audit_logs(client, sample_equipment):
    with app.app_context():
        for i in range(25):
            log = AuditLog(
                timestamp=datetime.now(timezone.utc) - timedelta(days=i % 10),
                operator='Operator1' if i % 3 == 0 else ('Metrologist1' if i % 3 == 1 else 'Supervisor1'),
                action='import' if i % 4 == 0 else ('enter' if i % 4 == 1 else ('review' if i % 4 == 2 else 'approve')),
                resource_type='certificate',
                resource_id=i + 1,
                equipment_id=sample_equipment,
                certificate_id=i + 1,
                notes=f'Test log {i}'
            )
            db.session.add(log)
        db.session.commit()

def test_audit_query_supervisor_access_all(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'total' in data
    assert data['total'] == 25

def test_audit_query_metrologist_only_own(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Metrologist1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] <= 25
    for item in data['items']:
        assert item['operator'] == 'Metrologist1'

def test_audit_query_operator_denied(client):
    response = client.get('/api/audit/search?operator=Operator1')
    assert response.status_code == 403
    data = json.loads(response.data)
    assert 'error' in data
    assert 'requires' in data['error']

def test_audit_query_pagination(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Supervisor1&page=1&per_page=10')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['items']) == 10
    assert data['page'] == 1
    assert data['per_page'] == 10
    assert data['has_next'] == True
    assert data['has_prev'] == False

def test_audit_query_pagination_last_page(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Supervisor1&page=3&per_page=10')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['items']) == 5
    assert data['has_next'] == False
    assert data['has_prev'] == True

def test_audit_query_pagination_invalid_page(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Supervisor1&page=-1&per_page=10')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['page'] == 1

def test_audit_query_pagination_invalid_per_page(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Supervisor1&page=1&per_page=200')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['per_page'] == 20

def test_audit_query_time_filter(client, sample_audit_logs):
    start_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    end_time = datetime.now(timezone.utc).isoformat()
    response = client.get(f'/api/audit/search?operator=Supervisor1&start_time={start_time}&end_time={end_time}')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] <= 25

def test_audit_query_action_filter(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Supervisor1&action=import')
    assert response.status_code == 200
    data = json.loads(response.data)
    for item in data['items']:
        assert item['action'] == 'import'

def test_audit_query_target_operator_filter(client, sample_audit_logs):
    response = client.get('/api/audit/search?operator=Supervisor1&target_operator=Operator1')
    assert response.status_code == 200
    data = json.loads(response.data)
    for item in data['items']:
        assert item['operator'] == 'Operator1'

def test_audit_export_supervisor(client, sample_audit_logs):
    response = client.get('/api/audit/export?operator=Supervisor1')
    assert response.status_code == 200
    assert 'text/csv' in response.content_type
    csv_content = response.data.decode('utf-8-sig')
    assert '时间' in csv_content
    assert '操作人' in csv_content
    assert '角色' in csv_content
    assert '操作类型' in csv_content
    assert '目标对象' in csv_content
    assert '变更摘要' in csv_content

def test_audit_export_metrologist_denied(client):
    response = client.get('/api/audit/export?operator=Metrologist1')
    assert response.status_code == 403

def test_audit_export_operator_denied(client):
    response = client.get('/api/audit/export?operator=Operator1')
    assert response.status_code == 403

def test_audit_query_logged(client, sample_audit_logs):
    initial_count = AuditLog.query.filter_by(action='audit_query').count()
    client.get('/api/audit/search?operator=Supervisor1&action=import')
    final_count = AuditLog.query.filter_by(action='audit_query').count()
    assert final_count == initial_count + 1

def test_audit_export_logged(client, sample_audit_logs):
    initial_count = AuditLog.query.filter_by(action='audit_export').count()
    client.get('/api/audit/export?operator=Supervisor1')
    final_count = AuditLog.query.filter_by(action='audit_export').count()
    assert final_count == initial_count + 1

def test_audit_archive_success(client):
    log_id = None
    with app.app_context():
        old_log = AuditLog(
            timestamp=datetime.now(timezone.utc) - timedelta(days=100),
            operator='Operator1',
            action='import',
            resource_type='certificate',
            resource_id=999,
            notes='Old log for archive'
        )
        db.session.add(old_log)
        db.session.commit()
        log_id = old_log.id

    response = client.post('/api/audit/archive',
        data=json.dumps({'operator': 'Supervisor1'}),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    assert data['archived_count'] == 1

    with app.app_context():
        assert AuditLog.query.filter_by(resource_id=999).count() == 0
        assert AuditArchive.query.filter_by(audit_log_id=log_id).count() == 1

def test_audit_archive_no_old_logs(client):
    response = client.post('/api/audit/archive',
        data=json.dumps({'operator': 'Supervisor1'}),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    assert data['archived_count'] == 0
    assert data['message'] == 'No logs to archive'

def test_audit_archive_permission_denied(client):
    response = client.post('/api/audit/archive',
        data=json.dumps({'operator': 'Operator1'}),
        content_type='application/json'
    )
    assert response.status_code == 403

def test_audit_archive_hash_verification(client):
    with app.app_context():
        old_log = AuditLog(
            timestamp=datetime.now(timezone.utc) - timedelta(days=100),
            operator='Operator1',
            action='import',
            resource_type='certificate',
            resource_id=888,
            notes='Test hash verification'
        )
        db.session.add(old_log)
        db.session.commit()

        archive_service = AuditService()
        result = archive_service.archive_old_logs()
        
        assert result['success'] == True
        assert result['archived_count'] == 1

        archived = AuditArchive.query.filter_by(audit_log_id=old_log.id).first()
        expected_hash = archive_service._calculate_record_hash(old_log)
        assert archived.check_hash == expected_hash

def test_config_audit_section(client):
    config = ConfigService().get_config()
    assert 'audit' in config
    assert 'retention_days' in config['audit']
    assert 'export_max_rows' in config['audit']
    assert 'auto_reload' in config['audit']
    assert 'reload_interval_seconds' in config['audit']
    assert 'archive_time_hour' in config['audit']

def test_audit_config_hot_reload(client):
    original_config = ConfigService()
    original_days = original_config._config.get('audit', {}).get('retention_days', 90)
    
    temp_config = original_config._config.copy()
    temp_config['audit'] = {'retention_days': 30, 'export_max_rows': 5000, 'auto_reload': True, 'reload_interval_seconds': 1, 'archive_time_hour': 3}
    
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(temp_config, f, indent=2)
    
    import time
    time.sleep(2)
    
    new_config = ConfigService()
    new_config._check_reload()
    new_days = new_config._config.get('audit', {}).get('retention_days', 90)
    
    with open(config_path, 'w', encoding='utf-8') as f:
        original_config._config['audit'] = {'retention_days': 90, 'export_max_rows': 10000, 'auto_reload': True, 'reload_interval_seconds': 5, 'archive_time_hour': 3}
        json.dump(original_config._config, f, indent=2)
    
    assert new_days == 30
