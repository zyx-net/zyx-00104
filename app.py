from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from models import db, Equipment, Certificate, AuditLog, WorkflowStatus, Report, ReportStatus, CalibrationTask, TaskStatus, TaskType
from services import CertificateImportService, WorkflowService, ExportService, ExpiryWarningService, BatchStatsService, ConfigService, BatchWorkflowService, RevertService, ExpiryAutoTransitionService, CertificateSearchService, RolePermissionService, UserService, PermissionDeniedException, ExpiryCheckConflictException, ScheduledTaskService, ReportService, ReportGenerationConflictException, CertificateLockedException, CalibrationTaskService, TaskConflictException, CalibrationStatisticsService, StatisticsPermissionDeniedException, AuditService, AuditQueryPermissionDeniedException
from validators import parse_csv_to_json
from datetime import datetime
import os
import json
import io

app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///calibration.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_AS_ASCII'] = False

db.init_app(app)

@app.cli.command('init-db')
def init_db():
    db.create_all()
    print('Database initialized.')

with app.app_context():
    db.create_all()

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'calibration-certificate-service'})

@app.route('/api/equipment', methods=['GET'])
def list_equipment():
    equipment = Equipment.query.all()
    return jsonify([eq.to_dict() for eq in equipment])

@app.route('/api/equipment/<int:equipment_id>', methods=['GET'])
def get_equipment(equipment_id):
    equipment = Equipment.query.get_or_404(equipment_id)
    return jsonify(equipment.to_dict())

@app.route('/api/equipment', methods=['POST'])
def create_equipment():
    data = request.json

    if isinstance(data, list):
        results = []
        for eq_data in data:
            equipment = Equipment(
                equipment_no=eq_data['equipment_no'],
                equipment_name=eq_data['equipment_name'],
                model_spec=eq_data.get('model_spec'),
                manufacturer=eq_data.get('manufacturer'),
                range_min=eq_data.get('range_min'),
                range_max=eq_data.get('range_max'),
                unit=eq_data.get('unit'),
                tolerance=eq_data.get('tolerance'),
                location=eq_data.get('location')
            )
            db.session.add(equipment)
            db.session.flush()

            audit = AuditLog(
                operator=eq_data.get('operator', 'system'),
                action='create',
                resource_type='equipment',
                resource_id=equipment.id,
                equipment_id=equipment.id,
                notes='Equipment created',
                version=1,
                new_state='active'
            )
            db.session.add(audit)
            results.append(equipment.to_dict())

        db.session.commit()
        return jsonify(results), 201
    else:
        equipment = Equipment(
            equipment_no=data['equipment_no'],
            equipment_name=data['equipment_name'],
            model_spec=data.get('model_spec'),
            manufacturer=data.get('manufacturer'),
            range_min=data.get('range_min'),
            range_max=data.get('range_max'),
            unit=data.get('unit'),
            tolerance=data.get('tolerance'),
            location=data.get('location')
        )
        db.session.add(equipment)
        db.session.commit()

        audit = AuditLog(
            operator=data.get('operator', 'system'),
            action='create',
            resource_type='equipment',
            resource_id=equipment.id,
            equipment_id=equipment.id,
            notes='Equipment created',
            version=1,
            new_state='active'
        )
        db.session.add(audit)
        db.session.commit()

        return jsonify(equipment.to_dict()), 201

@app.route('/api/certificates/import', methods=['POST'])
def import_certificates():
    data = request.json

    content_type = request.content_type or ''
    if 'application/json' in content_type:
        if isinstance(data, list):
            data_list = data
            operator = 'system'
            batch_id = None
        elif 'data' in data:
            data_list = data['data']
            operator = data.get('operator', 'system')
            batch_id = data.get('batch_id')
        else:
            data_list = [data]
            operator = data.get('operator', 'system')
            batch_id = data.get('batch_id')
    else:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    import_service = CertificateImportService()
    results, success = import_service.import_certificates(data_list, operator, batch_id)

    if success:
        return jsonify(results), 201
    else:
        return jsonify(results), 400

