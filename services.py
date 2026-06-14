from models import db, Certificate, Equipment, AuditLog, WorkflowStatus, User, UserRole, Report, ReportStatus
from validators import CertificateValidator, CertificateImportSchema, parse_csv_to_json
from marshmallow import ValidationError
from datetime import datetime, timedelta, date
import json
import uuid
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')


class PermissionDeniedException(Exception):
    def __init__(self, message, required_role, operator_role, action, resource_type=None, resource_id=None):
        self.message = message
        self.required_role = required_role
        self.operator_role = operator_role
        self.action = action
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(self.message)


class RolePermissionService:
    ROLE_HIERARCHY = {
        UserRole.SUPERVISOR.value: ['import', 'enter', 'review', 'approve', 'release', 'limit', 'stop', 'revert'],
        UserRole.METROLOGIST.value: ['import', 'enter', 'review'],
        UserRole.OPERATOR.value: ['import', 'enter']
    }

    REQUIRED_ROLES = {
        'import': [UserRole.OPERATOR.value, UserRole.METROLOGIST.value, UserRole.SUPERVISOR.value],
        'enter': [UserRole.OPERATOR.value, UserRole.METROLOGIST.value, UserRole.SUPERVISOR.value],
        'review': [UserRole.METROLOGIST.value, UserRole.SUPERVISOR.value],
        'approve': [UserRole.SUPERVISOR.value],
        'release': [UserRole.SUPERVISOR.value],
        'limit': [UserRole.SUPERVISOR.value],
        'stop': [UserRole.SUPERVISOR.value],
        'revert': [UserRole.SUPERVISOR.value]
    }

    @staticmethod
    def get_user_role(username):
        user = User.query.filter_by(username=username).first()
        if user:
            return user.role
        return UserRole.OPERATOR.value

    @staticmethod
    def can_perform_action(username, action):
        role = RolePermissionService.get_user_role(username)
        allowed_roles = RolePermissionService.REQUIRED_ROLES.get(action, [])
        return role in allowed_roles

    @staticmethod
    def check_permission(username, action, resource_type=None, resource_id=None):
        role = RolePermissionService.get_user_role(username)
        allowed_roles = RolePermissionService.REQUIRED_ROLES.get(action, [])

        if role not in allowed_roles:
            required = '/'.join(RolePermissionService._get_role_display_name(r) for r in allowed_roles)
            denied_reason = f"Action '{action}' requires role: {required}, but user has role: {RolePermissionService._get_role_display_name(role)}"

            audit = AuditLog(
                operator=username,
                action='permission_denied',
                resource_type=resource_type or 'system',
                resource_id=resource_id,
                notes=denied_reason,
                version=1,
                denied_reason=denied_reason
            )
            db.session.add(audit)
            db.session.commit()

            raise PermissionDeniedException(
                message=denied_reason,
                required_role=allowed_roles,
                operator_role=role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id
            )

        return True

    @staticmethod
    def _get_role_display_name(role):
        role_names = {
            UserRole.OPERATOR.value: '录入员',
            UserRole.METROLOGIST.value: '计量员',
            UserRole.SUPERVISOR.value: '主管'
        }
        return role_names.get(role, role)


class UserService:
    @staticmethod
    def create_user(username, role):
        if role not in [r.value for r in UserRole]:
            raise ValueError(f"Invalid role: {role}")

        existing = User.query.filter_by(username=username).first()
        if existing:
            raise ValueError(f"User {username} already exists")

        user = User(username=username, role=role)
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def get_user(username):
        return User.query.filter_by(username=username).first()

    @staticmethod
    def update_user_role(username, new_role):
        user = User.query.filter_by(username=username).first()
        if not user:
            raise ValueError(f"User {username} not found")

        if new_role not in [r.value for r in UserRole]:
            raise ValueError(f"Invalid role: {new_role}")

        user.role = new_role
        db.session.commit()
        return user

    @staticmethod
    def list_users():
        return User.query.all()


