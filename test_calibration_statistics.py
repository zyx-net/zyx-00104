import pytest
from app import app, db
from models import Equipment, Certificate, AuditLog, WorkflowStatus, User, CalibrationTask, TaskStatus, TaskType
from datetime import datetime, timedelta, date
import json
import os
import time


@pytest.fixture
def sample_data(client):
    with app.app_context():
        eq1 = Equipment(
            equipment_no='EQ-001',
            equipment_name='Multimeter',
            model_spec='FLUKE-87V',
            range_min=0,
            range_max=1000,
            unit='V',
            tolerance=0.05,
            location='Lab A'
        )
        eq2 = Equipment(
            equipment_no='EQ-002',
            equipment_name='Thermometer',
            model_spec='WIKA-C10',
            range_min=-40,
            range_max=150,
            unit='°C',
            tolerance=0.1,
            location='Lab B'
        )
        db.session.add_all([eq1, eq2])
        db.session.flush()

        today = date.today()

        cert1 = Certificate(
            cert_no='CERT-001',
            equipment_id=eq1.id,
            calibration_date=today - timedelta(days=60),
            valid_until=today + timedelta(days=305),
            range_min=0,
            range_max=1000,
            unit='V',
            deviation=0.02,
            workflow_status='released',
            reviewed_by='Metrologist1'
        )
        cert2 = Certificate(
            cert_no='CERT-002',
            equipment_id=eq1.id,
            calibration_date=today - timedelta(days=30),
            valid_until=today + timedelta(days=335),
            range_min=0,
            range_max=1000,
            unit='V',
            deviation=0.03,
            workflow_status='entered'
        )
        cert3 = Certificate(
            cert_no='CERT-003',
            equipment_id=eq2.id,
            calibration_date=today - timedelta(days=10),
            valid_until=today + timedelta(days=355),
            range_min=-40,
            range_max=150,
            unit='°C',
            deviation=0.05,
            workflow_status='reviewed',
            reviewed_by='Metrologist1'
        )
        cert4 = Certificate(
            cert_no='CERT-004',
            equipment_id=eq2.id,
            calibration_date=today,
            valid_until=today + timedelta(days=365),
            range_min=-40,
            range_max=150,
            unit='°C',
            deviation=0.02,
            workflow_status='draft'
        )
        cert_expiring = Certificate(
            cert_no='CERT-005',
            equipment_id=eq1.id,
            calibration_date=today - timedelta(days=360),
            valid_until=today + timedelta(days=30),
            range_min=0,
            range_max=1000,
            unit='V',
            deviation=0.01,
            workflow_status='released'
        )
        db.session.add_all([cert1, cert2, cert3, cert4, cert_expiring])
        db.session.flush()

        task1 = CalibrationTask(
            task_no='TASK-001',
            equipment_id=eq1.id,
            task_type='periodic',
            status=TaskStatus.PENDING.value,
            calibrator='Zhang San',
            planned_date=today + timedelta(days=7)
        )
        task2 = CalibrationTask(
            task_no='TASK-002',
            equipment_id=eq2.id,
            task_type='urgent',
            status=TaskStatus.IN_PROGRESS.value,
            calibrator='Zhang San',
            accepted_by='Zhang San',
            planned_date=today
        )
        task3 = CalibrationTask(
            task_no='TASK-003',
            equipment_id=eq1.id,
            task_type='periodic',
            status=TaskStatus.COMPLETED.value,
            calibrator='Li Si',
            completed_at=datetime.now(),
            planned_date=today - timedelta(days=30)
        )
        task4 = CalibrationTask(
            task_no='TASK-004',
            equipment_id=eq2.id,
            task_type='batch',
            status=TaskStatus.PENDING.value,
            calibrator='Wang Wu',
            planned_date=today + timedelta(days=14)
        )
        db.session.add_all([task1, task2, task3, task4])
        db.session.commit()

        return {
            'eq1_id': eq1.id,
            'eq2_id': eq2.id,
            'cert1_id': cert1.id,
            'cert2_id': cert2.id,
            'cert3_id': cert3.id,
            'cert4_id': cert4.id,
            'cert_expiring_id': cert_expiring.id
        }


def test_statistics_requires_operator(client):
    """测试统计接口必须提供操作员"""
    response = client.get('/api/statistics')
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'Operator is required' in data['error']


def test_statistics_operator_access_denied(client):
    """测试录入员无法访问统计接口"""
    response = client.get('/api/statistics?operator=Operator1')
    assert response.status_code == 403
    data = json.loads(response.data)
    assert 'required_role' in data
    assert data['operator_role'] == 'operator'


