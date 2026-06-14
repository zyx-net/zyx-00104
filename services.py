from models import db, Certificate, Equipment, AuditLog, WorkflowStatus
from validators import CertificateValidator, CertificateImportSchema, parse_csv_to_json
from marshmallow import ValidationError
from datetime import datetime, timedelta, date
import json
import uuid
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

class ConfigService:
    def __init__(self):
        self._config = None

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        else:
            self._config = {'expiry_warning_days': 30}
            self._save_config()

    def _save_config(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2)

    def get_expiry_warning_days(self):
        if self._config is None:
            self._load_config()
        return self._config.get('expiry_warning_days', 30)

    def set_expiry_warning_days(self, days):
        if self._config is None:
            self._load_config()
        self._config['expiry_warning_days'] = days
        self._save_config()
        return days

    def get_config(self):
        if self._config is None:
            self._load_config()
        return self._config.copy()

class ExpiryWarningService:
    def get_expiring_certificates(self, days=None):
        if days is None:
            config_service = ConfigService()
            days = config_service.get_expiry_warning_days()

        today = date.today()
        expiry_date = today + timedelta(days=days)

        certs = Certificate.query.filter(
            Certificate.valid_until <= expiry_date,
            Certificate.valid_until >= today
        ).order_by(Certificate.valid_until).all()

        return certs

class BatchStatsService:
    def get_batch_statistics(self):
        from sqlalchemy import func, desc

        stats = db.session.query(
            Certificate.batch_id,
            Certificate.workflow_status,
            func.count(Certificate.id).label('count')
        ).group_by(Certificate.batch_id, Certificate.workflow_status).order_by(desc('count')).all()

        result = {}
        for batch_id, status, count in stats:
            if batch_id not in result:
                result[batch_id] = {
                    'total': 0
                }
            result[batch_id][status] = count
            result[batch_id]['total'] += count

        return result

class CertificateImportService:
    def __init__(self):
        self.validator = CertificateValidator()

    def import_certificates(self, data_list, operator, batch_id=None):
        if not batch_id:
            batch_id = str(uuid.uuid4())

        results = {
            'batch_id': batch_id,
            'total': len(data_list),
            'successful': 0,
            'failed': 0,
            'errors': [],
            'imported': []
        }

        imported_ids = []

        try:
            for idx, data in enumerate(data_list):
                result = self._import_single_certificate(data, operator, batch_id)
                if result['success']:
                    results['successful'] += 1
                    imported_ids.append(result['certificate_id'])
                    results['imported'].append(result['certificate_id'])
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'index': idx,
                        'cert_no': data.get('cert_no'),
                        'errors': result['errors']
                    })

            if results['failed'] > 0:
                for cert_id in imported_ids:
                    cert = Certificate.query.get(cert_id)
                    if cert:
                        db.session.delete(cert)
                db.session.commit()
                results['imported'] = []
                results['successful'] = 0
                return results, False

            db.session.commit()
            return results, True

        except Exception as e:
            db.session.rollback()
            for cert_id in imported_ids:
                cert = Certificate.query.get(cert_id)
                if cert:
                    db.session.delete(cert)
            db.session.commit()

            results['errors'].append({
                'index': -1,
                'error': f'Batch import failed: {str(e)}'
            })
            return results, False

    def _import_single_certificate(self, data, operator, batch_id):
        try:
            schema = CertificateImportSchema()
            validated_data = schema.load(data)

            equipment = Equipment.query.filter_by(equipment_no=validated_data['equipment_no']).first()
            if not equipment:
                return {
                    'success': False,
                    'errors': [{'field': 'equipment_no', 'error': f'Equipment {validated_data["equipment_no"]} not found'}]
                }

            is_valid, errors = self.validator.validate_certificate_data(validated_data, equipment)
            if not is_valid:
                return {
                    'success': False,
                    'errors': errors
                }

            existing_cert = Certificate.query.filter_by(cert_no=validated_data['cert_no']).first()
            if existing_cert:
                return {
                    'success': False,
                    'errors': [{'field': 'cert_no', 'error': f'Certificate {validated_data["cert_no"]} already exists'}]
                }

            cert = Certificate(
                cert_no=validated_data['cert_no'],
                batch_id=batch_id,
                equipment_id=equipment.id,
                calibration_date=validated_data['_parsed_cal_date'],
                valid_until=validated_data['_parsed_valid_until'],
                range_min=validated_data['range_min'],
                range_max=validated_data['range_max'],
                unit=validated_data['unit'],
                deviation=validated_data['deviation'],
                calibrator=validated_data.get('calibrator'),
                cert_file=validated_data.get('cert_file'),
                workflow_status=WorkflowStatus.DRAFT.value,
                version=1
            )

            db.session.add(cert)
            db.session.flush()

            details_for_audit = {
                k: v.isoformat() if hasattr(v, 'isoformat') else v
                for k, v in validated_data.items()
            }

            audit = AuditLog(
                operator=operator,
                action='import',
                resource_type='certificate',
                resource_id=cert.id,
                certificate_id=cert.id,
                batch_id=batch_id,
                details=json.dumps(details_for_audit),
                notes=f'Certificate imported by {operator}',
                decision_basis='Initial import',
                version=1,
                new_state=WorkflowStatus.DRAFT.value
            )
            db.session.add(audit)

            return {
                'success': True,
                'certificate_id': cert.id
            }

        except ValidationError as e:
            return {
                'success': False,
                'errors': [{'field': k, 'error': str(v)} for k, v in e.messages.items()]
            }
        except Exception as e:
            return {
                'success': False,
                'errors': [{'field': 'system', 'error': str(e)}]
            }

