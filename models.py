from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from enum import Enum

db = SQLAlchemy()

class UserRole(Enum):
    OPERATOR = "operator"
    METROLOGIST = "metrologist"
    SUPERVISOR = "supervisor"

class WorkflowStatus(Enum):
    DRAFT = "draft"
    ENTERED = "entered"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    RELEASED = "released"
    LIMITED = "limited"
    STOPPED = "stopped"

class DeviceStatus(Enum):
    ACTIVE = "active"
    LIMITED = "limited"
    STOPPED = "stopped"

class ReportStatus(Enum):
    GENERATED = "generated"
    REVOKED = "revoked"
    OVERWRITTEN = "overwritten"

class Equipment(db.Model):
    __tablename__ = 'equipment'

    id = db.Column(db.Integer, primary_key=True)
    equipment_no = db.Column(db.String(100), unique=True, nullable=False, index=True)
    equipment_name = db.Column(db.String(200), nullable=False)
    model_spec = db.Column(db.String(200))
    manufacturer = db.Column(db.String(200))
    range_min = db.Column(db.Float)
    range_max = db.Column(db.Float)
    unit = db.Column(db.String(50))
    tolerance = db.Column(db.Float)
    location = db.Column(db.String(200))
    status = db.Column(db.String(20), default=DeviceStatus.ACTIVE.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    certificates = db.relationship('Certificate', back_populates='equipment', lazy='dynamic')
    audit_logs = db.relationship('AuditLog', back_populates='equipment', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'equipment_no': self.equipment_no,
            'equipment_name': self.equipment_name,
            'model_spec': self.model_spec,
            'manufacturer': self.manufacturer,
            'range_min': self.range_min,
            'range_max': self.range_max,
            'unit': self.unit,
            'tolerance': self.tolerance,
            'location': self.location,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default=UserRole.OPERATOR.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Certificate(db.Model):
    __tablename__ = 'certificates'

    id = db.Column(db.Integer, primary_key=True)
    cert_no = db.Column(db.String(100), nullable=False, index=True)
    batch_id = db.Column(db.String(100), index=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    calibration_date = db.Column(db.Date, nullable=False)
    valid_until = db.Column(db.Date, nullable=False)
    range_min = db.Column(db.Float, nullable=False)
    range_max = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(50), nullable=False)
    deviation = db.Column(db.Float, nullable=False)
    calibrator = db.Column(db.String(100))
    cert_file = db.Column(db.Text)
    workflow_status = db.Column(db.String(20), default=WorkflowStatus.DRAFT.value)
    entered_by = db.Column(db.String(100))
    entered_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.String(100))
    reviewed_at = db.Column(db.DateTime)
    approved_by = db.Column(db.String(100))
    approved_at = db.Column(db.DateTime)
    released_by = db.Column(db.String(100))
    released_at = db.Column(db.DateTime)
    version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    equipment = db.relationship('Equipment', back_populates='certificates')
    audit_logs = db.relationship('AuditLog', back_populates='certificate', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'cert_no': self.cert_no,
            'batch_id': self.batch_id,
            'equipment_id': self.equipment_id,
            'equipment_no': self.equipment.equipment_no if self.equipment else None,
            'equipment_name': self.equipment.equipment_name if self.equipment else None,
            'calibration_date': self.calibration_date.isoformat() if self.calibration_date else None,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
            'range_min': self.range_min,
            'range_max': self.range_max,
            'unit': self.unit,
            'deviation': self.deviation,
            'calibrator': self.calibrator,
            'cert_file': self.cert_file,
            'workflow_status': self.workflow_status,
            'entered_by': self.entered_by,
            'entered_at': self.entered_at.isoformat() if self.entered_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'released_by': self.released_by,
            'released_at': self.released_at.isoformat() if self.released_at else None,
            'version': self.version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    operator = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.Integer)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'))
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificates.id'))
    batch_id = db.Column(db.String(100), index=True)
    details = db.Column(db.Text)
    notes = db.Column(db.Text)
    decision_basis = db.Column(db.Text)
    version = db.Column(db.Integer, default=1)
    previous_state = db.Column(db.Text)
    new_state = db.Column(db.Text)
    reverted = db.Column(db.Boolean, default=False)
    reverted_by = db.Column(db.String(100))
    reverted_at = db.Column(db.DateTime)
    revert_log_id = db.Column(db.Integer, db.ForeignKey('audit_logs.id'))
    denied_reason = db.Column(db.Text)

    equipment = db.relationship('Equipment', back_populates='audit_logs')
    certificate = db.relationship('Certificate', back_populates='audit_logs')

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'operator': self.operator,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'equipment_id': self.equipment_id,
            'certificate_id': self.certificate_id,
            'batch_id': self.batch_id,
            'details': self.details,
            'notes': self.notes,
            'decision_basis': self.decision_basis,
            'version': self.version,
            'previous_state': self.previous_state,
            'new_state': self.new_state,
            'reverted': self.reverted,
            'reverted_by': self.reverted_by,
            'reverted_at': self.reverted_at.isoformat() if self.reverted_at else None,
            'revert_log_id': self.revert_log_id,
            'denied_reason': self.denied_reason
        }

class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    report_no = db.Column(db.String(100), nullable=False, index=True)
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificates.id'), nullable=False)
    equipment_no = db.Column(db.String(100), nullable=False, index=True)
    calibration_date = db.Column(db.Date, nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default=ReportStatus.GENERATED.value)
    decision_result = db.Column(db.String(50))
    standard_uncertainty = db.Column(db.Float)
    expanded_uncertainty = db.Column(db.Float)
    coverage_factor = db.Column(db.Float)
    generated_by = db.Column(db.String(100), nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    version = db.Column(db.Integer, default=1)
    previous_version = db.Column(db.Integer)
    revoked = db.Column(db.Boolean, default=False)
    revoked_by = db.Column(db.String(100))
    revoked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    certificate = db.relationship('Certificate', backref='reports')

    def to_dict(self):
        return {
            'id': self.id,
            'report_no': self.report_no,
            'certificate_id': self.certificate_id,
            'equipment_no': self.equipment_no,
            'calibration_date': self.calibration_date.isoformat() if self.calibration_date else None,
            'file_path': self.file_path,
            'file_name': self.file_name,
            'status': self.status,
            'decision_result': self.decision_result,
            'standard_uncertainty': self.standard_uncertainty,
            'expanded_uncertainty': self.expanded_uncertainty,
            'coverage_factor': self.coverage_factor,
            'generated_by': self.generated_by,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'version': self.version,
            'previous_version': self.previous_version,
            'revoked': self.revoked,
            'revoked_by': self.revoked_by,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class ReportTemplate(db.Model):
    __tablename__ = 'report_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    template_content = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'template_content': self.template_content,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
