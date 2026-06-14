import pytest
import tempfile
import os
from app import app, db
from models import Equipment, Certificate, AuditLog, AuditArchive, User, UserRole, WorkflowStatus, CalibrationTask, TaskStatus, TaskType
from services import ConfigService
from datetime import datetime, timedelta, timezone, date
import json

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')


@pytest.fixture(scope='session')
def test_config():
    original_config = None
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            original_config = f.read()
    
    test_config_data = {
        'expiry_warning_days': 30,
        'expiry_check_interval_hours': 24,
        'audit': {
            'retention_days': 90,
            'export_max_rows': 10000,
            'export_time_range_days': 365,
            'auto_reload': True,
            'reload_interval_seconds': 5,
            'archive_time_hour': 3
        },
        'scheduler': {
            'default_priority': 0,
            'urgent_priority': 10,
            'periodic_priority': 5,
            'batch_priority': 3,
            'auto_create_next_periodic': True,
            'default_period_days': 365,
            'task_reminder_days': 7,
            'max_tasks_per_equipment': 1,
            'allow_force_override': True,
            'auto_reload': True,
            'reload_interval_seconds': 5
        },
        'statistics': {
            'export_max_size_mb': 10,
            'default_time_range_days': 90,
            'auto_reload': True,
            'reload_interval_seconds': 5
        },
        'report': {
            'storage_path': './reports',
            'auto_reload': True,
            'reload_interval_seconds': 5,
            'template': {
                'header': '校准证书报告',
                'footer': '计量校准中心'
            },
            'decision_rules': {
                'qualified': {'description': '合格'},
                'limited': {'description': '限用'},
                'unqualified': {'description': '不合格'}
            }
        }
    }
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(test_config_data, f, indent=2)
    
    yield test_config_data
    
    if original_config is not None:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(original_config)
    else:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)


@pytest.fixture(scope='function')
def client(test_config):
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        
        operator1 = User(username='Operator1', role='operator')
        operator2 = User(username='Operator2', role='operator')
        metrologist1 = User(username='Metrologist1', role='metrologist')
        metrologist2 = User(username='Metrologist2', role='metrologist')
        supervisor1 = User(username='Supervisor1', role='supervisor')
        supervisor2 = User(username='Supervisor2', role='supervisor')
        admin1 = User(username='Admin1', role='supervisor')
        db.session.add_all([operator1, operator2, metrologist1, metrologist2, supervisor1, supervisor2, admin1])
        db.session.commit()
        
        config_service = ConfigService()
        config_service._config = test_config.copy()
        
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


@pytest.fixture
def sample_equipment2(client):
    with app.app_context():
        equipment = Equipment(
            equipment_no='EQ-TEST-002',
            equipment_name='Test Equipment 2',
            model_spec='TEST-200',
            manufacturer='Test Corp',
            range_min=0,
            range_max=200,
            unit='V',
            tolerance=0.1,
            location='Lab 2'
        )
        db.session.add(equipment)
        db.session.commit()
        return equipment.id


@pytest.fixture
def sample_users(client):
    return {
        'operator': 'Operator1',
        'operator2': 'Operator2',
        'metrologist': 'Metrologist1',
        'metrologist2': 'Metrologist2',
        'supervisor': 'Supervisor1',
        'supervisor2': 'Supervisor2'
    }


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


@pytest.fixture
def sample_certificate(client, sample_equipment):
    with app.app_context():
        cert = Certificate(
            cert_no='CERT-TEST-001',
            batch_id='BATCH-TEST-001',
            equipment_id=sample_equipment,
            calibration_date=date.today(),
            valid_until=date.today() + timedelta(days=365),
            range_min=0,
            range_max=100,
            unit='V',
            deviation=0.02,
            workflow_status=WorkflowStatus.DRAFT.value
        )
        db.session.add(cert)
        db.session.commit()
        return cert.id


@pytest.fixture
def backup_config():
    backup = None
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            backup = f.read()
    yield
    if backup is not None:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(backup)
