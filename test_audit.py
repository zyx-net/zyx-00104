import pytest
from app import app, db
from models import Equipment, Certificate, AuditLog, AuditArchive, User, UserRole
from services import AuditService, ConfigService
from datetime import datetime, timedelta, timezone
import json
import os


@pytest.fixture
def sample_equipment_audit(client):
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
def sample_audit_logs_audit(client, sample_equipment_audit):
    with app.app_context():
        for i in range(25):
            log = AuditLog(
                timestamp=datetime.now(timezone.utc) - timedelta(days=i % 10),
                operator='Operator1' if i % 3 == 0 else ('Metrologist1' if i % 3 == 1 else 'Supervisor1'),
                action='import' if i % 4 == 0 else ('enter' if i % 4 == 1 else ('review' if i % 4 == 2 else 'approve')),
                resource_type='certificate',
                resource_id=i + 1,
                equipment_id=sample_equipment_audit,
                certificate_id=i + 1,
                notes=f'Test log {i}'
            )
            db.session.add(log)
        db.session.commit()


def test_audit_query_supervisor_access_all(client, sample_audit_logs_audit):
    response = client.get('/api/audit/search?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'total' in data
    assert data['total'] == 25


def test_audit_query_metrologist_only_own(client, sample_audit_logs_audit):
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


def test_audit_query_pagination(client, sample_audit_logs_audit):
    response = client.get('/api/audit/search?operator=Supervisor1&page=1&per_page=10')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['items']) == 10
    assert data['page'] == 1
    assert data['per_page'] == 10
    assert data['has_next'] == True
    assert data['has_prev'] == False


def test_audit_query_pagination_last_page(client, sample_audit_logs_audit):
    response = client.get('/api/audit/search?operator=Supervisor1&page=3&per_page=10')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['items']) == 5
    assert data['has_next'] == False
    assert data['has_prev'] == True


def test_audit_query_pagination_invalid_page(client, sample_audit_logs_audit):
    response = client.get('/api/audit/search?operator=Supervisor1&page=-1&per_page=10')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['page'] == 1


def test_audit_query_pagination_invalid_per_page(client, sample_audit_logs_audit):
    response = client.get('/api/audit/search?operator=Supervisor1&page=1&per_page=200')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['per_page'] == 20


def test_audit_query_time_filter(client, sample_audit_logs_audit):
    start_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    end_time = datetime.now(timezone.utc).isoformat()
    response = client.get(f'/api/audit/search?operator=Supervisor1&start_time={start_time}&end_time={end_time}')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] <= 25


def test_audit_query_action_filter(client, sample_audit_logs_audit):
    response = client.get('/api/audit/search?operator=Supervisor1&action=import')
    assert response.status_code == 200
    data = json.loads(response.data)
    for item in data['items']:
        assert item['action'] == 'import'


def test_audit_query_target_operator_filter(client, sample_audit_logs_audit):
    response = client.get('/api/audit/search?operator=Supervisor1&target_operator=Operator1')
    assert response.status_code == 200
    data = json.loads(response.data)
    for item in data['items']:
        assert item['operator'] == 'Operator1'


def test_audit_export_supervisor(client, sample_audit_logs_audit):
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


def test_audit_query_logged(client, sample_audit_logs_audit):
    initial_count = AuditLog.query.filter_by(action='audit_query').count()
    client.get('/api/audit/search?operator=Supervisor1&action=import')
    final_count = AuditLog.query.filter_by(action='audit_query').count()
    assert final_count == initial_count + 1


def test_audit_export_logged(client, sample_audit_logs_audit):
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


def test_audit_archive_count_mismatch_protection(client):
    with app.app_context():
        old_log = AuditLog(
            timestamp=datetime.now(timezone.utc) - timedelta(days=100),
            operator='Operator1',
            action='import',
            resource_type='certificate',
            resource_id=777,
            notes='Test count mismatch protection'
        )
        db.session.add(old_log)
        db.session.commit()
        log_id = old_log.id

    with app.app_context():
        archive_service = AuditService()
        
        original_query = AuditArchive.query
        
        class MockQuery:
            def __init__(self, original):
                self._original = original
            
            def filter(self, *args):
                return self
            
            def filter_by(self, **kwargs):
                return self._original.filter_by(**kwargs)
            
            def count(self):
                return 999
        
        AuditArchive.query = MockQuery(AuditArchive.query)
        
        try:
            result = archive_service.archive_old_logs()
            
            assert result['success'] == False
            assert 'Archive verification failed' in result['message'] or 'Archive count mismatch' in str(result['errors'])
            
            assert AuditLog.query.filter_by(id=log_id).count() == 1
            assert AuditArchive.query.filter_by(audit_log_id=log_id).count() == 0
        finally:
            AuditArchive.query = original_query


