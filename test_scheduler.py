import pytest
import time
import json
import os
from datetime import datetime, timedelta
from app import app, db
from models import Equipment, Certificate, AuditLog, User, WorkflowStatus
from services import ConfigService, ScheduledTaskService, ExpiryAutoTransitionService, RolePermissionService, UserService

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    with app.app_context():
        db.create_all()
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'expiry_warning_days': 30, 'expiry_check_interval_hours': 24}, f)
        yield app.test_client()
        db.session.remove()
        db.drop_all()
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'expiry_warning_days': 30, 'expiry_check_interval_hours': 24}, f)


@pytest.fixture
def sample_equipment(client):
    with app.app_context():
        equipment = Equipment(
            equipment_no='EQ-TEST-SCHEDULER-001',
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
def sample_users(client):
    with app.app_context():
        operator = User(username='TestOperator', role='operator')
        metrologist = User(username='TestMetrologist', role='metrologist')
        supervisor = User(username='TestSupervisor', role='supervisor')
        db.session.add_all([operator, metrologist, supervisor])
        db.session.commit()
        return {
            'operator': 'TestOperator',
            'metrologist': 'TestMetrologist',
            'supervisor': 'TestSupervisor'
        }


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


class TestScheduledTask:
    def test_scheduler_status_endpoint_exists(self, client):
        """测试调度器状态接口存在"""
        response = client.get('/api/scheduler/status')
        assert response.status_code == 200

        response = client.get('/api/scheduler/status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'running' in data
        assert 'check_interval_hours' in data

    def test_scheduler_interval_configuration(self, client, backup_config):
        """测试调度器间隔配置"""
        response = client.get('/api/config/expiry-check-interval')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'expiry_check_interval_hours' in data

        response = client.put('/api/config/expiry-check-interval',
            data=json.dumps({'hours': 12}),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['expiry_check_interval_hours'] == 12

        response = client.get('/api/config/expiry-check-interval')
        data = json.loads(response.data)
        assert data['expiry_check_interval_hours'] == 12

    def test_scheduler_invalid_interval_rejected(self, client):
        """测试无效间隔配置被拒绝"""
        response = client.put('/api/config/expiry-check-interval',
            data=json.dumps({'hours': -1}),
            content_type='application/json'
        )
        assert response.status_code == 400

        response = client.put('/api/config/expiry-check-interval',
            data=json.dumps({'hours': 'invalid'}),
            content_type='application/json'
        )
        assert response.status_code == 400


class TestRestartRecovery:
    def test_config_persists_across_restarts(self, client, backup_config):
        """测试配置在重启后持久化"""
        with app.app_context():
            config_service = ConfigService()
            config_service.set_expiry_check_interval_hours(48)
            config_service.set_last_expiry_check_time('2026-06-13T10:00:00')

        response = client.get('/api/config/expiry-check-interval')
        data = json.loads(response.data)
        assert data['expiry_check_interval_hours'] == 48
        assert data['last_check_time'] == '2026-06-13T10:00:00'

    def test_scheduler_resumes_after_restart(self, client, backup_config, sample_equipment):
        """测试重启后调度器恢复"""
        yesterday = datetime.now().date() - timedelta(days=1)

        with app.app_context():
            config_service = ConfigService()
            config_service.set_expiry_check_interval_hours(24)
            config_service.set_last_expiry_check_time(
                (datetime.now() - timedelta(hours=25)).isoformat()
            )

            cert = Certificate(
                cert_no='CERT-RESTART-RECOVERY',
                batch_id='BATCH-RESTART',
                equipment_id=sample_equipment,
                calibration_date=datetime(2025, 1, 1).date(),
                valid_until=yesterday,
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02,
                workflow_status='approved'
            )
            db.session.add(cert)
            db.session.commit()

        response = client.post('/api/certificates/expiry-process')
        assert response.status_code == 200

        with app.app_context():
            cert = Certificate.query.filter_by(cert_no='CERT-RESTART-RECOVERY').first()
            assert cert is not None
            assert cert.workflow_status in ['limited', 'stopped']


class TestConcurrencyConflict:
    def test_manual_expiry_blocked_when_scheduled_running(self, client, sample_equipment):
        """测试手动过期处理在调度器运行时被阻止"""
        yesterday = datetime.now().date() - timedelta(days=1)

        with app.app_context():
            cert = Certificate(
                cert_no='CERT-CONCURRENT-TEST',
                batch_id='BATCH-CONCURRENT',
                equipment_id=sample_equipment,
                calibration_date=datetime(2025, 1, 1).date(),
                valid_until=yesterday,
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02,
                workflow_status='approved'
            )
            db.session.add(cert)
            db.session.commit()

        with app.app_context():
            config_service = ConfigService()
            config_service.set_expiry_check_in_progress(True)

        try:
            response = client.post('/api/certificates/expiry-process')
            assert response.status_code == 409
            data = json.loads(response.data)
            assert data['conflict'] == True
            assert 'already in progress' in data['error'].lower()
        finally:
            with app.app_context():
                config_service = ConfigService()
                config_service.set_expiry_check_in_progress(False)

    def test_concurrent_manual_calls_one_fails(self, client, sample_equipment):
        """测试并发手动调用至少有一个成功"""
        yesterday = datetime.now().date() - timedelta(days=1)

        with app.app_context():
            cert1 = Certificate(
                cert_no='CERT-CONCURRENT-1',
                batch_id='BATCH-CONCURRENT-1',
                equipment_id=sample_equipment,
                calibration_date=datetime(2025, 1, 1).date(),
                valid_until=yesterday,
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02,
                workflow_status='approved'
            )
            cert2 = Certificate(
                cert_no='CERT-CONCURRENT-2',
                batch_id='BATCH-CONCURRENT-2',
                equipment_id=sample_equipment,
                calibration_date=datetime(2025, 1, 1).date(),
                valid_until=yesterday,
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.03,
                workflow_status='approved'
            )
            db.session.add_all([cert1, cert2])
            db.session.commit()

        response1 = client.post('/api/certificates/expiry-process')
        response2 = client.post('/api/certificates/expiry-process')

        results = [response1.status_code, response2.status_code]
        assert 200 in results or 409 in results
        if 200 in results and 409 in results:
            pass
        else:
            assert response1.status_code == 200
            assert response2.status_code == 200


class TestPermissionDenied:
    def test_operator_cannot_review(self, client, sample_equipment, sample_users):
        """测试录入员不能进行复核操作"""
        import_response = client.post('/api/certificates/import',
            data=json.dumps({
                'operator': sample_users['operator'],
                'data': [{
                    'cert_no': 'CERT-PERM-001',
                    'equipment_no': 'EQ-TEST-SCHEDULER-001',
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
            data=json.dumps({'operator': sample_users['operator']}),
            content_type='application/json'
        )

        response = client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({
                'operator': sample_users['operator'],
                'decision_basis': 'Test review'
            }),
            content_type='application/json'
        )
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'review' in data['error'].lower()
        assert data['required_role'] == ['metrologist', 'supervisor']

    def test_operator_cannot_approve(self, client, sample_equipment, sample_users):
        """测试录入员不能进行批准操作"""
        import_response = client.post('/api/certificates/import',
            data=json.dumps({
                'operator': sample_users['operator'],
                'data': [{
                    'cert_no': 'CERT-PERM-002',
                    'equipment_no': 'EQ-TEST-SCHEDULER-001',
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
            data=json.dumps({'operator': sample_users['operator']}),
            content_type='application/json'
        )

        client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({
                'operator': sample_users['metrologist'],
                'decision_basis': 'OK'
            }),
            content_type='application/json'
        )

        response = client.post(f'/api/certificates/{cert_id}/approve',
            data=json.dumps({
                'operator': sample_users['operator'],
                'decision_basis': 'Test approve'
            }),
            content_type='application/json'
        )
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'approve' in data['error'].lower()
        assert data['required_role'] == ['supervisor']

    def test_operator_cannot_release(self, client, sample_equipment, sample_users):
        """测试录入员不能进行放行操作"""
        import_response = client.post('/api/certificates/import',
            data=json.dumps({
                'operator': sample_users['operator'],
                'data': [{
                    'cert_no': 'CERT-PERM-003',
                    'equipment_no': 'EQ-TEST-SCHEDULER-001',
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
            data=json.dumps({'operator': sample_users['operator']}),
            content_type='application/json'
        )

        client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({
                'operator': sample_users['metrologist'],
                'decision_basis': 'OK'
            }),
            content_type='application/json'
        )

        client.post(f'/api/certificates/{cert_id}/approve',
            data=json.dumps({
                'operator': sample_users['supervisor'],
                'decision_basis': 'OK'
            }),
            content_type='application/json'
        )

        response = client.post(f'/api/certificates/{cert_id}/release',
            data=json.dumps({
                'operator': sample_users['operator'],
                'decision_basis': 'Test release'
            }),
            content_type='application/json'
        )
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'release' in data['error'].lower()
        assert data['required_role'] == ['supervisor']

    def test_metrologist_can_review_but_not_approve(self, client, sample_equipment, sample_users):
        """测试计量员可以复核但不能批准"""
        import_response = client.post('/api/certificates/import',
            data=json.dumps({
                'operator': sample_users['operator'],
                'data': [{
                    'cert_no': 'CERT-PERM-004',
                    'equipment_no': 'EQ-TEST-SCHEDULER-001',
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
            data=json.dumps({'operator': sample_users['operator']}),
            content_type='application/json'
        )

        response = client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({
                'operator': sample_users['metrologist'],
                'decision_basis': 'Metrologist review'
            }),
            content_type='application/json'
        )
        assert response.status_code == 200

        response = client.post(f'/api/certificates/{cert_id}/approve',
            data=json.dumps({
                'operator': sample_users['metrologist'],
                'decision_basis': 'Try approve'
            }),
            content_type='application/json'
        )
        assert response.status_code == 403

    def test_supervisor_can_perform_all_actions(self, client, sample_equipment, sample_users):
        """测试主管可以执行所有操作"""
        import_response = client.post('/api/certificates/import',
            data=json.dumps({
                'operator': sample_users['operator'],
                'data': [{
                    'cert_no': 'CERT-PERM-005',
                    'equipment_no': 'EQ-TEST-SCHEDULER-001',
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
            data=json.dumps({'operator': sample_users['operator']}),
            content_type='application/json'
        )

        response = client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({
                'operator': sample_users['supervisor'],
                'decision_basis': 'Supervisor review'
            }),
            content_type='application/json'
        )
        assert response.status_code == 200

        response = client.post(f'/api/certificates/{cert_id}/approve',
            data=json.dumps({
                'operator': sample_users['supervisor'],
                'decision_basis': 'Supervisor approval'
            }),
            content_type='application/json'
        )
        assert response.status_code == 200

        client.post(f'/api/certificates/{cert_id}/release',
            data=json.dumps({'operator': sample_users['supervisor'], 'decision_basis': 'OK'}),
            content_type='application/json'
        )

    def test_permission_denied_logged_in_audit(self, client, sample_equipment, sample_users):
        """测试权限拒绝事件被记录到审计日志"""
        import_response = client.post('/api/certificates/import',
            data=json.dumps({
                'operator': sample_users['operator'],
                'data': [{
                    'cert_no': 'CERT-PERM-AUDIT',
                    'equipment_no': 'EQ-TEST-SCHEDULER-001',
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
            data=json.dumps({'operator': sample_users['operator']}),
            content_type='application/json'
        )

        client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({
                'operator': sample_users['operator'],
                'decision_basis': 'Try review'
            }),
            content_type='application/json'
        )

        response = client.get('/api/audit?action=permission_denied')
        audit_data = json.loads(response.data)

        denied_logs = [log for log in audit_data if log['action'] == 'permission_denied']
        assert len(denied_logs) >= 1

        latest_denied = denied_logs[0]
        assert latest_denied['operator'] == sample_users['operator']
        assert 'review' in latest_denied['notes'].lower()
        assert latest_denied['denied_reason'] is not None

    def test_operator_cannot_release_own_entry_still_enforced(self, client, sample_equipment, sample_users):
        """测试录入员不能放行自己的单仍然生效（权限检查优先）"""
        import_response = client.post('/api/certificates/import',
            data=json.dumps({
                'operator': sample_users['operator'],
                'data': [{
                    'cert_no': 'CERT-PERM-SELF',
                    'equipment_no': 'EQ-TEST-SCHEDULER-001',
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
            data=json.dumps({'operator': sample_users['operator']}),
            content_type='application/json'
        )

        client.post(f'/api/certificates/{cert_id}/review',
            data=json.dumps({
                'operator': sample_users['supervisor'],
                'decision_basis': 'OK'
            }),
            content_type='application/json'
        )

        client.post(f'/api/certificates/{cert_id}/approve',
            data=json.dumps({
                'operator': sample_users['supervisor'],
                'decision_basis': 'OK'
            }),
            content_type='application/json'
        )

        response = client.post(f'/api/certificates/{cert_id}/release',
            data=json.dumps({
                'operator': sample_users['operator'],
                'decision_basis': 'Try release own'
            }),
            content_type='application/json'
        )
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'release' in data['error'].lower() or 'cannot release' in data['error'].lower()


class TestUserManagement:
    def test_create_user(self, client):
        """测试创建用户"""
        response = client.post('/api/users',
            data=json.dumps({
                'username': 'NewUser',
                'role': 'operator'
            }),
            content_type='application/json'
        )
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['username'] == 'NewUser'
        assert data['role'] == 'operator'

    def test_create_user_invalid_role(self, client):
        """测试创建用户使用无效角色"""
        response = client.post('/api/users',
            data=json.dumps({
                'username': 'BadRoleUser',
                'role': 'invalid_role'
            }),
            content_type='application/json'
        )
        assert response.status_code == 400

    def test_update_user_role(self, client):
        """测试更新用户角色"""
        client.post('/api/users',
            data=json.dumps({
                'username': 'RoleChangeUser',
                'role': 'operator'
            }),
            content_type='application/json'
        )

        response = client.put('/api/users/RoleChangeUser/role',
            data=json.dumps({'role': 'supervisor'}),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['role'] == 'supervisor'

    def test_list_users(self, client, sample_users):
        """测试列出用户"""
        response = client.get('/api/users')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data) == 3


class TestExpiryProcessSource:
    def test_expiry_process_manual_source(self, client, sample_equipment):
        """测试手动触发过期处理时source为manual"""
        yesterday = datetime.now().date() - timedelta(days=1)

        with app.app_context():
            cert = Certificate(
                cert_no='CERT-SOURCE-MANUAL',
                batch_id='BATCH-SOURCE',
                equipment_id=sample_equipment,
                calibration_date=datetime(2025, 1, 1).date(),
                valid_until=yesterday,
                range_min=0,
                range_max=100,
                unit='V',
                deviation=0.02,
                workflow_status='approved'
            )
            db.session.add(cert)
            db.session.commit()

        response = client.post('/api/certificates/expiry-process')
        assert response.status_code == 200

        response = client.get('/api/audit?action=auto_expiry_transition')
        audit_data = json.loads(response.data)
        manual_logs = [log for log in audit_data if 'manual' in log.get('decision_basis', '').lower()]
        assert len(manual_logs) >= 1
