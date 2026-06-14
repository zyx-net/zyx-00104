from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from models import db, Equipment, Certificate, AuditLog, WorkflowStatus
from services import CertificateImportService, WorkflowService, ExportService, ExpiryWarningService, BatchStatsService, ConfigService, BatchWorkflowService, RevertService, ExpiryAutoTransitionService, CertificateSearchService
from validators import parse_csv_to_json
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

@app.route('/api/audit', methods=['GET'])
def list_audit_logs():
    certificate_id = request.args.get('certificate_id')
    equipment_id = request.args.get('equipment_id')
    batch_id = request.args.get('batch_id')
    operator = request.args.get('operator')

    query = AuditLog.query

    if certificate_id:
        query = query.filter_by(certificate_id=int(certificate_id))
    if equipment_id:
        query = query.filter_by(equipment_id=int(equipment_id))
    if batch_id:
        query = query.filter_by(batch_id=batch_id)
    if operator:
        query = query.filter_by(operator=operator)

    logs = query.order_by(AuditLog.timestamp.desc()).all()
    return jsonify([log.to_dict() for log in logs])

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
        results = expiry_service.process_expired_certificates()
        return jsonify(results)
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

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