class ConfigService:
    _config = None
    _config_mtime = 0
    _auto_reload_thread = None
    _stop_event = None

    def __init__(self):
        if self._config is None:
            self._load_config()
            self._start_auto_reload()

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                self._config_mtime = os.path.getmtime(CONFIG_FILE)
            except Exception as e:
                pass
        else:
            self._config = {'expiry_warning_days': 30, 'expiry_check_interval_hours': 24}
            self._save_config()

    def _save_config(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2)

    def _start_auto_reload(self):
        if self._auto_reload_thread is not None and self._auto_reload_thread.is_alive():
            return

        self._stop_event = None
        
        def monitor_config():
            import time
            while True:
                try:
                    if os.path.exists(CONFIG_FILE):
                        current_mtime = os.path.getmtime(CONFIG_FILE)
                        if current_mtime != self._config_mtime:
                            self._load_config()
                    time.sleep(self.get_reload_interval_seconds())
                except Exception:
                    time.sleep(1)

        self._auto_reload_thread = __import__('threading').Thread(target=monitor_config, daemon=True)
        self._auto_reload_thread.start()

    def _check_reload(self):
        if os.path.exists(CONFIG_FILE):
            current_mtime = os.path.getmtime(CONFIG_FILE)
            if current_mtime != self._config_mtime:
                self._load_config()

    def get_expiry_warning_days(self):
        self._check_reload()
        return self._config.get('expiry_warning_days', 30)

    def set_expiry_warning_days(self, days):
        self._check_reload()
        self._config['expiry_warning_days'] = days
        self._save_config()
        return days

    def get_expiry_check_interval_hours(self):
        self._check_reload()
        return self._config.get('expiry_check_interval_hours', 24)

    def set_expiry_check_interval_hours(self, hours):
        self._check_reload()
        self._config['expiry_check_interval_hours'] = hours
        self._save_config()
        return hours

    def get_last_expiry_check_time(self):
        self._check_reload()
        return self._config.get('last_expiry_check_time')

    def set_last_expiry_check_time(self, timestamp):
        self._check_reload()
        self._config['last_expiry_check_time'] = timestamp
        self._save_config()

    def get_expiry_check_in_progress(self):
        self._check_reload()
        return self._config.get('expiry_check_in_progress', False)

    def set_expiry_check_in_progress(self, in_progress):
        self._check_reload()
        self._config['expiry_check_in_progress'] = in_progress
        self._save_config()

    def get_config(self):
        self._check_reload()
        return self._config.copy()

    def get_report_config(self):
        self._check_reload()
        return self._config.get('report', {})

    def get_reload_interval_seconds(self):
        self._check_reload()
        report_config = self._config.get('report', {})
        return report_config.get('reload_interval_seconds', 5)

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
        RolePermissionService.check_permission(operator, 'import', 'system')
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
        RolePermissionService.check_permission(operator, 'enter', 'certificate', certificate_id)
        return self._transition(certificate_id, operator, WorkflowStatus.ENTERED, 'enter', notes)

    def review(self, certificate_id, operator, notes='', decision_basis=''):
        RolePermissionService.check_permission(operator, 'review', 'certificate', certificate_id)
        return self._transition(certificate_id, operator, WorkflowStatus.REVIEWED, 'review', notes, decision_basis)

    def approve(self, certificate_id, operator, notes='', decision_basis=''):
        RolePermissionService.check_permission(operator, 'approve', 'certificate', certificate_id)
        return self._transition(certificate_id, operator, WorkflowStatus.APPROVED, 'approve', notes, decision_basis)

    def release(self, certificate_id, operator, notes='', decision_basis=''):
        RolePermissionService.check_permission(operator, 'release', 'certificate', certificate_id)
        cert = Certificate.query.get(certificate_id)
        if not cert:
            return False, [{'error': 'Certificate not found'}]

        if operator == cert.entered_by:
            return False, [{'error': 'Operator cannot release their own entry', 'field': 'operator'}]

        return self._transition(certificate_id, operator, WorkflowStatus.RELEASED, 'release', notes, decision_basis)

    def limit(self, certificate_id, operator, notes='', decision_basis=''):
        RolePermissionService.check_permission(operator, 'limit', 'certificate', certificate_id)
        return self._transition(certificate_id, operator, WorkflowStatus.LIMITED, 'limit', notes, decision_basis)

    def stop(self, certificate_id, operator, notes='', decision_basis=''):
        RolePermissionService.check_permission(operator, 'stop', 'certificate', certificate_id)
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
        try:
            RolePermissionService.check_permission(operator, 'approve', 'system')
        except PermissionDeniedException as e:
            return {
                'total': len(certificate_ids),
                'successful': 0,
                'failed': len(certificate_ids),
                'results': [
                    {
                        'certificate_id': cert_id,
                        'cert_no': Certificate.query.get(cert_id).cert_no if Certificate.query.get(cert_id) else None,
                        'success': False,
                        'errors': [str(e)]
                    } for cert_id in certificate_ids
                ]
            }

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
        try:
            RolePermissionService.check_permission(operator, 'release', 'system')
        except PermissionDeniedException as e:
            return {
                'total': len(certificate_ids),
                'successful': 0,
                'failed': len(certificate_ids),
                'results': [
                    {
                        'certificate_id': cert_id,
                        'cert_no': Certificate.query.get(cert_id).cert_no if Certificate.query.get(cert_id) else None,
                        'success': False,
                        'errors': [str(e)]
                    } for cert_id in certificate_ids
                ]
            }

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
        RolePermissionService.check_permission(operator, 'revert', 'certificate', certificate_id)
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