@app.route('/api/certificates/import/csv', methods=['POST'])
def import_certificates_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    operator = request.form.get('operator', 'system')
    batch_id = request.form.get('batch_id')

    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be CSV format'}), 400

    try:
        csv_content = file.read().decode('utf-8')
        data_list = parse_csv_to_json(csv_content)

        import_service = CertificateImportService()
        results, success = import_service.import_certificates(data_list, operator, batch_id)

        if success:
            return jsonify(results), 201
        else:
            return jsonify(results), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/certificates', methods=['GET'])
def list_certificates():
    workflow_status = request.args.get('workflow_status')
    equipment_id = request.args.get('equipment_id')
    batch_id = request.args.get('batch_id')

    query = Certificate.query

    if workflow_status:
        query = query.filter_by(workflow_status=workflow_status)
    if equipment_id:
        query = query.filter_by(equipment_id=int(equipment_id))
    if batch_id:
        query = query.filter_by(batch_id=batch_id)

    certificates = query.order_by(Certificate.created_at.desc()).all()
    return jsonify([cert.to_dict() for cert in certificates])

@app.route('/api/certificates/<int:certificate_id>', methods=['GET'])
def get_certificate(certificate_id):
    cert = Certificate.query.get_or_404(certificate_id)
    return jsonify(cert.to_dict())

