from datetime import datetime
from dateutil import parser
from marshmallow import Schema, fields, validates, ValidationError, post_load
import json

class CertificateImportSchema(Schema):
    cert_no = fields.String(required=True)
    equipment_no = fields.String(required=True)
    calibration_date = fields.String(required=True)
    valid_until = fields.String(required=True)
    range_min = fields.Float(required=True)
    range_max = fields.Float(required=True)
    unit = fields.String(required=True)
    deviation = fields.Float(required=True)
    calibrator = fields.String(required=False, allow_none=True)
    cert_file = fields.String(required=False, allow_none=True)

class CertificateValidator:
    def __init__(self):
        self.errors = []

    def validate_certificate_data(self, data, equipment):
        self.errors = []

        self._validate_dates(data)
        self._validate_equipment_match(data, equipment)
        self._validate_range(data, equipment)
        self._validate_unit(data, equipment)
        self._validate_deviation(data, equipment)

        return len(self.errors) == 0, self.errors

    def _validate_dates(self, data):
        try:
            cal_date = parser.parse(data['calibration_date']).date()
            valid_until = parser.parse(data['valid_until']).date()

            if valid_until <= cal_date:
                self.errors.append({
                    'field': 'valid_until',
                    'error': f'Valid until date must be after calibration date: {valid_until} <= {cal_date}'
                })

            data['_parsed_cal_date'] = cal_date
            data['_parsed_valid_until'] = valid_until

        except Exception as e:
            self.errors.append({
                'field': 'date',
                'error': f'Invalid date format: {str(e)}'
            })

    def _validate_equipment_match(self, data, equipment):
        if equipment.equipment_no != data['equipment_no']:
            self.errors.append({
                'field': 'equipment_no',
                'error': f'Equipment number mismatch: expected {equipment.equipment_no}, got {data["equipment_no"]}'
            })

    def _validate_range(self, data, equipment):
        if data['range_max'] <= 0:
            self.errors.append({
                'field': 'range_max',
                'error': 'Range max must be positive'
            })

        if equipment.range_min is not None and equipment.range_max is not None:
            if not (equipment.range_min <= data['range_min'] and data['range_max'] <= equipment.range_max):
                self.errors.append({
                    'field': 'range',
                    'error': f'Range {data["range_min"]}-{data["range_max"]} exceeds equipment range {equipment.range_min}-{equipment.range_max}'
                })

        if data['range_min'] >= data['range_max']:
            self.errors.append({
                'field': 'range',
                'error': f'Range min must be less than range max: {data["range_min"]} >= {data["range_max"]}'
            })

    def _validate_unit(self, data, equipment):
        if equipment.unit and equipment.unit != data['unit']:
            self.errors.append({
                'field': 'unit',
                'error': f'Unit mismatch: expected {equipment.unit}, got {data["unit"]}'
            })

    def _validate_deviation(self, data, equipment):
        if data['deviation'] is None:
            self.errors.append({
                'field': 'deviation',
                'error': 'Deviation is required'
            })
        elif equipment.tolerance is not None:
            if abs(data['deviation']) > equipment.tolerance:
                self.errors.append({
                    'field': 'deviation',
                    'error': f'Deviation {data["deviation"]} exceeds tolerance {equipment.tolerance}'
                })

def parse_csv_to_json(csv_content):
    import csv
    import io

    reader = csv.DictReader(io.StringIO(csv_content))
    records = []
    for row in reader:
        record = {}
        for key, value in row.items():
            if key in ['range_min', 'range_max', 'deviation']:
                try:
                    record[key] = float(value) if value else None
                except:
                    record[key] = None
            else:
                record[key] = value
        records.append(record)
    return records