class WorkflowService:
    def __init__(self):
        self.errors = []

    def enter(self, certificate_id, operator, notes=''):
        return self._transition(certificate_id, operator, WorkflowStatus.ENTERED, 'enter', notes)

    def review(self, certificate_id, operator, notes='', decision_basis=''):
        return self._transition(certificate_id, operator, WorkflowStatus.REVIEWED, 'review', notes, decision_basis)

    def approve(self, certificate_id, operator, notes='', decision_basis=''):
        return self._transition(certificate_id, operator, WorkflowStatus.APPROVED, 'approve', notes, decision_basis)

    def release(self, certificate_id, operator, notes='', decision_basis=''):
        cert = Certificate.query.get(certificate_id)
        if not cert:
            return False, [{'error': 'Certificate not found'}]

        if operator == cert.entered_by:
            return False, [{'error': 'Operator cannot release their own entry', 'field': 'operator'}]

        return self._transition(certificate_id, operator, WorkflowStatus.RELEASED, 'release', notes, decision_basis)

    def limit(self, certificate_id, operator, notes='', decision_basis=''):
        return self._transition(certificate_id, operator, WorkflowStatus.LIMITED, 'limit', notes, decision_basis)

    def stop(self, certificate_id, operator, notes='', decision_basis=''):
        return self._transition(certificate_id, operator, WorkflowStatus.STOPPED, 'stop', notes, decision_basis)

    def _transition(self, certificate_id, operator, new_status, action, notes='', decision_basis=''):
        self.errors = []
        cert = Certificate.query.get(certificate_id)

        if not cert:
            self.errors.append({'error': 'Certificate not found'})
            return False, self.errors

        previous_status = cert.workflow_status
        previous_equipment_status = cert.equipment.status

        valid_transitions = {
            WorkflowStatus.DRAFT.value: [WorkflowStatus.ENTERED.value],
            WorkflowStatus.ENTERED.value: [WorkflowStatus.REVIEWED.value],
            WorkflowStatus.REVIEWED.value: [WorkflowStatus.APPROVED.value],
            WorkflowStatus.APPROVED.value: [WorkflowStatus.RELEASED.value, WorkflowStatus.LIMITED.value, WorkflowStatus.STOPPED.value]
        }

        if new_status.value not in valid_transitions.get(previous_status, []):
            self.errors.append({
                'error': f'Invalid transition from {previous_status} to {new_status.value}',
                'field': 'workflow_status'
            })
            return False, self.errors

        cert.workflow_status = new_status.value
        cert.version += 1
        cert.updated_at = datetime.utcnow()

        if new_status == WorkflowStatus.ENTERED:
            cert.entered_by = operator
            cert.entered_at = datetime.utcnow()
        elif new_status == WorkflowStatus.REVIEWED:
            cert.reviewed_by = operator
            cert.reviewed_at = datetime.utcnow()
        elif new_status == WorkflowStatus.APPROVED:
            cert.approved_by = operator
            cert.approved_at = datetime.utcnow()
        elif new_status == WorkflowStatus.RELEASED:
            cert.released_by = operator
            cert.released_at = datetime.utcnow()
            cert.equipment.status = 'active'
        elif new_status == WorkflowStatus.LIMITED:
            cert.released_by = operator
            cert.released_at = datetime.utcnow()
            cert.equipment.status = 'limited'
        elif new_status == WorkflowStatus.STOPPED:
            cert.released_by = operator
            cert.released_at = datetime.utcnow()
            cert.equipment.status = 'stopped'

        audit = AuditLog(
            operator=operator,
            action=action,
            resource_type='certificate',
            resource_id=cert.id,
            certificate_id=cert.id,
            batch_id=cert.batch_id,
            notes=notes,
            decision_basis=decision_basis,
            version=cert.version,
            previous_state=previous_status,
            new_state=new_status.value
        )
        db.session.add(audit)

        if new_status in [WorkflowStatus.RELEASED, WorkflowStatus.LIMITED, WorkflowStatus.STOPPED]:
            equipment_audit = AuditLog(
                operator=operator,
                action=f'equipment_{action}',
                resource_type='equipment',
                resource_id=cert.equipment.id,
                equipment_id=cert.equipment.id,
                certificate_id=cert.id,
                batch_id=cert.batch_id,
                notes=notes,
                decision_basis=decision_basis,
                version=cert.equipment.status,
                previous_state=previous_equipment_status,
                new_state=cert.equipment.status
            )
            db.session.add(equipment_audit)

        try:
            db.session.commit()
            return True, []
        except Exception as e:
            db.session.rollback()
            self.errors.append({'error': str(e)})
            return False, self.errors

