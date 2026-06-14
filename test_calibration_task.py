import pytest
from app import app, db
from models import Equipment, CalibrationTask, TaskStatus, TaskType, AuditLog, User
from datetime import datetime, timedelta, date
import json
import time
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
        supervisor2 = User(username='Supervisor2', role='supervisor')
        db.session.add_all([operator1, metrologist1, supervisor1, supervisor2])
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_equipment(client):
    with app.app_context():
        equipment = Equipment(
            equipment_no='EQ-TASK-001',
            equipment_name='Task Test Equipment',
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
            equipment_no='EQ-TASK-002',
            equipment_name='Task Test Equipment 2',
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


def test_create_task_permission_denied_for_operator(client, sample_equipment):
    response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Operator1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    assert response.status_code == 403
    data = json.loads(response.data)
    assert 'required_role' in data
    assert data['required_role'] == ['supervisor']


def test_create_task_permission_denied_for_metrologist(client, sample_equipment):
    response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Metrologist1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    assert response.status_code == 403
    data = json.loads(response.data)
    assert 'required_role' in data


def test_create_periodic_task_success(client, sample_equipment):
    response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic',
            'planned_date': '2026-07-01',
            'calibrator': 'Calibrator1',
            'priority': 5,
            'period_days': 365
        }),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['task_type'] == 'periodic'
    assert data['status'] == 'pending'
    assert data['period_days'] == 365
    assert data['assigned_by'] == 'Supervisor1'
    assert 'task_no' in data


def test_create_urgent_task_success(client, sample_equipment):
    response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'urgent',
            'priority': 10
        }),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['task_type'] == 'urgent'
    assert data['priority'] == 10


def test_create_batch_task_success(client, sample_equipment):
    response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'batch',
            'priority': 3
        }),
        content_type='application/json'
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['task_type'] == 'batch'


def test_create_task_equipment_not_found(client):
    response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': 99999,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'not found' in str(data['errors']).lower()


def test_create_task_invalid_type(client, sample_equipment):
    response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'invalid_type'
        }),
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'invalid' in str(data['errors']).lower()


def test_task_conflict_detection(client, sample_equipment):
    response1 = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    assert response1.status_code == 201
    
    response2 = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'urgent'
        }),
        content_type='application/json'
    )
    assert response2.status_code == 409
    data = json.loads(response2.data)
    assert data['conflict'] == True
    assert len(data['conflicting_tasks']) == 1


def test_task_force_override(client, sample_equipment):
    response1 = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    assert response1.status_code == 201
    data1 = json.loads(response1.data)
    task1_id = data1['id']
    
    response2 = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'urgent',
            'force_override': True
        }),
        content_type='application/json'
    )
    assert response2.status_code == 201
    data2 = json.loads(response2.data)
    
    task_response = client.get(f'/api/tasks/{task1_id}')
    task_data = json.loads(task_response.data)
    assert task_data['status'] == 'abnormal_closed'
    assert 'Overridden' in task_data['close_reason']


def test_task_force_override_audit_log(client, sample_equipment):
    response1 = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    data1 = json.loads(response1.data)
    task1_id = data1['id']
    
    client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'urgent',
            'force_override': True
        }),
        content_type='application/json'
    )
    
    audit_response = client.get(f'/api/audit?resource_id={task1_id}')
    audit_data = json.loads(audit_response.data)
    
    override_logs = [log for log in audit_data if log['action'] == 'task_force_override']
    assert len(override_logs) == 1
    assert override_logs[0]['previous_state'] == 'pending'
    assert override_logs[0]['new_state'] == 'abnormal_closed'


def test_batch_create_tasks(client, sample_equipment, sample_equipment2):
    response = client.post('/api/tasks/batch',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_ids': [sample_equipment, sample_equipment2],
            'task_type': 'batch'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] == 2
    assert data['successful'] == 2
    assert data['failed'] == 0


def test_batch_create_tasks_permission_denied(client, sample_equipment, sample_equipment2):
    response = client.post('/api/tasks/batch',
        data=json.dumps({
            'operator': 'Operator1',
            'equipment_ids': [sample_equipment, sample_equipment2],
            'task_type': 'batch'
        }),
        content_type='application/json'
    )
    assert response.status_code == 403


