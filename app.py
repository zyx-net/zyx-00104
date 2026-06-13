from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from models import db, Equipment, Certificate, AuditLog, WorkflowStatus
from services import CertificateImportService, WorkflowService, ExportService
from validators import parse_csv_to_json
import os
import json

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
    operator = data.get('operator', 'system')
    batch_id = data.get('batch_id')

    content_type = request.content_type or ''
    if 'application/json' in content_type:
        if 'data' in data:
            data_list = data['data']
        else:
            data_list = [data]
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
        return jsonify({'errors': errors, 'message': 'Release failed'}, 400)

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

    export_service = ExportService()
    result = export_service.export_by_equipment(equipment_id, format_type)

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

    export_service = ExportService()
    result = export_service.export_by_batch(batch_id, format_type)

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

    export_service = ExportService()
    result = export_service.export_all(format_type)

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

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