class BatchWorkflowService:
    def __init__(self):
        self.workflow_service = WorkflowService()

    def batch_approve(self, certificate_ids, operator, notes='', decision_basis=''):
        results = {
            'total': len(certificate_ids),
            'successful': 0,
            'failed': 0,
            'results': []
        }

        for cert_id in certificate_ids:
            success, errors = self.workflow_service.approve(cert_id, operator, notes, decision_basis)
            cert = Certificate.query.get(cert_id)
            
            result_item = {
                'certificate_id': cert_id,
                'cert_no': cert.cert_no if cert else None,
                'success': success
            }
            
            if success:
                results['successful'] += 1
                result_item['workflow_status'] = cert.workflow_status
            else:
                results['failed'] += 1
                result_item['errors'] = errors
            
            results['results'].append(result_item)

        return results

    def batch_release(self, certificate_ids, operator, notes='', decision_basis=''):
        results = {
            'total': len(certificate_ids),
            'successful': 0,
            'failed': 0,
            'results': []
        }

        for cert_id in certificate_ids:
            cert = Certificate.query.get(cert_id)
            
            if not cert:
                results['failed'] += 1
                results['results'].append({
                    'certificate_id': cert_id,
                    'cert_no': None,
                    'success': False,
                    'errors': [{'error': 'Certificate not found'}]
                })
                continue

            if operator == cert.entered_by:
                results['failed'] += 1
                results['results'].append({
                    'certificate_id': cert_id,
                    'cert_no': cert.cert_no,
                    'success': False,
                    'errors': [{'error': 'Operator cannot release their own entry', 'field': 'operator'}]
                })
                continue

            success, errors = self.workflow_service.release(cert_id, operator, notes, decision_basis)
            
            result_item = {
                'certificate_id': cert_id,
                'cert_no': cert.cert_no,
                'success': success
            }
            
            if success:
                results['successful'] += 1
                result_item['workflow_status'] = cert.workflow_status
            else:
                results['failed'] += 1
                result_item['errors'] = errors
            
            results['results'].append(result_item)

        return results