def test_accept_task_success(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    accept_response = client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    assert accept_response.status_code == 200
    data = json.loads(accept_response.data)
    assert data['status'] == 'accepted'
    assert data['accepted_by'] == 'Calibrator1'


def test_accept_task_wrong_status(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    
    accept_again = client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator2'}),
        content_type='application/json'
    )
    assert accept_again.status_code == 400


def test_start_task_success(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    
    start_response = client.post(f'/api/tasks/{task_id}/start',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    assert start_response.status_code == 200
    data = json.loads(start_response.data)
    assert data['status'] == 'in_progress'
    assert data['actual_start_time'] is not None


def test_start_task_wrong_status(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    start_response = client.post(f'/api/tasks/{task_id}/start',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    assert start_response.status_code == 400


def test_complete_task_permission_denied(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    client.post(f'/api/tasks/{task_id}/start',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    
    complete_response = client.post(f'/api/tasks/{task_id}/complete',
        data=json.dumps({
            'operator': 'Operator1',
            'execution_notes': 'Completed'
        }),
        content_type='application/json'
    )
    assert complete_response.status_code == 403


def test_complete_task_success(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic',
            'period_days': 365
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    client.post(f'/api/tasks/{task_id}/start',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    
    complete_response = client.post(f'/api/tasks/{task_id}/complete',
        data=json.dumps({
            'operator': 'Supervisor1',
            'execution_notes': 'Calibration completed successfully',
            'measurement_data': {'deviation': 0.02, 'result': 'pass'}
        }),
        content_type='application/json'
    )
    assert complete_response.status_code == 200
    data = json.loads(complete_response.data)
    assert data['status'] == 'completed'
    assert data['execution_notes'] == 'Calibration completed successfully'
    assert data['measurement_data'] is not None


def test_complete_task_creates_next_periodic(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic',
            'period_days': 365,
            'planned_date': '2026-07-01'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    client.post(f'/api/tasks/{task_id}/start',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    client.post(f'/api/tasks/{task_id}/complete',
        data=json.dumps({
            'operator': 'Supervisor1',
            'execution_notes': 'Done'
        }),
        content_type='application/json'
    )
    
    search_response = client.get(f'/api/tasks?equipment_id={sample_equipment}')
    search_data = json.loads(search_response.data)
    
    assert search_data['total'] == 2
    
    completed_task = next((t for t in search_data['items'] if t['status'] == 'completed'), None)
    next_task = next((t for t in search_data['items'] if t['status'] == 'pending'), None)
    
    assert completed_task is not None
    assert next_task is not None
    assert next_task['parent_task_id'] == completed_task['id']


def test_close_task_abnormal_permission_denied(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    close_response = client.post(f'/api/tasks/{task_id}/close',
        data=json.dumps({
            'operator': 'Operator1',
            'close_reason': 'Equipment unavailable'
        }),
        content_type='application/json'
    )
    assert close_response.status_code == 403


def test_close_task_abnormal_success(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    close_response = client.post(f'/api/tasks/{task_id}/close',
        data=json.dumps({
            'operator': 'Supervisor1',
            'close_reason': 'Equipment sent for repair'
        }),
        content_type='application/json'
    )
    assert close_response.status_code == 200
    data = json.loads(close_response.data)
    assert data['status'] == 'abnormal_closed'
    assert data['close_reason'] == 'Equipment sent for repair'


def test_task_status_flow_audit_logs(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    
    client.post(f'/api/tasks/{task_id}/start',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    
    client.post(f'/api/tasks/{task_id}/complete',
        data=json.dumps({
            'operator': 'Supervisor1',
            'execution_notes': 'Done'
        }),
        content_type='application/json'
    )
    
    audit_response = client.get(f'/api/audit?resource_id={task_id}')
    audit_data = json.loads(audit_response.data)
    
    task_audits = [log for log in audit_data if log['resource_type'] == 'calibration_task']
    actions = [log['action'] for log in task_audits]
    
    assert 'task_create' in actions
    assert 'task_accept' in actions
    assert 'task_start' in actions
    assert 'task_complete' in actions
    
    for log in task_audits:
        assert log['previous_state'] is not None or log['action'] == 'task_create'
        assert log['new_state'] is not None


def test_complete_task_data_persistence(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    client.post(f'/api/tasks/{task_id}/accept',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    client.post(f'/api/tasks/{task_id}/start',
        data=json.dumps({'operator': 'Calibrator1'}),
        content_type='application/json'
    )
    
    measurement_data = {
        'points': [
            {'nominal': 0, 'actual': 0.01, 'deviation': 0.01},
            {'nominal': 50, 'actual': 50.02, 'deviation': 0.02},
            {'nominal': 100, 'actual': 100.03, 'deviation': 0.03}
        ],
        'temperature': 23.5,
        'humidity': 45
    }
    
    client.post(f'/api/tasks/{task_id}/complete',
        data=json.dumps({
            'operator': 'Supervisor1',
            'execution_notes': 'All points within tolerance',
            'measurement_data': measurement_data
        }),
        content_type='application/json'
    )
    
    task_response = client.get(f'/api/tasks/{task_id}')
    task_data = json.loads(task_response.data)
    
    assert task_data['execution_notes'] == 'All points within tolerance'
    saved_data = json.loads(task_data['measurement_data'])
    assert len(saved_data['points']) == 3
    assert saved_data['temperature'] == 23.5


def test_search_tasks_by_status(client, sample_equipment):
    client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    
    response = client.get('/api/tasks?status=pending')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['total'] >= 1
    for item in data['items']:
        assert item['status'] == 'pending'


def test_search_tasks_by_type(client, sample_equipment):
    client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'urgent'
        }),
        content_type='application/json'
    )
    
    response = client.get('/api/tasks?task_type=urgent')
    assert response.status_code == 200
    data = json.loads(response.data)
    for item in data['items']:
        assert item['task_type'] == 'urgent'


def test_search_tasks_pagination(client, sample_equipment):
    task_ids = []
    for i in range(25):
        response = client.post('/api/tasks',
            data=json.dumps({
                'operator': 'Supervisor1',
                'equipment_id': sample_equipment,
                'task_type': 'periodic',
                'force_override': True
            }),
            content_type='application/json'
        )
        if response.status_code == 201:
            task_ids.append(json.loads(response.data)['id'])
    
    response = client.get('/api/tasks?page=1&per_page=10')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['items']) == 10
    assert data['has_next'] == True


def test_get_scheduler_config(client):
    response = client.get('/api/config/scheduler')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'default_priority' in data
    assert 'urgent_priority' in data
    assert 'auto_create_next_periodic' in data
    assert 'allow_force_override' in data


def test_update_scheduler_config(client):
    response = client.put('/api/config/scheduler',
        data=json.dumps({
            'default_priority': 1,
            'task_reminder_days': 14
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['updated']['default_priority'] == 1
    assert data['updated']['task_reminder_days'] == 14
    
    get_response = client.get('/api/config/scheduler')
    get_data = json.loads(get_response.data)
    assert get_data['default_priority'] == 1
    assert get_data['task_reminder_days'] == 14


def test_scheduler_config_hot_reload(client):
    client.put('/api/config/scheduler',
        data=json.dumps({'default_period_days': 180}),
        content_type='application/json'
    )
    
    import time
    time.sleep(1)
    
    get_response = client.get('/api/config/scheduler')
    get_data = json.loads(get_response.data)
    assert get_data['default_period_days'] == 180


def test_check_task_conflict_endpoint(client, sample_equipment):
    client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic'
        }),
        content_type='application/json'
    )
    
    response = client.get(f'/api/tasks/conflict/{sample_equipment}')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['has_conflict'] == True
    assert len(data['conflicting_tasks']) == 1


def test_get_tasks_by_calibrator(client, sample_equipment):
    client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic',
            'calibrator': 'TestCalibrator'
        }),
        content_type='application/json'
    )
    
    response = client.get('/api/tasks/calibrator/TestCalibrator')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) >= 1
    for task in data:
        assert task['calibrator'] == 'TestCalibrator'


def test_task_not_found(client):
    response = client.get('/api/tasks/99999')
    assert response.status_code == 404


def test_task_audit_log_correctness(client, sample_equipment):
    create_response = client.post('/api/tasks',
        data=json.dumps({
            'operator': 'Supervisor1',
            'equipment_id': sample_equipment,
            'task_type': 'periodic',
            'planned_date': '2026-07-15'
        }),
        content_type='application/json'
    )
    task_id = json.loads(create_response.data)['id']
    
    audit_response = client.get(f'/api/audit?resource_id={task_id}')
    audit_data = json.loads(audit_response.data)
    
    create_log = next((log for log in audit_data if log['action'] == 'task_create'), None)
    assert create_log is not None
    assert create_log['operator'] == 'Supervisor1'
    assert create_log['resource_type'] == 'calibration_task'
    assert create_log['equipment_id'] == sample_equipment
    
    details = json.loads(create_log['details'])
    assert details['task_type'] == 'periodic'
    assert details['equipment_id'] == sample_equipment