def test_audit_archive_hash_mismatch_no_data_loss(client):
    with app.app_context():
        old_log = AuditLog(
            timestamp=datetime.now(timezone.utc) - timedelta(days=100),
            operator='Operator1',
            action='import',
            resource_type='certificate',
            resource_id=666,
            notes='Test hash mismatch no data loss'
        )
        db.session.add(old_log)
        db.session.commit()
        log_id = old_log.id
        original_notes = old_log.notes

    with app.app_context():
        archive_service = AuditService()
        
        original_calculate = archive_service._calculate_record_hash
        call_count = [0]
        
        def mock_calculate_hash(log):
            call_count[0] += 1
            if call_count[0] > 2:
                return "intentionally_wrong_hash"
            return original_calculate(log)
        
        archive_service._calculate_record_hash = mock_calculate_hash
        
        result = archive_service.archive_old_logs()
        
        assert result['success'] == False
        assert result['archived_count'] == 0
        
        preserved_log = AuditLog.query.filter_by(id=log_id).first()
        assert preserved_log is not None
        assert preserved_log.notes == original_notes


def test_audit_export_time_range_limit(client, sample_equipment_audit):
    with app.app_context():
        for i in range(10):
            log = AuditLog(
                timestamp=datetime.now(timezone.utc) - timedelta(days=i * 50),
                operator='Supervisor1',
                action='test_action',
                resource_type='certificate',
                resource_id=i + 100,
                equipment_id=sample_equipment_audit,
                notes=f'Time range test log {i}'
            )
            db.session.add(log)
        db.session.commit()

    response = client.get('/api/audit/export?operator=Supervisor1')
    assert response.status_code == 200
    csv_content = response.data.decode('utf-8-sig')
    lines = csv_content.strip().split('\n')
    
    assert len(lines) >= 1


def test_audit_export_time_range_config_respected(client, sample_equipment_audit, test_config):
    with app.app_context():
        log_within_range = AuditLog(
            timestamp=datetime.now(timezone.utc) - timedelta(days=30),
            operator='Supervisor1',
            action='test_within_range',
            resource_type='certificate',
            resource_id=200,
            equipment_id=sample_equipment_audit,
            notes='Log within time range'
        )
        log_outside_range = AuditLog(
            timestamp=datetime.now(timezone.utc) - timedelta(days=400),
            operator='Supervisor1',
            action='test_outside_range',
            resource_type='certificate',
            resource_id=201,
            equipment_id=sample_equipment_audit,
            notes='Log outside time range'
        )
        db.session.add_all([log_within_range, log_outside_range])
        db.session.commit()

    response = client.get('/api/audit/export?operator=Supervisor1')
    assert response.status_code == 200
    csv_content = response.data.decode('utf-8-sig')
    
    assert 'test_within_range' in csv_content
    assert 'test_outside_range' not in csv_content


def test_config_audit_section(client):
    config = ConfigService().get_config()
    assert 'audit' in config
    assert 'retention_days' in config['audit']
    assert 'export_max_rows' in config['audit']
    assert 'export_time_range_days' in config['audit']
    assert 'auto_reload' in config['audit']
    assert 'reload_interval_seconds' in config['audit']
    assert 'archive_time_hour' in config['audit']


def test_audit_config_hot_reload(client):
    original_config = ConfigService()
    original_days = original_config._config.get('audit', {}).get('retention_days', 90)
    
    temp_config = original_config._config.copy()
    temp_config['audit'] = {'retention_days': 30, 'export_max_rows': 5000, 'export_time_range_days': 180, 'auto_reload': True, 'reload_interval_seconds': 1, 'archive_time_hour': 3}
    
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(temp_config, f, indent=2)
    
    import time
    time.sleep(2)
    
    new_config = ConfigService()
    new_config._check_reload()
    new_days = new_config._config.get('audit', {}).get('retention_days', 90)
    
    with open(config_path, 'w', encoding='utf-8') as f:
        original_config._config['audit'] = {'retention_days': 90, 'export_max_rows': 10000, 'export_time_range_days': 365, 'auto_reload': True, 'reload_interval_seconds': 5, 'archive_time_hour': 3}
        json.dump(original_config._config, f, indent=2)
    
    assert new_days == 30