class RevertService:
    def revert_last_workflow_change(self, certificate_id, operator, notes=''):
        cert = Certificate.query.get(certificate_id)
        if not cert:
            return False, [{'error': 'Certificate not found'}]

        last_audit = AuditLog.query.filter(
            AuditLog.certificate_id == certificate_id,
            AuditLog.resource_type == 'certificate',
            AuditLog.action.in_(['enter', 'review', 'approve', 'release', 'limit', 'stop']),
            AuditLog.reverted == False
        ).order_by(AuditLog.timestamp.desc()).first()

        if not last_audit:
            return False, [{'error': 'No workflow change to revert'}]

        previous_status = last_audit.previous_state
        if not previous_status:
            return False, [{'error': 'Cannot determine previous state'}]

        current_status = cert.workflow_status
        cert.workflow_status = previous_status
        cert.version += 1
        cert.updated_at = datetime.utcnow()

        if previous_status == WorkflowStatus.DRAFT.value:
            cert.entered_by = None
            cert.entered_at = None
            cert.reviewed_by = None
            cert.reviewed_at = None
            cert.approved_by = None
            cert.approved_at = None
            cert.released_by = None
            cert.released_at = None
        elif previous_status == WorkflowStatus.ENTERED.value:
            cert.reviewed_by = None
            cert.reviewed_at = None
            cert.approved_by = None
            cert.approved_at = None
            cert.released_by = None
            cert.released_at = None
        elif previous_status == WorkflowStatus.REVIEWED.value:
            cert.approved_by = None
            cert.approved_at = None
            cert.released_by = None
            cert.released_at = None
        elif previous_status == WorkflowStatus.APPROVED.value:
            cert.released_by = None
            cert.released_at = None

        if current_status in [WorkflowStatus.RELEASED.value, WorkflowStatus.LIMITED.value, WorkflowStatus.STOPPED.value]:
            equipment_audit = AuditLog.query.filter(
                AuditLog.certificate_id == certificate_id,
                AuditLog.resource_type == 'equipment',
                AuditLog.action.in_(['equipment_release', 'equipment_limit', 'equipment_stop'])
            ).order_by(AuditLog.timestamp.desc()).first()

            if equipment_audit and equipment_audit.previous_state:
                cert.equipment.status = equipment_audit.previous_state

        last_audit.reverted = True
        last_audit.reverted_by = operator
        last_audit.reverted_at = datetime.utcnow()

        revert_audit = AuditLog(
            operator=operator,
            action='revert',
            resource_type='certificate',
            resource_id=cert.id,
            certificate_id=cert.id,
            batch_id=cert.batch_id,
            notes=notes,
            decision_basis=f'Reverted {last_audit.action} by {operator}',
            version=cert.version,
            previous_state=current_status,
            new_state=previous_status,
            revert_log_id=last_audit.id
        )
        db.session.add(revert_audit)

        try:
            db.session.commit()
            return True, []
        except Exception as e:
            db.session.rollback()
            return False, [{'error': str(e)}]