class ExpiryCheckConflictException(Exception):
    def __init__(self, message="Another expiry check is already in progress"):
        self.message = message
        super().__init__(self.message)


class ExpiryAutoTransitionService:
    SYSTEM_OPERATOR = 'SYSTEM_AUTO_EXPIRY'

    def process_expired_certificates(self, source='manual'):
        config_service = ConfigService()

        if config_service.get_expiry_check_in_progress():
            raise ExpiryCheckConflictException()

        config_service.set_expiry_check_in_progress(True)
        try:
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
                    decision_basis=f'System automatic expiry processing (source: {source})',
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

            config_service.set_last_expiry_check_time(datetime.utcnow().isoformat())

            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                raise e

            return results

        finally:
            config_service.set_expiry_check_in_progress(False)

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


class ScheduledTaskService:
    _scheduler_thread = None
    _stop_event = None

    @classmethod
    def start_scheduler(cls, app):
        from threading import Thread, Event
        import time

        if cls._scheduler_thread is not None and cls._scheduler_thread.is_alive():
            return

        cls._stop_event = Event()
        cls._scheduler_thread = Thread(target=cls._scheduler_loop, args=(app, cls._stop_event), daemon=True)
        cls._scheduler_thread.start()

    @classmethod
    def stop_scheduler(cls):
        if cls._stop_event is not None:
            cls._stop_event.set()
        if cls._scheduler_thread is not None:
            cls._scheduler_thread.join(timeout=5)

    @classmethod
    def _scheduler_loop(cls, app, stop_event):
        import time
        from datetime import datetime

        while not stop_event.is_set():
            with app.app_context():
                try:
                    config_service = ConfigService()
                    interval_hours = config_service.get_expiry_check_interval_hours()
                    last_check = config_service.get_last_expiry_check_time()

                    should_run = True
                    if last_check:
                        try:
                            last_time = datetime.fromisoformat(last_check)
                            hours_since_last = (datetime.utcnow() - last_time).total_seconds() / 3600
                            should_run = hours_since_last >= interval_hours
                        except:
                            pass

                    if should_run:
                        expiry_service = ExpiryAutoTransitionService()
                        try:
                            expiry_service.process_expired_certificates(source='scheduled')
                        except ExpiryCheckConflictException:
                            pass
                except Exception as e:
                    pass

            time.sleep(60)

    @classmethod
    def get_scheduler_status(cls):
        return {
            'running': cls._scheduler_thread is not None and cls._scheduler_thread.is_alive(),
            'last_check_time': ConfigService().get_last_expiry_check_time(),
            'check_interval_hours': ConfigService().get_expiry_check_interval_hours(),
            'check_in_progress': ConfigService().get_expiry_check_in_progress()
        }


class ReportGenerationConflictException(Exception):
    def __init__(self, message, existing_report):
        self.message = message
        self.existing_report = existing_report
        super().__init__(self.message)


class CertificateLockedException(Exception):
    def __init__(self, message, certificate_ids):
        self.message = message
        self.certificate_ids = certificate_ids
        super().__init__(self.message)