@app.route('/api/certificates/<int:certificate_id>/enter', methods=['POST'])
def enter_certificate(certificate_id):
    data = request.json
    operator = data.get('operator')
    notes = data.get('notes', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    workflow_service = WorkflowService()
    success, errors = workflow_service.enter(certificate_id, operator, notes)

    if success:
        cert = Certificate.query.get(certificate_id)
        return jsonify(cert.to_dict())
    else:
        return jsonify({'errors': errors}), 400

@app.route('/api/certificates/<int:certificate_id>/review', methods=['POST'])
def review_certificate(certificate_id):
    data = request.json
    operator = data.get('operator')
    notes = data.get('notes', '')
    decision_basis = data.get('decision_basis', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    workflow_service = WorkflowService()
    success, errors = workflow_service.review(certificate_id, operator, notes, decision_basis)

    if success:
        cert = Certificate.query.get(certificate_id)
        return jsonify(cert.to_dict())
    else:
        return jsonify({'errors': errors}), 400

@app.route('/api/certificates/<int:certificate_id>/approve', methods=['POST'])
def approve_certificate(certificate_id):
    data = request.json
    operator = data.get('operator')
    notes = data.get('notes', '')
    decision_basis = data.get('decision_basis', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    workflow_service = WorkflowService()
    success, errors = workflow_service.approve(certificate_id, operator, notes, decision_basis)

    if success:
        cert = Certificate.query.get(certificate_id)
        return jsonify(cert.to_dict())
    else:
        return jsonify({'errors': errors}), 400

@app.route('/api/certificates/<int:certificate_id>/release', methods=['POST'])
def release_certificate(certificate_id):
    data = request.json
    operator = data.get('operator')
    notes = data.get('notes', '')
    decision_basis = data.get('decision_basis', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    workflow_service = WorkflowService()
    success, errors = workflow_service.release(certificate_id, operator, notes, decision_basis)

    if success:
        cert = Certificate.query.get(certificate_id)
        return jsonify(cert.to_dict())
    else:
        return jsonify({'errors': errors, 'message': 'Release failed'}), 400

@app.route('/api/certificates/<int:certificate_id>/limit', methods=['POST'])
def limit_certificate(certificate_id):
    data = request.json
    operator = data.get('operator')
    notes = data.get('notes', '')
    decision_basis = data.get('decision_basis', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    workflow_service = WorkflowService()
    success, errors = workflow_service.limit(certificate_id, operator, notes, decision_basis)

    if success:
        cert = Certificate.query.get(certificate_id)
        return jsonify(cert.to_dict())
    else:
        return jsonify({'errors': errors}), 400

@app.route('/api/certificates/<int:certificate_id>/stop', methods=['POST'])
def stop_certificate(certificate_id):
    data = request.json
    operator = data.get('operator')
    notes = data.get('notes', '')
    decision_basis = data.get('decision_basis', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    workflow_service = WorkflowService()
    success, errors = workflow_service.stop(certificate_id, operator, notes, decision_basis)

    if success:
        cert = Certificate.query.get(certificate_id)
        return jsonify(cert.to_dict())
    else:
        return jsonify({'errors': errors}), 400

@app.route('/api/certificates/batch/approve', methods=['POST'])
def batch_approve_certificates():
    data = request.json
    certificate_ids = data.get('certificate_ids', [])
    operator = data.get('operator')
    notes = data.get('notes', '')
    decision_basis = data.get('decision_basis', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    if not certificate_ids:
        return jsonify({'error': 'certificate_ids is required and cannot be empty'}), 400

    if not isinstance(certificate_ids, list):
        return jsonify({'error': 'certificate_ids must be a list'}), 400

    batch_service = BatchWorkflowService()
    results = batch_service.batch_approve(certificate_ids, operator, notes, decision_basis)

    return jsonify(results)

@app.route('/api/certificates/batch/release', methods=['POST'])
def batch_release_certificates():
    data = request.json
    certificate_ids = data.get('certificate_ids', [])
    operator = data.get('operator')
    notes = data.get('notes', '')
    decision_basis = data.get('decision_basis', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    if not certificate_ids:
        return jsonify({'error': 'certificate_ids is required and cannot be empty'}), 400

    if not isinstance(certificate_ids, list):
        return jsonify({'error': 'certificate_ids must be a list'}), 400

    batch_service = BatchWorkflowService()
    results = batch_service.batch_release(certificate_ids, operator, notes, decision_basis)

    return jsonify(results)

@app.route('/api/certificates/<int:certificate_id>/revert', methods=['POST'])
def revert_certificate(certificate_id):
    data = request.json
    operator = data.get('operator')
    notes = data.get('notes', '')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    revert_service = RevertService()
    success, errors = revert_service.revert_last_workflow_change(certificate_id, operator, notes)

    if success:
        cert = Certificate.query.get(certificate_id)
        return jsonify(cert.to_dict())
    else:
        return jsonify({'errors': errors}), 400

@app.route('/api/export/equipment/<int:equipment_id>', methods=['GET'])
def export_by_equipment(equipment_id):
    format_type = request.args.get('format', 'json')
    valid_from = request.args.get('valid_from')
    valid_to = request.args.get('valid_to')

    export_service = ExportService()
    result = export_service.export_by_equipment(equipment_id, format_type, valid_from, valid_to)

    if format_type == 'csv':
        return send_file(
            io.BytesIO(result.encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'equipment_{equipment_id}_certs.csv'
        )
    else:
        return jsonify(json.loads(result))

@app.route('/api/export/batch/<batch_id>', methods=['GET'])
def export_by_batch(batch_id):
    format_type = request.args.get('format', 'json')
    valid_from = request.args.get('valid_from')
    valid_to = request.args.get('valid_to')

    export_service = ExportService()
    result = export_service.export_by_batch(batch_id, format_type, valid_from, valid_to)

    if format_type == 'csv':
        import io
        return send_file(
            io.BytesIO(result.encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'batch_{batch_id}_certs.csv'
        )
    else:
        return jsonify(json.loads(result))

@app.route('/api/export/all', methods=['GET'])
def export_all():
    format_type = request.args.get('format', 'json')
    valid_from = request.args.get('valid_from')
    valid_to = request.args.get('valid_to')

    export_service = ExportService()
    result = export_service.export_all(format_type, valid_from, valid_to)

    if format_type == 'csv':
        import io
        return send_file(
            io.BytesIO(result.encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='all_certs.csv'
        )
    else:
        return jsonify(json.loads(result))

@app.route('/api/certificates/expiry-warning', methods=['GET'])
def expiry_warning():
    days = request.args.get('days', type=int)

    warning_service = ExpiryWarningService()
    certs = warning_service.get_expiring_certificates(days)

    return jsonify({
        'warning_days_used': days if days else ConfigService().get_expiry_warning_days(),
        'count': len(certs),
        'certificates': [cert.to_dict() for cert in certs]
    })

@app.route('/api/batches/stats', methods=['GET'])
def batch_stats():
    stats_service = BatchStatsService()
    stats = stats_service.get_batch_statistics()
    return jsonify(stats)

@app.route('/api/config/expiry-warning-days', methods=['GET'])
def get_expiry_warning_days():
    config_service = ConfigService()
    return jsonify({'expiry_warning_days': config_service.get_expiry_warning_days()})

@app.route('/api/config/expiry-warning-days', methods=['PUT'])
def set_expiry_warning_days():
    data = request.json
    days = data.get('days')

    if not days or not isinstance(days, int) or days <= 0:
        return jsonify({'error': 'Days must be a positive integer'}), 400

    config_service = ConfigService()
    config_service.set_expiry_warning_days(days)
    return jsonify({'expiry_warning_days': days})

@app.route('/api/certificates/expiry-process', methods=['POST'])
def process_expiry():
    expiry_service = ExpiryAutoTransitionService()
    try:
        results = expiry_service.process_expired_certificates(source='manual')
        return jsonify(results)
    except ExpiryCheckConflictException as e:
        return jsonify({'error': str(e), 'conflict': True}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/certificates/search', methods=['GET'])
def search_certificates():
    cert_no = request.args.get('cert_no')
    workflow_status = request.args.get('workflow_status')
    equipment_no = request.args.get('equipment_no')
    batch_id = request.args.get('batch_id')
    calibration_date_from = request.args.get('calibration_date_from')
    calibration_date_to = request.args.get('calibration_date_to')
    operator = request.args.get('operator')
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'valid_until')
    sort_order = request.args.get('sort_order', 'asc')

    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 20

    filters = {}
    if cert_no:
        filters['cert_no'] = cert_no
    if workflow_status:
        filters['workflow_status'] = workflow_status
    if equipment_no:
        filters['equipment_no'] = equipment_no
    if batch_id:
        filters['batch_id'] = batch_id
    if calibration_date_from:
        filters['calibration_date_from'] = calibration_date_from
    if calibration_date_to:
        filters['calibration_date_to'] = calibration_date_to
    if operator:
        filters['operator'] = operator

    search_service = CertificateSearchService()
    results = search_service.search(
        filters=filters if filters else None,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order
    )

    return jsonify(results)

@app.route('/api/users', methods=['GET'])
def list_users():
    users = UserService.list_users()
    return jsonify([user.to_dict() for user in users])

@app.route('/api/users', methods=['POST'])
def create_user():
    data = request.json
    username = data.get('username')
    role = data.get('role', 'operator')

    if not username:
        return jsonify({'error': 'Username is required'}), 400

    try:
        user = UserService.create_user(username, role)
        return jsonify(user.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/users/<username>', methods=['GET'])
def get_user(username):
    user = UserService.get_user(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user.to_dict())

@app.route('/api/users/<username>/role', methods=['PUT'])
def update_user_role(username):
    data = request.json
    new_role = data.get('role')

    if not new_role:
        return jsonify({'error': 'Role is required'}), 400

    try:
        user = UserService.update_user_role(username, new_role)
        return jsonify(user.to_dict())
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/config/expiry-check-interval', methods=['GET'])
def get_expiry_check_interval():
    config_service = ConfigService()
    return jsonify({
        'expiry_check_interval_hours': config_service.get_expiry_check_interval_hours(),
        'last_check_time': config_service.get_last_expiry_check_time(),
        'check_in_progress': config_service.get_expiry_check_in_progress()
    })

@app.route('/api/config/expiry-check-interval', methods=['PUT'])
def set_expiry_check_interval():
    data = request.json
    hours = data.get('hours')

    if not hours or not isinstance(hours, (int, float)) or hours <= 0:
        return jsonify({'error': 'Hours must be a positive number'}), 400

    config_service = ConfigService()
    config_service.set_expiry_check_interval_hours(hours)
    return jsonify({'expiry_check_interval_hours': hours})

@app.route('/api/scheduler/status', methods=['GET'])
def get_scheduler_status():
    status = ScheduledTaskService.get_scheduler_status()
    return jsonify(status)

@app.route('/api/scheduler/start', methods=['POST'])
def start_scheduler():
    ScheduledTaskService.start_scheduler(app)
    return jsonify({'message': 'Scheduler started'})

@app.route('/api/scheduler/stop', methods=['POST'])
def stop_scheduler():
    ScheduledTaskService.stop_scheduler()
    return jsonify({'message': 'Scheduler stopped'})

@app.route('/api/audit', methods=['GET'])
def list_audit_logs():
    certificate_id = request.args.get('certificate_id')
    equipment_id = request.args.get('equipment_id')
    batch_id = request.args.get('batch_id')
    operator = request.args.get('operator')
    action = request.args.get('action')

    query = AuditLog.query

    if certificate_id:
        query = query.filter_by(certificate_id=int(certificate_id))
    if equipment_id:
        query = query.filter_by(equipment_id=int(equipment_id))
    if batch_id:
        query = query.filter_by(batch_id=batch_id)
    if operator:
        query = query.filter_by(operator=operator)
    if action:
        query = query.filter_by(action=action)

    logs = query.order_by(AuditLog.timestamp.desc()).all()
    return jsonify([log.to_dict() for log in logs])


@app.route('/api/audit/search', methods=['GET'])
def search_audit_logs():
    operator = request.args.get('operator')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    action = request.args.get('action')
    resource_type = request.args.get('resource_type')
    certificate_id = request.args.get('certificate_id', type=int)
    equipment_id = request.args.get('equipment_id', type=int)
    batch_id = request.args.get('batch_id')
    target_operator = request.args.get('target_operator')
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 20

    filters = {}
    if start_time:
        filters['start_time'] = start_time
    if end_time:
        filters['end_time'] = end_time
    if action:
        filters['action'] = action
    if target_operator:
        filters['target_operator'] = target_operator
    if resource_type:
        filters['resource_type'] = resource_type
    if certificate_id:
        filters['certificate_id'] = certificate_id
    if equipment_id:
        filters['equipment_id'] = equipment_id
    if batch_id:
        filters['batch_id'] = batch_id

    audit_service = AuditService()

    try:
        results = audit_service.query_audit_logs(
            operator=operator,
            filters=filters if filters else None,
            page=page,
            per_page=per_page
        )
        return jsonify(results)
    except AuditQueryPermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403


@app.route('/api/audit/export', methods=['GET'])
def export_audit_logs():
    operator = request.args.get('operator')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    action = request.args.get('action')
    resource_type = request.args.get('resource_type')
    certificate_id = request.args.get('certificate_id', type=int)
    equipment_id = request.args.get('equipment_id', type=int)
    batch_id = request.args.get('batch_id')
    target_operator = request.args.get('target_operator')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    filters = {}
    if start_time:
        filters['start_time'] = start_time
    if end_time:
        filters['end_time'] = end_time
    if action:
        filters['action'] = action
    if target_operator:
        filters['target_operator'] = target_operator
    if resource_type:
        filters['resource_type'] = resource_type
    if certificate_id:
        filters['certificate_id'] = certificate_id
    if equipment_id:
        filters['equipment_id'] = equipment_id
    if batch_id:
        filters['batch_id'] = batch_id

    audit_service = AuditService()

    try:
        csv_content = audit_service.export_audit_logs_csv(
            operator=operator,
            filters=filters if filters else None
        )

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'audit_logs_{timestamp}.csv'

        return send_file(
            io.BytesIO(csv_content.encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    except AuditQueryPermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403


@app.route('/api/audit/archive', methods=['POST'])
def archive_audit_logs():
    data = request.json
    operator = data.get('operator')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    role = RolePermissionService.get_user_role(operator)
    if role != 'supervisor':
        return jsonify({
            'error': 'Archive operation requires supervisor role',
            'required_role': ['supervisor'],
            'operator_role': role
        }), 403

    audit_service = AuditService()
    result = audit_service.archive_old_logs()

    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400


@app.errorhandler(AuditQueryPermissionDeniedException)
def handle_audit_permission_denied(e):
    return jsonify({
        'error': e.message,
        'required_role': e.required_role,
        'operator_role': e.operator_role
    }), 403

@app.route('/api/reports/preview/<int:certificate_id>', methods=['POST'])
def preview_report(certificate_id):
    data = request.json
    operator = data.get('operator')
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    
    report_service = ReportService()
    
    try:
        result, error = report_service.preview_report(certificate_id, operator)
        
        if error:
            return jsonify(error), 400
        
        return jsonify(result)
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403

@app.route('/api/reports/generate/<int:certificate_id>', methods=['POST'])
def generate_report(certificate_id):
    data = request.json
    operator = data.get('operator')
    force_overwrite = data.get('force_overwrite', False)
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    
    report_service = ReportService()
    
    try:
        result, error = report_service.generate_report(certificate_id, operator, force_overwrite)
        
        if error:
            return jsonify(error), 400
        
        return jsonify(result), 201
    except ReportGenerationConflictException as e:
        return jsonify({
            'error': e.message,
            'conflict': True,
            'existing_version': e.existing_report.version,
            'message': 'Report already exists. Use force_overwrite=true to overwrite.'
        }), 409
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403

@app.route('/api/reports/batch/generate', methods=['POST'])
def batch_generate_reports():
    data = request.json
    certificate_ids = data.get('certificate_ids', [])
    operator = data.get('operator')
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    
    if not certificate_ids or not isinstance(certificate_ids, list):
        return jsonify({'error': 'certificate_ids must be a non-empty list'}), 400
    
    report_service = ReportService()
    
    try:
        result = report_service.batch_generate_reports(certificate_ids, operator)
        return jsonify(result)
    except CertificateLockedException as e:
        return jsonify({
            'error': e.message,
            'locked_certificates': e.certificate_ids
        }), 409
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403

@app.route('/api/reports', methods=['GET'])
def search_reports():
    equipment_no = request.args.get('equipment_no')
    certificate_id = request.args.get('certificate_id')
    status = request.args.get('status')
    calibration_date_from = request.args.get('calibration_date_from')
    calibration_date_to = request.args.get('calibration_date_to')
    generated_by = request.args.get('generated_by')
    
    filters = {}
    if equipment_no:
        filters['equipment_no'] = equipment_no
    if certificate_id:
        filters['certificate_id'] = int(certificate_id)
    if status:
        filters['status'] = status
    if calibration_date_from:
        filters['calibration_date_from'] = calibration_date_from
    if calibration_date_to:
        filters['calibration_date_to'] = calibration_date_to
    if generated_by:
        filters['generated_by'] = generated_by
    
    report_service = ReportService()
    reports = report_service.search_reports(filters if filters else None)
    
    return jsonify(reports)

@app.route('/api/reports/<int:report_id>', methods=['GET'])
def get_report(report_id):
    report_service = ReportService()
    report = report_service.get_report_by_id(report_id)
    
    if not report:
        return jsonify({'error': 'Report not found'}), 404
    
    return jsonify(report.to_dict())

@app.route('/api/reports/<int:report_id>/revoke', methods=['POST'])
def revoke_report(report_id):
    data = request.json
    operator = data.get('operator')
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    
    report_service = ReportService()
    
    try:
        result, error = report_service.revoke_report(report_id, operator)
        
        if error:
            return jsonify(error), 400
        
        return jsonify(result)
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(PermissionDeniedException)
def handle_permission_denied(e):
    return jsonify({
        'error': e.message,
        'required_role': e.required_role,
        'operator_role': e.operator_role,
        'action': e.action,
        'resource_type': e.resource_type,
        'resource_id': e.resource_id
    }), 403


@app.route('/api/tasks', methods=['POST'])
def create_calibration_task():
    data = request.json
    operator = data.get('operator')
    equipment_id = data.get('equipment_id')
    task_type = data.get('task_type')
    planned_date = data.get('planned_date')
    calibrator = data.get('calibrator')
    priority = data.get('priority', 0)
    period_days = data.get('period_days')
    force_override = data.get('force_override', False)
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    if not equipment_id:
        return jsonify({'error': 'Equipment ID is required'}), 400
    if not task_type:
        return jsonify({'error': 'Task type is required'}), 400
    
    from dateutil import parser
    parsed_date = None
    if planned_date:
        try:
            parsed_date = parser.parse(planned_date).date()
        except:
            return jsonify({'error': 'Invalid planned_date format'}), 400
    
    task_service = CalibrationTaskService()
    
    try:
        task, error = task_service.create_task(
            equipment_id=equipment_id,
            task_type=task_type,
            operator=operator,
            planned_date=parsed_date,
            calibrator=calibrator,
            priority=priority,
            period_days=period_days,
            force_override=force_override
        )
        
        if error:
            return jsonify({'errors': error}), 400
        
        return jsonify(task), 201
    except TaskConflictException as e:
        return jsonify({
            'error': e.message,
            'conflict': True,
            'conflicting_tasks': e.conflicting_tasks
        }), 409
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403


@app.route('/api/tasks/batch', methods=['POST'])
def batch_create_calibration_tasks():
    data = request.json
    operator = data.get('operator')
    equipment_ids = data.get('equipment_ids', [])
    task_type = data.get('task_type')
    planned_date = data.get('planned_date')
    calibrator = data.get('calibrator')
    priority = data.get('priority', 0)
    force_override = data.get('force_override', False)
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    if not equipment_ids or not isinstance(equipment_ids, list):
        return jsonify({'error': 'equipment_ids must be a non-empty list'}), 400
    if not task_type:
        return jsonify({'error': 'Task type is required'}), 400
    
    from dateutil import parser
    parsed_date = None
    if planned_date:
        try:
            parsed_date = parser.parse(planned_date).date()
        except:
            pass
    
    task_service = CalibrationTaskService()
    
    try:
        results = task_service.batch_create_tasks(
            equipment_ids=equipment_ids,
            task_type=task_type,
            operator=operator,
            planned_date=parsed_date,
            calibrator=calibrator,
            priority=priority,
            force_override=force_override
        )
        return jsonify(results)
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403


@app.route('/api/tasks', methods=['GET'])
def search_calibration_tasks():
    equipment_id = request.args.get('equipment_id', type=int)
    status = request.args.get('status')
    task_type = request.args.get('task_type')
    calibrator = request.args.get('calibrator')
    planned_date_from = request.args.get('planned_date_from')
    planned_date_to = request.args.get('planned_date_to')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 20
    
    filters = {}
    if equipment_id:
        filters['equipment_id'] = equipment_id
    if status:
        filters['status'] = status
    if task_type:
        filters['task_type'] = task_type
    if calibrator:
        filters['calibrator'] = calibrator
    if planned_date_from:
        filters['planned_date_from'] = planned_date_from
    if planned_date_to:
        filters['planned_date_to'] = planned_date_to
    
    task_service = CalibrationTaskService()
    results = task_service.search_tasks(filters=filters if filters else None, page=page, per_page=per_page)
    
    return jsonify(results)


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def get_calibration_task(task_id):
    task_service = CalibrationTaskService()
    task = task_service.get_task(task_id)
    
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(task.to_dict())


@app.route('/api/tasks/<int:task_id>/accept', methods=['POST'])
def accept_calibration_task(task_id):
    data = request.json
    operator = data.get('operator')
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    
    task_service = CalibrationTaskService()
    task, error = task_service.accept_task(task_id, operator)
    
    if error:
        return jsonify({'errors': error}), 400
    
    return jsonify(task)


@app.route('/api/tasks/<int:task_id>/start', methods=['POST'])
def start_calibration_task(task_id):
    data = request.json
    operator = data.get('operator')
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    
    task_service = CalibrationTaskService()
    task, error = task_service.start_task(task_id, operator)
    
    if error:
        return jsonify({'errors': error}), 400
    
    return jsonify(task)


@app.route('/api/tasks/<int:task_id>/complete', methods=['POST'])
def complete_calibration_task(task_id):
    data = request.json
    operator = data.get('operator')
    execution_notes = data.get('execution_notes')
    measurement_data = data.get('measurement_data')
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    
    task_service = CalibrationTaskService()
    
    try:
        task, error = task_service.complete_task(
            task_id=task_id,
            operator=operator,
            execution_notes=execution_notes,
            measurement_data=json.dumps(measurement_data) if measurement_data else None
        )
        
        if error:
            return jsonify({'errors': error}), 400
        
        return jsonify(task)
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403


@app.route('/api/tasks/<int:task_id>/close', methods=['POST'])
def close_calibration_task_abnormal(task_id):
    data = request.json
    operator = data.get('operator')
    close_reason = data.get('close_reason')
    
    if not operator:
        return jsonify({'error': 'Operator is required'}), 400
    if not close_reason:
        return jsonify({'error': 'Close reason is required'}), 400
    
    task_service = CalibrationTaskService()
    
    try:
        task, error = task_service.close_task_abnormal(task_id, operator, close_reason)
        
        if error:
            return jsonify({'errors': error}), 400
        
        return jsonify(task)
    except PermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403


@app.route('/api/tasks/conflict/<int:equipment_id>', methods=['GET'])
def check_task_conflict(equipment_id):
    task_service = CalibrationTaskService()
    conflicting_tasks = task_service.check_equipment_conflict(equipment_id)
    
    return jsonify({
        'equipment_id': equipment_id,
        'has_conflict': len(conflicting_tasks) > 0,
        'conflicting_tasks': [{
            'task_id': t.id,
            'task_no': t.task_no,
            'status': t.status,
            'planned_date': t.planned_date.isoformat() if t.planned_date else None
        } for t in conflicting_tasks]
    })


@app.route('/api/tasks/calibrator/<calibrator>', methods=['GET'])
def get_tasks_by_calibrator(calibrator):
    status = request.args.get('status')
    
    task_service = CalibrationTaskService()
    tasks = task_service.get_tasks_by_calibrator(calibrator, status)
    
    return jsonify([task.to_dict() for task in tasks])


@app.route('/api/config/scheduler', methods=['GET'])
def get_scheduler_config():
    config_service = ConfigService()
    return jsonify(config_service.get_scheduler_config())


@app.route('/api/config/scheduler', methods=['PUT'])
def update_scheduler_config():
    data = request.json
    
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    
    config_service = ConfigService()
    updated = {}
    
    for key, value in data.items():
        updated[key] = config_service.set_scheduler_config(key, value)
    
    return jsonify({
        'message': 'Scheduler config updated',
        'updated': updated
    })


@app.errorhandler(TaskConflictException)
def handle_task_conflict(e):
    return jsonify({
        'error': e.message,
        'conflict': True,
        'conflicting_tasks': e.conflicting_tasks
    }), 409

@app.errorhandler(StatisticsPermissionDeniedException)
def handle_statistics_permission_denied(e):
    return jsonify({
        'error': e.message,
        'required_role': e.required_role,
        'operator_role': e.operator_role
    }), 403


@app.route('/api/statistics', methods=['GET'])
def get_statistics():
    operator = request.args.get('operator')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    try:
        stats_service = CalibrationStatisticsService()
        stats_service.check_statistics_permission(operator)
        stats = stats_service.get_statistics(operator, date_from, date_to)
        return jsonify(stats)
    except StatisticsPermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403


@app.route('/api/statistics/export', methods=['GET'])
def export_statistics():
    operator = request.args.get('operator')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    if not operator:
        return jsonify({'error': 'Operator is required'}), 400

    try:
        stats_service = CalibrationStatisticsService()
        csv_content = stats_service.export_statistics_csv(operator, date_from, date_to)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'calibration_statistics_{timestamp}.csv'

        return send_file(
            io.BytesIO(csv_content.encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    except StatisticsPermissionDeniedException as e:
        return jsonify({
            'error': e.message,
            'required_role': e.required_role,
            'operator_role': e.operator_role
        }), 403
    except Exception as e:
        if '超过限制' in str(e):
            return jsonify({'error': str(e)}), 400
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/statistics', methods=['GET'])
def get_statistics_config():
    config_service = ConfigService()
    return jsonify(config_service.get_statistics_config())


@app.route('/api/config/statistics', methods=['PUT'])
def update_statistics_config():
    data = request.json

    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400

    config_service = ConfigService()
    updated = {}

    for key, value in data.items():
        updated[key] = config_service.set_statistics_config(key, value)

    return jsonify({
        'message': 'Statistics config updated',
        'updated': updated
    })


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    ScheduledTaskService.start_scheduler(app)
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    finally:
        ScheduledTaskService.stop_scheduler()