class ExpiryAutoTransitionService:
    SYSTEM_OPERATOR = 'SYSTEM_AUTO_EXPIRY'

    def process_expired_certificates(self):
        today = date.today()
        
        expired_certs = Certificate.query.filter(
            Certificate.valid_until < today,
            Certificate.workflow_status.in_([
                WorkflowStatus.DRAFT.value,
                WorkflowStatus.ENTERED.value,
                WorkflowStatus.REVIEWED.value,
                WorkflowStatus.APPROVED.value
            ])
        ).all()

        results = {
            'processed': 0,
            'limited': 0,
            'stopped': 0,
            'equipment_updated': 0,
            'details': []
        }

        for cert in expired_certs:
            new_status = self._determine_expiry_status(cert)
            
            previous_status = cert.workflow_status
            cert.workflow_status = new_status.value
            cert.version += 1
            cert.updated_at = datetime.utcnow()
            cert.released_by = self.SYSTEM_OPERATOR
            cert.released_at = datetime.utcnow()

            audit = AuditLog(
                operator=self.SYSTEM_OPERATOR,
                action='auto_expiry_transition',
                resource_type='certificate',
                resource_id=cert.id,
                certificate_id=cert.id,
                batch_id=cert.batch_id,
                notes=f'Certificate auto-transitioned to {new_status.value} due to expiry (valid_until: {cert.valid_until})',
                decision_basis='System automatic expiry processing',
                version=cert.version,
                previous_state=previous_status,
                new_state=new_status.value
            )
            db.session.add(audit)

            results['processed'] += 1
            if new_status == WorkflowStatus.LIMITED:
                results['limited'] += 1
            else:
                results['stopped'] += 1

            results['details'].append({
                'certificate_id': cert.id,
                'cert_no': cert.cert_no,
                'previous_status': previous_status,
                'new_status': new_status.value,
                'valid_until': cert.valid_until.isoformat()
            })

        db.session.flush()
        
        equipment_updates = self._update_equipment_status()
        results['equipment_updated'] = equipment_updates

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

        return results

    def _determine_expiry_status(self, cert):
        equipment = cert.equipment
        if equipment and equipment.tolerance:
            if cert.deviation <= equipment.tolerance:
                return WorkflowStatus.LIMITED
            else:
                return WorkflowStatus.STOPPED
        return WorkflowStatus.STOPPED

    def _update_equipment_status(self):
        updated_count = 0
        equipment_ids = db.session.query(Certificate.equipment_id).filter(
            Certificate.workflow_status == WorkflowStatus.STOPPED.value
        ).distinct().all()
        
        for (eq_id,) in equipment_ids:
            equipment = Equipment.query.get(eq_id)
            if not equipment:
                continue

            all_certs = Certificate.query.filter_by(equipment_id=eq_id).all()
            if not all_certs:
                continue

            all_stopped = all(
                c.workflow_status == WorkflowStatus.STOPPED.value 
                for c in all_certs
            )

            if all_stopped and equipment.status != 'stopped':
                previous_status = equipment.status
                equipment.status = 'stopped'
                equipment.updated_at = datetime.utcnow()

                audit = AuditLog(
                    operator=self.SYSTEM_OPERATOR,
                    action='auto_expiry_equipment_stop',
                    resource_type='equipment',
                    resource_id=equipment.id,
                    equipment_id=equipment.id,
                    notes='Equipment auto-stopped due to all certificates expired and stopped',
                    decision_basis='System automatic expiry processing',
                    previous_state=previous_status,
                    new_state='stopped'
                )
                db.session.add(audit)
                updated_count += 1

        return updated_count