class ReportService:
    REQUIRED_ROLE_FOR_GENERATION = UserRole.SUPERVISOR.value
    REQUIRED_ROLE_FOR_PREVIEW = [UserRole.SUPERVISOR.value, UserRole.METROLOGIST.value]

    def __init__(self):
        self._lock_cache = {}

    def _get_report_config(self, force_reload=False):
        config_service = ConfigService()
        return config_service.get_report_config()

    def _get_storage_path(self):
        config = self._get_report_config()
        path = config.get('storage_path', './reports')
        os.makedirs(path, exist_ok=True)
        return os.path.abspath(path)

    def _determine_decision_result(self, certificate):
        config = self._get_report_config()
        decision_rules = config.get('decision_rules', {})
        
        deviation = certificate.deviation
        tolerance = certificate.equipment.tolerance if certificate.equipment else 0
        
        if deviation <= tolerance:
            return decision_rules.get('qualified', {}).get('description', '合格')
        elif deviation > tolerance * 2:
            return decision_rules.get('unqualified', {}).get('description', '不合格')
        else:
            return decision_rules.get('limited', {}).get('description', '限用')

    def _generate_report_no(self, certificate):
        return f"RPT-{certificate.equipment.equipment_no}-{certificate.calibration_date.strftime('%Y%m%d')}"

    def _generate_file_name(self, certificate, version=1):
        equipment_no = certificate.equipment.equipment_no
        date_str = certificate.calibration_date.strftime('%Y%m%d')
        if version > 1:
            return f"{equipment_no}_{date_str}_v{version}.json"
        return f"{equipment_no}_{date_str}.json"

    def _generate_report_content(self, certificate, operator, decision_result):
        config = self._get_report_config()
        template = config.get('template', {})
        
        report_data = {
            'report_no': self._generate_report_no(certificate),
            'header': template.get('header', '校准证书报告'),
            'certificate': certificate.to_dict(),
            'equipment': certificate.equipment.to_dict() if certificate.equipment else {},
            'decision_result': decision_result,
            'uncertainty': {
                'standard_uncertainty': None,
                'expanded_uncertainty': None,
                'coverage_factor': None
            },
            'generated_by': operator,
            'generated_at': datetime.utcnow().isoformat(),
            'footer': template.get('footer', '计量校准中心')
        }
        
        return json.dumps(report_data, indent=2, ensure_ascii=False)

    def _check_certificate_locked(self, certificate_id):
        return self._lock_cache.get(certificate_id, False)

    def _lock_certificates(self, certificate_ids):
        for cert_id in certificate_ids:
            self._lock_cache[cert_id] = True

    def _unlock_certificates(self, certificate_ids):
        for cert_id in certificate_ids:
            self._lock_cache.pop(cert_id, None)

    def check_generation_permission(self, operator):
        role = RolePermissionService.get_user_role(operator)
        if role != self.REQUIRED_ROLE_FOR_GENERATION:
            denied_reason = f"Report generation requires supervisor role, but user has: {role}"
            audit = AuditLog(
                operator=operator,
                action='permission_denied',
                resource_type='report',
                notes=denied_reason,
                denied_reason=denied_reason
            )
            db.session.add(audit)
            db.session.commit()
            raise PermissionDeniedException(
                message=denied_reason,
                required_role=[self.REQUIRED_ROLE_FOR_GENERATION],
                operator_role=role,
                action='generate_report',
                resource_type='report'
            )
        return True

    def check_preview_permission(self, operator):
        role = RolePermissionService.get_user_role(operator)
        if role not in self.REQUIRED_ROLE_FOR_PREVIEW:
            denied_reason = f"Report preview requires supervisor or metrologist role, but user has: {role}"
            raise PermissionDeniedException(
                message=denied_reason,
                required_role=self.REQUIRED_ROLE_FOR_PREVIEW,
                operator_role=role,
                action='preview_report',
                resource_type='report'
            )
        return True

    def get_existing_report(self, certificate_id):
        return Report.query.filter(
            Report.certificate_id == certificate_id,
            Report.revoked == False
        ).order_by(Report.version.desc()).first()

    def has_conflict(self, certificate_id):
        existing = self.get_existing_report(certificate_id)
        return existing is not None

    def preview_report(self, certificate_id, operator):
        self.check_preview_permission(operator)
        
        certificate = Certificate.query.get(certificate_id)
        if not certificate:
            return None, {'error': 'Certificate not found'}
        
        if certificate.workflow_status not in [
            WorkflowStatus.APPROVED.value,
            WorkflowStatus.RELEASED.value,
            WorkflowStatus.LIMITED.value
        ]:
            return None, {'error': 'Certificate must be approved or released to generate report'}
        
        decision_result = self._determine_decision_result(certificate)
        content = self._generate_report_content(certificate, operator, decision_result)
        
        existing_report = self.get_existing_report(certificate_id)
        
        return {
            'preview': json.loads(content),
            'has_existing_report': existing_report is not None,
            'existing_version': existing_report.version if existing_report else None,
            'certificate_status': certificate.workflow_status
        }, None

    def generate_report(self, certificate_id, operator, force_overwrite=False, skip_lock_check=False):
        self.check_generation_permission(operator)
        
        certificate = Certificate.query.get(certificate_id)
        if not certificate:
            return None, {'error': 'Certificate not found'}
        
        if certificate.workflow_status not in [
            WorkflowStatus.APPROVED.value,
            WorkflowStatus.RELEASED.value,
            WorkflowStatus.LIMITED.value
        ]:
            return None, {'error': 'Certificate must be approved or released to generate report'}
        
        if not skip_lock_check and self._check_certificate_locked(certificate_id):
            return None, {'error': 'Certificate is locked by another operation'}
        
        existing_report = self.get_existing_report(certificate_id)
        
        if existing_report and not force_overwrite:
            raise ReportGenerationConflictException(
                message=f"Report already exists for certificate {certificate_id}. Version: {existing_report.version}",
                existing_report=existing_report
            )
        
        decision_result = self._determine_decision_result(certificate)
        
        if existing_report:
            new_version = existing_report.version + 1
            
            existing_report.status = ReportStatus.OVERWRITTEN.value
            existing_report.revoked = True
            existing_report.revoked_by = operator
            existing_report.revoked_at = datetime.utcnow()
            
            audit = AuditLog(
                operator=operator,
                action='report_overwrite',
                resource_type='report',
                resource_id=existing_report.id,
                certificate_id=certificate_id,
                equipment_id=certificate.equipment_id,
                notes=f"Report version {existing_report.version} overwritten by version {new_version}",
                decision_basis='Report regeneration requested',
                version=new_version,
                previous_state=json.dumps({
                    'report_id': existing_report.id,
                    'version': existing_report.version,
                    'status': existing_report.status
                }),
                new_state=f"version:{new_version},status:{ReportStatus.GENERATED.value}"
            )
            db.session.add(audit)
        else:
            new_version = 1
        
        file_name = self._generate_file_name(certificate, new_version)
        file_path = os.path.join(self._get_storage_path(), file_name)
        
        content = self._generate_report_content(certificate, operator, decision_result)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        report = Report(
            report_no=self._generate_report_no(certificate),
            certificate_id=certificate_id,
            equipment_no=certificate.equipment.equipment_no,
            calibration_date=certificate.calibration_date,
            file_path=file_path,
            file_name=file_name,
            status=ReportStatus.GENERATED.value,
            decision_result=decision_result,
            generated_by=operator,
            generated_at=datetime.utcnow(),
            version=new_version,
            previous_version=existing_report.version if existing_report else None
        )
        
        db.session.add(report)
        
        generation_audit = AuditLog(
            operator=operator,
            action='report_generate',
            resource_type='report',
            resource_id=report.id if report.id else 0,
            certificate_id=certificate_id,
            equipment_id=certificate.equipment_id,
            notes=f"Report generated: {file_name}",
            decision_basis='Report generation requested',
            version=new_version,
            new_state=ReportStatus.GENERATED.value
        )
        db.session.add(generation_audit)
        
        db.session.flush()
        generation_audit.resource_id = report.id
        
        db.session.commit()
        
        return report.to_dict(), None

    def batch_generate_reports(self, certificate_ids, operator):
        self.check_generation_permission(operator)
        
        locked_certs = [cid for cid in certificate_ids if self._check_certificate_locked(cid)]
        if locked_certs:
            raise CertificateLockedException(
                message=f"Some certificates are locked: {locked_certs}",
                certificate_ids=locked_certs
            )
        
        self._lock_certificates(certificate_ids)
        
        results = {
            'total': len(certificate_ids),
            'successful': 0,
            'failed': 0,
            'results': [],
            'batch_id': str(uuid.uuid4())
        }
        
        try:
            for cert_id in certificate_ids:
                certificate = Certificate.query.get(cert_id)
                
                if not certificate:
                    results['failed'] += 1
                    results['results'].append({
                        'certificate_id': cert_id,
                        'success': False,
                        'errors': ['Certificate not found']
                    })
                    continue
                
                if certificate.workflow_status not in [
                    WorkflowStatus.APPROVED.value,
                    WorkflowStatus.RELEASED.value,
                    WorkflowStatus.LIMITED.value
                ]:
                    results['failed'] += 1
                    results['results'].append({
                        'certificate_id': cert_id,
                        'cert_no': certificate.cert_no,
                        'success': False,
                        'errors': ['Certificate must be approved or released']
                    })
                    continue
                
                try:
                    report_data, error = self.generate_report(cert_id, operator, force_overwrite=True, skip_lock_check=True)
                    if error:
                        results['failed'] += 1
                        results['results'].append({
                            'certificate_id': cert_id,
                            'cert_no': certificate.cert_no,
                            'success': False,
                            'errors': [error.get('error', 'Unknown error')]
                        })
                    else:
                        results['successful'] += 1
                        results['results'].append({
                            'certificate_id': cert_id,
                            'cert_no': certificate.cert_no,
                            'success': True,
                            'report_id': report_data['id'],
                            'report_no': report_data['report_no'],
                            'version': report_data['version']
                        })
                except Exception as e:
                    results['failed'] += 1
                    results['results'].append({
                        'certificate_id': cert_id,
                        'cert_no': certificate.cert_no,
                        'success': False,
                        'errors': [str(e)]
                    })
            
            return results
        
        finally:
            self._unlock_certificates(certificate_ids)

    def search_reports(self, filters=None):
        query = Report.query
        
        if filters:
            if filters.get('equipment_no'):
                query = query.filter(Report.equipment_no.ilike(f"%{filters['equipment_no']}%"))
            
            if filters.get('certificate_id'):
                query = query.filter(Report.certificate_id == filters['certificate_id'])
            
            if filters.get('status'):
                query = query.filter(Report.status == filters['status'])
            
            if filters.get('calibration_date_from'):
                from dateutil import parser
                try:
                    date_from = parser.parse(filters['calibration_date_from']).date()
                    query = query.filter(Report.calibration_date >= date_from)
                except:
                    pass
            
            if filters.get('calibration_date_to'):
                from dateutil import parser
                try:
                    date_to = parser.parse(filters['calibration_date_to']).date()
                    query = query.filter(Report.calibration_date <= date_to)
                except:
                    pass
            
            if filters.get('generated_by'):
                query = query.filter(Report.generated_by.ilike(f"%{filters['generated_by']}%"))
        
        reports = query.order_by(Report.generated_at.desc()).all()
        return [report.to_dict() for report in reports]

    def get_report_by_id(self, report_id):
        return Report.query.get(report_id)

    def revoke_report(self, report_id, operator):
        self.check_generation_permission(operator)
        
        report = Report.query.get(report_id)
        if not report:
            return None, {'error': 'Report not found'}
        
        if report.revoked:
            return None, {'error': 'Report is already revoked'}
        
        report.revoked = True
        report.revoked_by = operator
        report.revoked_at = datetime.utcnow()
        report.status = ReportStatus.REVOKED.value
        
        audit = AuditLog(
            operator=operator,
            action='report_revoke',
            resource_type='report',
            resource_id=report.id,
            certificate_id=report.certificate_id,
            equipment_id=report.equipment_no,
            notes=f"Report revoked: {report.report_no}",
            decision_basis='Report revocation requested',
            version=report.version,
            previous_state=ReportStatus.GENERATED.value,
            new_state=ReportStatus.REVOKED.value
        )
        db.session.add(audit)
        
        db.session.commit()
        
        return report.to_dict(), None