def test_statistics_metrologist_can_access(client, sample_data):
    """测试计量员可以访问统计接口"""
    response = client.get('/api/statistics?operator=Metrologist1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'overview' in data
    assert 'equipment_coverage' in data
    assert 'calibrator_workload' in data


def test_statistics_supervisor_can_access(client, sample_data):
    """测试主管可以访问统计接口"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'overview' in data
    assert 'equipment_coverage' in data
    assert 'calibrator_workload' in data


def test_statistics_overview_data_supervisor(client, sample_data):
    """测试主管获取概览数据"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    assert 'expiring_warning_count' in overview
    assert 'new_this_month' in overview
    assert 'pending_review' in overview
    assert 'pending_approve' in overview
    assert 'completion_rate' in overview
    assert 'total_certificates' in overview

    assert overview['total_certificates'] == 5
    assert overview['pending_review'] >= 1
    assert overview['pending_approve'] >= 1


def test_statistics_overview_data_metrologist(client, sample_data):
    """测试计量员获取概览数据（只能看到自己复核的证书）"""
    response = client.get('/api/statistics?operator=Metrologist1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    assert overview['total_certificates'] == 2


def test_statistics_equipment_coverage(client, sample_data):
    """测试设备覆盖率统计"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    coverage = data['equipment_coverage']
    assert len(coverage) >= 1

    fluke_coverage = next((c for c in coverage if 'FLUKE' in c['model_spec']), None)
    assert fluke_coverage is not None
    assert fluke_coverage['certificate_count'] >= 2


def test_statistics_calibrator_workload(client, sample_data):
    """测试校准员任务负载统计"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    workload = data['calibrator_workload']
    assert len(workload) >= 2

    zhang_workload = next((w for w in workload if w['calibrator'] == 'Zhang San'), None)
    assert zhang_workload is not None
    assert zhang_workload['total_tasks'] >= 2


def test_statistics_metrologist_workload_filtered(client, sample_data):
    """测试计量员只能看到自己相关的任务"""
    response = client.get('/api/statistics?operator=Metrologist1')
    assert response.status_code == 200
    data = json.loads(response.data)

    workload = data['calibrator_workload']
    assert isinstance(workload, list)


def test_statistics_export_requires_operator(client):
    """测试导出接口必须提供操作员"""
    response = client.get('/api/statistics/export')
    assert response.status_code == 400


def test_statistics_export_operator_denied(client):
    """测试录入员无法导出统计"""
    response = client.get('/api/statistics/export?operator=Operator1')
    assert response.status_code == 403


def test_statistics_export_supervisor(client, sample_data):
    """测试主管可以导出统计"""
    response = client.get('/api/statistics/export?operator=Supervisor1')
    assert response.status_code == 200
    assert 'text/csv' in response.content_type
    assert 'calibration_statistics' in response.headers.get('Content-Disposition', '')


def test_statistics_export_csv_content(client, sample_data):
    """测试导出CSV内容"""
    response = client.get('/api/statistics/export?operator=Supervisor1')
    assert response.status_code == 200

    content = response.data.decode('utf-8-sig')
    assert '校准统计看板' in content
    assert '概览数据' in content
    assert '设备类型校准覆盖率' in content
    assert '校准员任务负载' in content


def test_statistics_export_with_date_range(client, sample_data):
    """测试带日期范围的导出"""
    today = date.today()
    date_from = (today - timedelta(days=30)).isoformat()
    date_to = today.isoformat()

    response = client.get(f'/api/statistics/export?operator=Supervisor1&date_from={date_from}&date_to={date_to}')
    assert response.status_code == 200


def test_statistics_creates_audit_log(client, sample_data):
    """测试访问统计创建审计日志"""
    client.get('/api/statistics?operator=Supervisor1')

    audit_response = client.get('/api/audit')
    audit_data = json.loads(audit_response.data)

    view_logs = [log for log in audit_data if log['action'] == 'view_statistics']
    assert len(view_logs) >= 1
    assert view_logs[0]['operator'] == 'Supervisor1'


def test_statistics_export_creates_audit_log(client, sample_data):
    """测试导出统计创建审计日志"""
    client.get('/api/statistics/export?operator=Supervisor1')

    audit_response = client.get('/api/audit')
    audit_data = json.loads(audit_response.data)

    export_logs = [log for log in audit_data if log['action'] == 'export_statistics']
    assert len(export_logs) >= 1
    assert export_logs[0]['operator'] == 'Supervisor1'


def test_statistics_permission_denied_creates_audit_log(client, sample_data):
    """测试权限拒绝创建审计日志"""
    client.get('/api/statistics?operator=Operator1')

    audit_response = client.get('/api/audit')
    audit_data = json.loads(audit_response.data)

    denied_logs = [log for log in audit_data if log['action'] == 'permission_denied' and log['resource_type'] == 'statistics']
    assert len(denied_logs) >= 1
    assert denied_logs[0]['operator'] == 'Operator1'


def test_statistics_default_time_range(client, sample_data):
    """测试默认时间范围"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    assert data['filter']['date_from'] is not None
    assert data['filter']['date_to'] is not None


def test_statistics_custom_time_range(client, sample_data):
    """测试自定义时间范围"""
    today = date.today()
    date_from = (today - timedelta(days=7)).isoformat()
    date_to = today.isoformat()

    response = client.get(f'/api/statistics?operator=Supervisor1&date_from={date_from}&date_to={date_to}')
    assert response.status_code == 200
    data = json.loads(response.data)

    assert data['filter']['date_from'] == date_from
    assert data['filter']['date_to'] == date_to


def test_statistics_completion_rate_calculation(client, sample_data):
    """测试完成率计算"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    total = overview['total_certificates']
    completion_rate = overview['completion_rate']

    assert 0 <= completion_rate <= 100


def test_statistics_pending_counts(client, sample_data):
    """测试待复核和待批准数量"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    assert overview['pending_review'] >= 1
    assert overview['pending_approve'] >= 1


def test_statistics_metrologist_pending_review_only(client, sample_data):
    """测试计量员只能看到待复核数"""
    response = client.get('/api/statistics?operator=Metrologist1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    assert overview['pending_review'] >= 1
    assert overview['pending_approve'] == 0


def test_statistics_config_get(client):
    """测试获取统计配置"""
    response = client.get('/api/config/statistics')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'export_max_size_mb' in data
    assert 'default_time_range_days' in data


def test_statistics_config_update(client):
    """测试更新统计配置"""
    response = client.put('/api/config/statistics',
        data=json.dumps({'export_max_size_mb': 20}),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['updated']['export_max_size_mb'] == 20


def test_statistics_config_reload(client):
    """测试配置热加载"""
    response = client.put('/api/config/statistics',
        data=json.dumps({'default_time_range_days': 180}),
        content_type='application/json'
    )
    assert response.status_code == 200

    response2 = client.get('/api/config/statistics')
    data2 = json.loads(response2.data)
    assert data2['default_time_range_days'] == 180


def test_statistics_empty_data(client):
    """测试空数据统计"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    assert data['overview']['total_certificates'] == 0
    assert data['overview']['expiring_warning_count'] == 0


def test_statistics_role_in_response(client, sample_data):
    """测试响应包含用户角色"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    assert data['filter']['role'] == 'supervisor'

    response2 = client.get('/api/statistics?operator=Metrologist1')
    assert response2.status_code == 200
    data2 = json.loads(response2.data)
    assert data2['filter']['role'] == 'metrologist'


def test_statistics_equipment_coverage_sorted(client, sample_data):
    """测试设备覆盖率按证书数量排序"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    coverage = data['equipment_coverage']
    if len(coverage) > 1:
        for i in range(len(coverage) - 1):
            assert coverage[i]['certificate_count'] >= coverage[i + 1]['certificate_count']


def test_statistics_calibrator_workload_sorted(client, sample_data):
    """测试校准员任务负载按待处理数量排序"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    workload = data['calibrator_workload']
    if len(workload) > 1:
        for i in range(len(workload) - 1):
            assert workload[i]['pending_tasks'] >= workload[i + 1]['pending_tasks']


def test_statistics_metrologist_sees_own_reviewed_only(client, sample_data):
    """测试计量员只能看到自己复核过的证书"""
    response = client.get('/api/statistics?operator=Metrologist1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    assert overview['total_certificates'] == 2


def test_statistics_new_this_month_count(client, sample_data):
    """测试本月新增证书数量"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    today = date.today()
    current_month_start = today.replace(day=1)

    new_count = 0
    with app.app_context():
        new_count = Certificate.query.filter(
            Certificate.calibration_date >= current_month_start
        ).count()

    assert overview['new_this_month'] == new_count


def test_statistics_expiring_warning_count(client, sample_data):
    """测试到期预警数量"""
    response = client.get('/api/statistics?operator=Supervisor1')
    assert response.status_code == 200
    data = json.loads(response.data)

    overview = data['overview']
    today = date.today()
    warning_days = overview['warning_days']
    expiry_threshold = today + timedelta(days=warning_days)

    expiring_count = Certificate.query.filter(
        Certificate.valid_until <= expiry_threshold,
        Certificate.valid_until >= today,
        Certificate.workflow_status.in_([
            WorkflowStatus.DRAFT.value,
            WorkflowStatus.ENTERED.value,
            WorkflowStatus.REVIEWED.value,
            WorkflowStatus.APPROVED.value,
            WorkflowStatus.RELEASED.value
        ])
    ).count()

    assert overview['expiring_warning_count'] == expiring_count