class CertificateSearchService:
    SAFE_FIELDS = [
        'id', 'cert_no', 'batch_id', 'equipment_id', 'equipment_no', 'equipment_name',
        'calibration_date', 'valid_until', 'range_min', 'range_max', 'unit',
        'deviation', 'calibrator', 'workflow_status',
        'entered_by', 'entered_at', 'reviewed_by', 'reviewed_at',
        'approved_by', 'approved_at', 'released_by', 'released_at',
        'version', 'created_at', 'updated_at'
    ]

    def search(self, filters=None, page=1, per_page=20, sort_by='valid_until', sort_order='asc'):
        query = Certificate.query.join(Equipment, Certificate.equipment_id == Equipment.id)

        if filters:
            query = self._apply_filters(query, filters)

        if sort_by == 'valid_until':
            query = query.order_by(
                Certificate.valid_until.asc() if sort_order == 'asc' else Certificate.valid_until.desc()
            )
        elif sort_by == 'calibration_date':
            query = query.order_by(
                Certificate.calibration_date.asc() if sort_order == 'asc' else Certificate.calibration_date.desc()
            )
        elif sort_by == 'created_at':
            query = query.order_by(
                Certificate.created_at.asc() if sort_order == 'asc' else Certificate.created_at.desc()
            )
        else:
            query = query.order_by(Certificate.valid_until.asc())

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return {
            'items': [self._to_safe_dict(cert) for cert in pagination.items],
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }

    def _apply_filters(self, query, filters):
        if filters.get('cert_no'):
            query = query.filter(Certificate.cert_no.ilike(f"%{filters['cert_no']}%"))

        if filters.get('workflow_status'):
            query = query.filter(Certificate.workflow_status == filters['workflow_status'])

        if filters.get('equipment_no'):
            query = query.filter(Equipment.equipment_no.ilike(f"%{filters['equipment_no']}%"))

        if filters.get('batch_id'):
            query = query.filter(Certificate.batch_id.ilike(f"%{filters['batch_id']}%"))

        if filters.get('calibration_date_from'):
            from dateutil import parser
            try:
                date_from = parser.parse(filters['calibration_date_from']).date()
                query = query.filter(Certificate.calibration_date >= date_from)
            except:
                pass

        if filters.get('calibration_date_to'):
            from dateutil import parser
            try:
                date_to = parser.parse(filters['calibration_date_to']).date()
                query = query.filter(Certificate.calibration_date <= date_to)
            except:
                pass

        if filters.get('operator'):
            operator = filters['operator']
            query = query.filter(
                db.or_(
                    Certificate.entered_by.ilike(f"%{operator}%"),
                    Certificate.reviewed_by.ilike(f"%{operator}%"),
                    Certificate.approved_by.ilike(f"%{operator}%"),
                    Certificate.released_by.ilike(f"%{operator}%")
                )
            )

        return query

    def _to_safe_dict(self, cert):
        full_dict = cert.to_dict()
        return {k: v for k, v in full_dict.items() if k in self.SAFE_FIELDS}


class ExportService:
    def export_by_equipment(self, equipment_id, format='json', valid_from=None, valid_to=None):
        query = Certificate.query.filter_by(equipment_id=equipment_id)
        query = self._add_valid_date_filter(query, valid_from, valid_to)
        certs = query.all()
        return self._format_output(certs, format)

    def export_by_batch(self, batch_id, format='json', valid_from=None, valid_to=None):
        query = Certificate.query.filter_by(batch_id=batch_id)
        query = self._add_valid_date_filter(query, valid_from, valid_to)
        certs = query.all()
        return self._format_output(certs, format)

    def export_all(self, format='json', valid_from=None, valid_to=None):
        query = Certificate.query
        query = self._add_valid_date_filter(query, valid_from, valid_to)
        certs = query.all()
        return self._format_output(certs, format)

    def _add_valid_date_filter(self, query, valid_from, valid_to):
        from dateutil import parser

        if valid_from:
            try:
                from_date = parser.parse(valid_from).date()
                query = query.filter(Certificate.valid_until >= from_date)
            except:
                pass

        if valid_to:
            try:
                to_date = parser.parse(valid_to).date()
                query = query.filter(Certificate.valid_until <= to_date)
            except:
                pass

        return query

    def _format_output(self, certs, format):
        if format == 'json':
            return json.dumps([cert.to_dict() for cert in certs], indent=2, ensure_ascii=False)
        elif format == 'csv':
            import csv
            import io
            output = io.StringIO()
            if not certs:
                return ''

            fieldnames = list(certs[0].to_dict().keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for cert in certs:
                writer.writerow(cert.to_dict())
            return output.getvalue()
        return ''
